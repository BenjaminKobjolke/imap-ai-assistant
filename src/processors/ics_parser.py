from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from dateutil.rrule import rrulestr
from dateutil.tz import UTC as DATEUTIL_UTC
from dateutil.tz import gettz

from src.constants import MIME_TEXT_CALENDAR
from src.processors.meeting_display import extract_meeting_links

logger = logging.getLogger(__name__)


class IcsParser:
    """Extract and parse calendar data embedded in email messages."""

    @staticmethod
    def get_ics_data(email_message: object) -> bytes | None:
        """Extract raw ICS bytes from an attachment or calendar MIME part."""
        attachments = getattr(email_message, "attachments", []) or []
        for attachment in attachments:
            if attachment.content_type == MIME_TEXT_CALENDAR and attachment.data:
                return attachment.data

        try:
            calendar_text = email_message.get_body(MIME_TEXT_CALENDAR)
            if calendar_text:
                return calendar_text.encode("utf-8")
        except Exception:
            pass
        return None

    @staticmethod
    def parse_dt_field(vevent_text: str, field: str) -> datetime | None:
        """Parse a DTSTART or DTEND field from one VEVENT text block."""
        match = re.search(rf'{field}(?:;([^:]*?))?[:]([^\r\n]+)', vevent_text)
        if not match:
            return None

        params, value = match.group(1) or "", match.group(2)
        timezone = None
        timezone_match = re.search(r"TZID=([^;:]+)", params)
        if timezone_match:
            timezone = gettz(timezone_match.group(1))
        elif value.endswith("Z"):
            timezone = DATEUTIL_UTC
            value = value[:-1]

        try:
            parsed = datetime.strptime(value, "%Y%m%dT%H%M%S") if "T" in value else datetime.strptime(value, "%Y%m%d")
            return parsed.replace(tzinfo=timezone or DATEUTIL_UTC)
        except ValueError as error:
            logger.warning("Failed to parse %s value '%s': %s", field, value, error)
            return None

    @staticmethod
    def parse_vevent(ics_text: str) -> dict | None:
        """Parse event dates, recurrence, organizer and location from ICS text."""
        event_match = re.search(r"BEGIN:VEVENT(.*?)END:VEVENT", ics_text, re.DOTALL)
        if not event_match:
            return None

        event_text = re.sub(r"\r?\n[ \t]", "", event_match.group(1))
        start = IcsParser.parse_dt_field(event_text, "DTSTART")
        if start is None:
            return None
        end = IcsParser.parse_dt_field(event_text, "DTEND")
        recurrence_match = re.search(r"RRULE[:]([^\r\n]+)", event_text)
        organizer_match = re.search(r"ORGANIZER[^:]*?CN=([^;:\r\n]+)", event_text)
        location_match = re.search(r"LOCATION[:]([^\r\n]+)", event_text)
        return {
            "dtstart": start,
            "dtend": end,
            "rrule": recurrence_match.group(1) if recurrence_match else None,
            "organizer": organizer_match.group(1).strip().strip('"') if organizer_match else None,
            "location": location_match.group(1).strip() if location_match else None,
        }

    @staticmethod
    def normalize_to_utc(value: datetime) -> datetime:
        """Convert a datetime to UTC, treating naive values as UTC."""
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    @staticmethod
    def has_future_occurrence(parsed: dict, after: datetime) -> bool:
        """Check whether the parsed recurring event has a future occurrence."""
        if not parsed.get("rrule"):
            return False
        try:
            rule = rrulestr(parsed["rrule"], dtstart=parsed["dtstart"])
            return rule.after(after) is not None
        except Exception as error:
            logger.warning("Failed to evaluate RRULE: %s", error)
            return False

    @staticmethod
    def extract_meeting_links(email_message: object, ics_text: str | None) -> list[dict[str, str]]:
        """Extract meeting URLs from ICS data and the email body."""
        return extract_meeting_links(email_message, ics_text)

    @staticmethod
    def extract_meeting_datetime(email_message: object) -> datetime | None:
        """Return the meeting start as UTC when calendar data is available."""
        ics_data = IcsParser.get_ics_data(email_message)
        if ics_data is None:
            return None
        try:
            parsed = IcsParser.parse_vevent(ics_data.decode("utf-8", errors="replace"))
            if parsed and parsed["dtstart"]:
                return IcsParser.normalize_to_utc(parsed["dtstart"])
        except Exception as error:
            logger.warning("Failed to parse ICS data: %s", error)
        return None

    @staticmethod
    def extract_meeting_times(email_message: object) -> tuple[datetime | None, datetime | None]:
        """Return the event start and end as UTC datetimes."""
        ics_data = IcsParser.get_ics_data(email_message)
        if ics_data is None:
            return None, None
        try:
            parsed = IcsParser.parse_vevent(ics_data.decode("utf-8", errors="replace"))
            if parsed and parsed["dtstart"]:
                start = IcsParser.normalize_to_utc(parsed["dtstart"])
                end = IcsParser.normalize_to_utc(parsed["dtend"]) if parsed.get("dtend") else None
                return start, end
        except Exception as error:
            logger.warning("Failed to parse ICS data: %s", error)
        return None, None

    @staticmethod
    def parse_event_from_email(email_message: object) -> dict | None:
        """Parse full VEVENT details, including recurrence, from an email."""
        ics_data = IcsParser.get_ics_data(email_message)
        if ics_data is None:
            return None
        try:
            return IcsParser.parse_vevent(ics_data.decode("utf-8", errors="replace"))
        except Exception as error:
            logger.warning("Failed to parse ICS data: %s", error)
            return None
