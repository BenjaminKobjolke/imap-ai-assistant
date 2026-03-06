from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime, timedelta

from dateutil.rrule import rrulestr
from dateutil.tz import UTC as dateutil_UTC
from dateutil.tz import gettz

from src.constants import MIME_TEXT_CALENDAR
from src.interaction.scheduler_prompts import send_output
from src.processors.meeting_display import (
    extract_meeting_links as _extract_meeting_links_fn,
)
from src.processors.meeting_display import (
    list_meetings,
)
from src.processors.meeting_display import (
    show_meeting_detail as _show_detail_fn,
)

logger = logging.getLogger(__name__)


def _gcal_event_to_meeting_dict(event: dict, cal_name: str) -> dict | None:
    """Convert a Google Calendar API event to the meeting dict format."""
    start_raw = event.get("start", {})
    end_raw = event.get("end", {})

    start_str = start_raw.get("dateTime")
    if not start_str:
        return None  # skip all-day events

    start_dt = datetime.fromisoformat(start_str).astimezone()
    end_str = end_raw.get("dateTime")
    end_dt = datetime.fromisoformat(end_str).astimezone() if end_str else None

    return {
        "start": start_dt,
        "end": end_dt,
        "subject": event.get("summary", "(no title)"),
        "email_message": None,
        "ics_text": None,
        "parsed": {
            "dtstart": start_dt,
            "dtend": end_dt,
            "rrule": None,
            "organizer": event.get("organizer", {}).get("displayName")
            or event.get("organizer", {}).get("email"),
            "location": event.get("location"),
        },
        "source": "gcal",
        "gcal_event": event,
        "calendar_name": cal_name,
    }


def _is_duplicate(imap_meeting: dict, gcal_meeting: dict) -> bool:
    """Check if a gcal event matches an existing IMAP meeting."""
    time_diff = abs((imap_meeting["start"] - gcal_meeting["start"]).total_seconds())
    if time_diff > 300:  # 5 minutes
        return False
    subj_imap = imap_meeting["subject"].strip().lower()
    subj_gcal = gcal_meeting["subject"].strip().lower()
    return subj_imap == subj_gcal or subj_imap in subj_gcal or subj_gcal in subj_imap


class MeetingCleanup:
    """Handles archiving and listing of meeting emails based on ICS calendar data."""

    @staticmethod
    def _parse_date(value: str) -> date:
        """Parse a flexible date string into a date object.

        Supported formats: today, tomorrow, 5 (day of month), 12.03, 12.03.2026.
        """
        v = value.strip().lower()
        if v == "today":
            return date.today()
        if v == "tomorrow":
            return date.today() + timedelta(days=1)

        # DD.MM.YYYY
        try:
            return datetime.strptime(v, "%d.%m.%Y").date()
        except ValueError:
            pass

        # DD.MM (current year)
        try:
            parsed = datetime.strptime(v, "%d.%m").date()
            return parsed.replace(year=date.today().year)
        except ValueError:
            pass

        # Bare number = day of current month
        try:
            day = int(v)
            now = date.today()
            return date(now.year, now.month, day)
        except (ValueError, OverflowError):
            pass

        msg = (
            f"Invalid date: '{value}'. "
            "Supported formats: today, tomorrow, 5, 12.03, 12.03.2026"
        )
        raise ValueError(msg)

    @staticmethod
    def _get_ics_data(email_message: object) -> bytes | None:
        """Extract raw ICS data from an email message."""
        # Strategy 1: Check attachments for text/calendar
        attachments = getattr(email_message, "attachments", []) or []
        for attachment in attachments:
            if attachment.content_type == MIME_TEXT_CALENDAR and attachment.data:
                return attachment.data

        # Strategy 2: Fall back to text/calendar MIME part
        try:
            calendar_text = email_message.get_body(MIME_TEXT_CALENDAR)
            if calendar_text:
                return calendar_text.encode("utf-8")
        except Exception:
            pass

        return None

    @staticmethod
    def _parse_dt_field(vevent_text: str, field: str) -> datetime | None:
        """Parse a DTSTART or DTEND field from a VEVENT text block."""
        m = re.search(rf'{field}(?:;([^:]*?))?[:]([^\r\n]+)', vevent_text)
        if not m:
            return None

        params, value = m.group(1) or '', m.group(2)

        # Resolve timezone
        tz = None
        tz_m = re.search(r'TZID=([^;:]+)', params)
        if tz_m:
            tz = gettz(tz_m.group(1))
        elif value.endswith('Z'):
            tz = dateutil_UTC
            value = value[:-1]

        # Parse datetime value
        try:
            if 'T' in value:
                dt = datetime.strptime(value, '%Y%m%dT%H%M%S')
            else:
                dt = datetime.strptime(value, '%Y%m%d')
            if tz:
                dt = dt.replace(tzinfo=tz)
            else:
                dt = dt.replace(tzinfo=dateutil_UTC)
            return dt
        except ValueError as e:
            logger.warning(f"Failed to parse {field} value '{value}': {e}")
            return None

    @staticmethod
    def _parse_vevent(ics_text: str) -> dict | None:
        """Parse VEVENT block from ICS text using regex.

        Returns dict with 'dtstart', 'dtend' (datetime), and 'rrule' (str|None),
        or None if parsing fails.
        """
        vevent_m = re.search(r'BEGIN:VEVENT(.*?)END:VEVENT', ics_text, re.DOTALL)
        if not vevent_m:
            return None

        vevent = vevent_m.group(1)
        # Unfold lines per RFC 5545 (continuation lines start with space/tab)
        vevent = re.sub(r'\r?\n[ \t]', '', vevent)

        dtstart = MeetingCleanup._parse_dt_field(vevent, 'DTSTART')
        if dtstart is None:
            return None

        dtend = MeetingCleanup._parse_dt_field(vevent, 'DTEND')

        # Extract RRULE
        rrule = None
        rrule_m = re.search(r'RRULE[:]([^\r\n]+)', vevent)
        if rrule_m:
            rrule = rrule_m.group(1)

        # Extract ORGANIZER (CN param)
        organizer = None
        org_m = re.search(r'ORGANIZER[^:]*?CN=([^;:\r\n]+)', vevent)
        if org_m:
            organizer = org_m.group(1).strip().strip('"')

        # Extract LOCATION
        location = None
        loc_m = re.search(r'LOCATION[:]([^\r\n]+)', vevent)
        if loc_m:
            location = loc_m.group(1).strip()

        return {
            'dtstart': dtstart,
            'dtend': dtend,
            'rrule': rrule,
            'organizer': organizer,
            'location': location,
        }

    @staticmethod
    def _normalize_to_utc(dt: datetime) -> datetime:
        """Convert a timezone-aware datetime to UTC."""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)

    @staticmethod
    def _has_future_occurrence(parsed: dict, after: datetime) -> bool:
        """Check if a recurring event has any occurrence after the given datetime."""
        if not parsed.get('rrule'):
            return False
        try:
            rule = rrulestr(parsed['rrule'], dtstart=parsed['dtstart'])
            next_occ = rule.after(after)
            return next_occ is not None
        except Exception as e:
            logger.warning(f"Failed to evaluate RRULE: {e}")
            return False

    @staticmethod
    def _extract_meeting_links(email_message: object, ics_text: str | None) -> list[dict[str, str]]:
        """Extract meeting URLs from ICS data and email body."""
        return _extract_meeting_links_fn(email_message, ics_text)

    @staticmethod
    def extract_meeting_datetime(email_message: object) -> datetime | None:
        """Extract the meeting start datetime from ICS data in the email.

        Returns a timezone-aware UTC datetime, or None if no calendar data found.
        """
        ics_data = MeetingCleanup._get_ics_data(email_message)
        if ics_data is None:
            return None

        try:
            ics_text = ics_data.decode('utf-8', errors='replace')
            parsed = MeetingCleanup._parse_vevent(ics_text)
            if parsed and parsed['dtstart']:
                return MeetingCleanup._normalize_to_utc(parsed['dtstart'])
        except Exception as e:
            logger.warning(f"Failed to parse ICS data: {e}")

        return None

    @staticmethod
    def extract_meeting_times(email_message: object) -> tuple[datetime | None, datetime | None]:
        """Extract meeting start and end datetimes from ICS data.

        Returns (dtstart, dtend) as timezone-aware UTC datetimes, or (None, None).
        """
        ics_data = MeetingCleanup._get_ics_data(email_message)
        if ics_data is None:
            return None, None

        try:
            ics_text = ics_data.decode('utf-8', errors='replace')
            parsed = MeetingCleanup._parse_vevent(ics_text)
            if parsed and parsed['dtstart']:
                dtstart = MeetingCleanup._normalize_to_utc(parsed['dtstart'])
                dtend = MeetingCleanup._normalize_to_utc(parsed['dtend']) if parsed.get('dtend') else None
                return dtstart, dtend
        except Exception as e:
            logger.warning(f"Failed to parse ICS data: {e}")

        return None, None

    @staticmethod
    def _parse_event_from_email(email_message: object) -> dict | None:
        """Parse the full VEVENT data (including RRULE) from an email."""
        ics_data = MeetingCleanup._get_ics_data(email_message)
        if ics_data is None:
            return None
        try:
            ics_text = ics_data.decode('utf-8', errors='replace')
            return MeetingCleanup._parse_vevent(ics_text)
        except Exception as e:
            logger.warning(f"Failed to parse ICS data: {e}")
            return None

    @staticmethod
    def cleanup_old_meetings(client, config) -> None:
        """Scan the meetings folder and move old meetings to the archive folder.

        Args:
            client: Connected EnhancedImapClient instance
            config: ConfigManager instance
        """
        folder = config.meetings_folder
        archive_folder = config.meetings_archive_folder
        age_limit_hours = config.meetings_age_limit_hours
        cutoff = datetime.now(UTC) - timedelta(hours=age_limit_hours)

        logger.info(f"Scanning '{folder}' for meetings older than {age_limit_hours}h (cutoff: {cutoff.isoformat()})")

        messages = client.client.get_all_messages(folder=folder)
        if not messages:
            logger.info(f"No messages found in '{folder}'")
            return

        total = len(messages)
        moved = 0
        kept = 0
        skipped = 0

        for message_id, email_message in messages:
            subject = email_message.subject or "(no subject)"
            try:
                parsed = MeetingCleanup._parse_event_from_email(email_message)

                if parsed is None:
                    logger.warning(f"No calendar data found in '{subject}', skipping")
                    skipped += 1
                    continue

                # Recurring events: keep if they have future occurrences
                if parsed.get('rrule'):
                    if MeetingCleanup._has_future_occurrence(parsed, datetime.now(parsed['dtstart'].tzinfo)):
                        logger.debug(f"Kept (recurring, has future occurrences): '{subject}'")
                        kept += 1
                        continue
                    # RRULE expired — fall through to archive

                meeting_dt = MeetingCleanup._normalize_to_utc(parsed['dtstart'])

                if meeting_dt < cutoff:
                    # Re-select folder to acknowledge prior expunges
                    client.client.client.select_folder(folder)
                    success = client.client.move_to_folder(message_id, archive_folder)
                    if success:
                        logger.info(f"Moved: '{subject}' (meeting: {meeting_dt.isoformat()})")
                        moved += 1
                    else:
                        logger.error(f"Failed to move: '{subject}'")
                        skipped += 1
                else:
                    logger.debug(f"Kept: '{subject}' (meeting: {meeting_dt.isoformat()})")
                    kept += 1

            except Exception as e:
                logger.error(f"Error processing '{subject}': {e}")
                skipped += 1

        send_output("\nMeeting cleanup complete:")
        send_output(f"  Checked: {total} | Moved: {moved} | Kept: {kept} | Skipped: {skipped}")

    @staticmethod
    def get_todays_meetings(
        client,
        config,
        target_date: date | None = None,
        gcal_client: object | None = None,
    ) -> list[dict]:
        """Collect meetings for a given date as a list of dicts.

        Each dict has: index (1-based), start, end, subject, email_message,
        ics_text, parsed, source.  When *gcal_client* is provided, Google
        Calendar events are merged and deduplicated with IMAP meetings.
        """
        folder = config.meetings_folder
        today = target_date or date.today()

        logger.info(f"Scanning '{folder}' for meetings on {today}")

        messages = client.client.get_all_messages(folder=folder)

        todays: list[dict] = []
        for _, email_message in (messages or []):
            subject = email_message.subject or "(no subject)"
            try:
                ics_data = MeetingCleanup._get_ics_data(email_message)
                ics_text = ics_data.decode('utf-8', errors='replace') if ics_data else None
                parsed = MeetingCleanup._parse_vevent(ics_text) if ics_text else None

                if parsed is None or parsed['dtstart'] is None:
                    continue

                local_tz = parsed['dtstart'].tzinfo

                if parsed.get('rrule'):
                    try:
                        rule = rrulestr(parsed['rrule'], dtstart=parsed['dtstart'])
                        today_start = datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=local_tz)
                        today_end = datetime(today.year, today.month, today.day, 23, 59, 59, tzinfo=local_tz)
                        occurrences = rule.between(today_start, today_end, inc=True)
                        if occurrences:
                            occ_start = occurrences[0].astimezone()
                            if parsed.get('dtend'):
                                duration = parsed['dtend'] - parsed['dtstart']
                                occ_end = (occurrences[0] + duration).astimezone()
                            else:
                                occ_end = None
                            todays.append({
                                "start": occ_start,
                                "end": occ_end,
                                "subject": subject,
                                "email_message": email_message,
                                "ics_text": ics_text,
                                "parsed": parsed,
                                "source": "imap",
                            })
                    except Exception as e:
                        logger.debug(f"Error expanding RRULE for '{subject}': {e}")
                else:
                    local_start = parsed['dtstart'].astimezone()
                    if local_start.date() == today:
                        local_end = parsed['dtend'].astimezone() if parsed.get('dtend') else None
                        todays.append({
                            "start": local_start,
                            "end": local_end,
                            "subject": subject,
                            "email_message": email_message,
                            "ics_text": ics_text,
                            "parsed": parsed,
                            "source": "imap",
                        })

            except Exception as e:
                logger.debug(f"Error checking '{subject}': {e}")

        # -- Merge Google Calendar events --
        if gcal_client is not None:
            try:
                todays = MeetingCleanup._merge_gcal_events(
                    todays, gcal_client, config, today,
                )
            except Exception as e:
                logger.warning(f"Failed to fetch Google Calendar events: {e}")

        todays.sort(key=lambda m: m["start"])
        for i, meeting in enumerate(todays, 1):
            meeting["index"] = i

        return todays

    @staticmethod
    def _merge_gcal_events(
        imap_meetings: list[dict],
        gcal_client: object,
        config: object,
        today: date,
    ) -> list[dict]:
        """Fetch Google Calendar events and merge with IMAP meetings."""
        from dateutil.tz import tzlocal

        local_tz = tzlocal()
        day_start = datetime(today.year, today.month, today.day, 0, 0, 0, tzinfo=local_tz)
        day_end = datetime(today.year, today.month, today.day, 23, 59, 59, tzinfo=local_tz)

        calendar_ids: list[str] = [gcal_client.calendar_id]  # type: ignore[attr-defined]
        calendar_ids.extend(config.free_check_calendar_ids)  # type: ignore[attr-defined]

        # Build calendar name lookup
        cal_names: dict[str, str] = {}
        try:
            for cal in gcal_client.list_calendars():  # type: ignore[attr-defined]
                cal_names[cal.get("id", "")] = cal.get("summary", cal.get("id", ""))
        except Exception:
            pass

        seen_event_ids: set[str] = set()
        gcal_meetings: list[dict] = []
        for cal_id in calendar_ids:
            cal_name = cal_names.get(cal_id, cal_id)
            events = gcal_client.list_events_in_range(cal_id, day_start, day_end)  # type: ignore[attr-defined]
            for event in events:
                event_id = event.get("id", "")
                if event_id in seen_event_ids:
                    continue
                seen_event_ids.add(event_id)
                meeting = _gcal_event_to_meeting_dict(event, cal_name)
                if meeting is not None:
                    gcal_meetings.append(meeting)

        # Deduplicate: mark matching IMAP meetings as "both"
        for gcal_m in gcal_meetings:
            matched = False
            for imap_m in imap_meetings:
                if _is_duplicate(imap_m, gcal_m):
                    imap_m["source"] = "both"
                    imap_m.setdefault("gcal_event", gcal_m.get("gcal_event"))
                    imap_m.setdefault("calendar_name", gcal_m.get("calendar_name"))
                    matched = True
                    break
            if not matched:
                imap_meetings.append(gcal_m)

        return imap_meetings

    @staticmethod
    def list_todays_meetings(
        client,
        config,
        target_date: date | None = None,
        gcal_client: object | None = None,
        *,
        interactive: bool = True,
    ) -> None:
        """List meetings for a given date with optional interactive detail selection."""
        target = target_date or date.today()
        meetings = MeetingCleanup.get_todays_meetings(
            client, config, target_date=target, gcal_client=gcal_client,
        )
        list_meetings(meetings, target)

        if not meetings or not interactive:
            return

        max_idx = len(meetings)
        while True:
            raw = input(f"\nEnter meeting number [1-{max_idx}] or 'q' to quit: ").strip().lower()
            if raw in ("q", "quit", ""):
                break
            try:
                idx = int(raw)
                if 1 <= idx <= max_idx:
                    _show_detail_fn(meetings[idx - 1])
                else:
                    send_output(f"  Please enter 1-{max_idx}")
            except ValueError:
                send_output(f"  Please enter 1-{max_idx}")

    @staticmethod
    def show_meeting_detail(client, config, index: int) -> None:
        """Show full details for a specific meeting by 1-based index."""
        meetings = MeetingCleanup.get_todays_meetings(client, config)

        if not meetings or index < 1 or index > len(meetings):
            send_output(f"\nInvalid meeting index: {index}. Use --todays-meetings to see available indices.")
            return

        _show_detail_fn(meetings[index - 1])
