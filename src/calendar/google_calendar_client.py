"""Google Calendar API client with OAuth2 authentication."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import ClassVar

logger = logging.getLogger(__name__)


class GoogleCalendarClient:
    """Wraps the Google Calendar API with OAuth2 auth and event operations."""

    SCOPES: ClassVar[list[str]] = ["https://www.googleapis.com/auth/calendar"]
    OAUTH_PORT: ClassVar[int] = 51032

    def __init__(
        self,
        credentials_path: str = "credentials.json",
        token_path: str = "token.json",
        calendar_id: str = "primary",
    ) -> None:
        """Initialize with paths for OAuth credentials, stored token, and target calendar."""
        self.credentials_path = Path(credentials_path)
        self.token_path = Path(token_path)
        self.calendar_id = calendar_id
        self.service = None

    @classmethod
    def from_config(
        cls,
        config: object,
        *,
        calendar_id: str | None = None,
    ) -> GoogleCalendarClient | None:
        """Create and authenticate a client from a ConfigManager.

        Returns the authenticated client, or ``None`` when authentication
        fails (e.g. missing credentials file, no browser available).
        """
        client = cls(
            credentials_path=config.google_calendar_credentials_path,  # type: ignore[attr-defined]
            token_path=config.google_calendar_token_path,  # type: ignore[attr-defined]
            calendar_id=calendar_id or config.accepts_meetings_calendar_id,  # type: ignore[attr-defined]
        )
        if not client.authenticate():
            return None
        return client

    def authenticate(self) -> bool:
        """Authenticate with Google Calendar API using OAuth2.

        On first run opens a browser for consent and stores the token.
        Subsequent runs reuse and auto-refresh the stored token.
        """
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build

        creds: Credentials | None = None

        if self.token_path.exists():
            creds = Credentials.from_authorized_user_file(str(self.token_path), self.SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except Exception:
                    logger.warning("Token refresh failed, re-authenticating")
                    creds = None

            if not creds:
                if not self.credentials_path.exists():
                    logger.error(
                        "Google Calendar credentials file not found: %s. "
                        "Download it from Google Cloud Console.",
                        self.credentials_path,
                    )
                    return False
                flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_path), self.SCOPES)
                creds = flow.run_local_server(port=self.OAUTH_PORT)

            self.token_path.write_text(creds.to_json())

        self.service = build("calendar", "v3", credentials=creds)
        return True

    def event_exists(self, uid: str | None, summary: str, start_time: datetime | None) -> bool:
        """Check whether an event already exists in the calendar.

        Primary lookup by ICS UID, fallback by summary plus start time.
        """
        if uid:
            found = self._find_event_by_uid(uid)
            if found:
                return True

        if start_time:
            found = self._find_event_by_summary_and_time(summary, start_time)
            if found:
                return True

        return False

    def delete_event(self, uid: str | None, summary: str, start_time: datetime | None) -> bool:
        """Delete an event from the calendar, found by UID or summary+time fallback."""
        if not self.service:
            logger.error("Google Calendar service not initialized")
            return False

        event: dict | None = None
        if uid:
            event = self._find_event_by_uid(uid)
        if not event and start_time:
            event = self._find_event_by_summary_and_time(summary, start_time)
        if not event:
            logger.warning("Cannot delete event: not found in calendar")
            return False

        try:
            self.service.events().delete(
                calendarId=self.calendar_id, eventId=event["id"],
            ).execute()
            logger.info("Deleted event from Google Calendar, id=%s", event["id"])
            return True
        except Exception as e:
            logger.error("Failed to delete event from Google Calendar: %s", e)
            return False

    def delete_event_by_id(self, event_id: str) -> bool:
        """Delete a calendar event by its Google Calendar event ID."""
        if not self.service:
            logger.error("Google Calendar service not initialized")
            return False
        try:
            self.service.events().delete(
                calendarId=self.calendar_id, eventId=event_id,
            ).execute()
            logger.info("Deleted event from Google Calendar, id=%s", event_id)
            return True
        except Exception as e:
            logger.error("Failed to delete event by ID: %s", e)
            return False

    def create_event(self, summary: str, start_dt: datetime, end_dt: datetime) -> str | None:
        """Create a calendar event from explicit start/end datetimes.

        Uses Europe/Berlin timezone. Returns the Google Calendar event ID on success, None on failure.
        """
        if not self.service:
            logger.error("Google Calendar service not initialized")
            return None

        event_body = {
            "summary": summary,
            "start": {"dateTime": start_dt.isoformat(), "timeZone": "Europe/Berlin"},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": "Europe/Berlin"},
        }

        try:
            result = self.service.events().insert(
                calendarId=self.calendar_id, body=event_body, sendUpdates="none",
            ).execute()
            event_id = result.get("id")
            logger.info("Event created in Google Calendar, id=%s", event_id)
            return event_id
        except Exception as e:
            logger.error("Failed to create event in Google Calendar: %s", e)
            return None

    def add_event_from_ics(self, ics_data: bytes) -> str | None:
        """Import an event from raw ICS data into Google Calendar.

        Uses events().import_() which preserves the original ICS UID.
        Returns the Google Calendar event ID on success, None on failure.
        """
        if not self.service:
            logger.error("Google Calendar service not initialized")
            return None

        try:
            from icalendar import Calendar

            cal = Calendar.from_ical(ics_data)
            for component in cal.walk():
                if component.name != "VEVENT":
                    continue

                event_body = self._vevent_to_google_event(component)
                try:
                    result = self.service.events().import_(calendarId=self.calendar_id, body=event_body).execute()
                except Exception:
                    logger.debug("import_() failed, falling back to insert()")
                    insert_body = {k: v for k, v in event_body.items() if k != "iCalUID"}
                    result = self.service.events().insert(
                        calendarId=self.calendar_id, body=insert_body, sendUpdates="none",
                    ).execute()
                event_id = result.get("id")
                logger.info("Event imported to Google Calendar, id=%s", event_id)
                return event_id

            logger.warning("No VEVENT found in ICS data")
            return None
        except Exception as e:
            logger.error("Failed to import event to Google Calendar: %s", e)
            return None

    def list_events_in_range(self, calendar_id: str, time_min: datetime, time_max: datetime) -> list[dict]:
        """List events from a calendar within a time range for conflict detection."""
        if not self.service:
            return []

        try:
            min_dt = time_min
            max_dt = time_max
            if min_dt.tzinfo is not None:
                min_dt = min_dt.astimezone(UTC).replace(tzinfo=None)
                max_dt = max_dt.astimezone(UTC).replace(tzinfo=None)
            results = self.service.events().list(
                calendarId=calendar_id,
                timeMin=f"{min_dt.isoformat()}Z",
                timeMax=f"{max_dt.isoformat()}Z",
                singleEvents=True,
                orderBy="startTime",
                showDeleted=False,
            ).execute()
            return results.get("items", [])
        except Exception as e:
            logger.error("Error listing events in range for %s: %s", calendar_id, e)
            return []

    def test_connection(self) -> bool:
        """Test the Google Calendar API connection."""
        if not self.service:
            return False
        try:
            self.service.calendarList().get(calendarId=self.calendar_id).execute()
            logger.info("Google Calendar connection test successful")
            return True
        except Exception as e:
            logger.error("Google Calendar connection test failed: %s", e)
            return False

    def _find_event_by_uid(self, uid: str) -> dict | None:
        """Search for an event by its iCalendar UID."""
        if not self.service:
            return None
        try:
            results = self.service.events().list(
                calendarId=self.calendar_id,
                iCalUID=uid,
                showDeleted=False,
            ).execute()
            items = results.get("items", [])
            return items[0] if items else None
        except Exception as e:
            logger.error("Error searching for event by UID: %s", e)
            return None

    def _find_event_by_summary_and_time(self, summary: str, start_time: datetime) -> dict | None:
        """Fallback duplicate detection by summary and start time window."""
        if not self.service:
            return None
        try:
            dt_min = start_time - timedelta(minutes=5)
            dt_max = start_time + timedelta(minutes=5)
            if dt_min.tzinfo is not None:
                dt_min = dt_min.astimezone(UTC).replace(tzinfo=None)
                dt_max = dt_max.astimezone(UTC).replace(tzinfo=None)
            time_min = dt_min.isoformat() + "Z"
            time_max = dt_max.isoformat() + "Z"
            results = self.service.events().list(
                calendarId=self.calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                q=summary,
                showDeleted=False,
            ).execute()
            items = results.get("items", [])
            return items[0] if items else None
        except Exception as e:
            logger.error("Error searching for event by summary and time: %s", e)
            return None

    def list_calendars(self) -> list[dict]:
        """Fetch all calendars visible to the authenticated user.

        Useful for discovering calendar IDs to use in configuration.
        """
        if not self.service:
            logger.error("Google Calendar service not initialized")
            return []
        try:
            result = self.service.calendarList().list().execute()
            return result.get("items", [])
        except Exception as e:
            logger.error("Failed to list calendars: %s", e)
            return []

    @staticmethod
    def _vevent_to_google_event(vevent) -> dict:
        """Convert an icalendar VEVENT component to a Google Calendar event body."""
        event: dict = {}

        uid = vevent.get("uid")
        if uid:
            event["iCalUID"] = str(uid)

        summary = vevent.get("summary")
        if summary:
            event["summary"] = str(summary)

        location = vevent.get("location")
        if location:
            event["location"] = str(location)

        description = vevent.get("description")
        if description:
            event["description"] = str(description)

        dtstart = vevent.get("dtstart")
        if dtstart:
            dt = dtstart.dt
            if isinstance(dt, datetime):
                event["start"] = {"dateTime": dt.isoformat(), "timeZone": "UTC"}
            else:
                event["start"] = {"date": dt.isoformat()}

        dtend = vevent.get("dtend")
        if dtend:
            dt = dtend.dt
            if isinstance(dt, datetime):
                event["end"] = {"dateTime": dt.isoformat(), "timeZone": "UTC"}
            else:
                event["end"] = {"date": dt.isoformat()}

        organizer = vevent.get("organizer")
        if organizer:
            org_email = str(organizer).replace("mailto:", "").replace("MAILTO:", "")
            cn = organizer.params.get("CN", "") if hasattr(organizer, "params") else ""
            event["organizer"] = {"email": org_email}
            if cn:
                event["organizer"]["displayName"] = str(cn)

        rrule = vevent.get("rrule")
        if rrule:
            event["recurrence"] = [f"RRULE:{rrule.to_ical().decode()}"]

        return event
