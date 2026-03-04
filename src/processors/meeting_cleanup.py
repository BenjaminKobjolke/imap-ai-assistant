from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime, timedelta

from dateutil.rrule import rrulestr
from dateutil.tz import UTC as dateutil_UTC
from dateutil.tz import gettz

from src.constants import MIME_TEXT_CALENDAR
from src.processors.meeting_display import (
    extract_meeting_links as _extract_meeting_links_fn,
    list_meetings,
    safe_print,
    show_meeting_detail as _show_detail_fn,
)

logger = logging.getLogger(__name__)


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

        print("\nMeeting cleanup complete:")
        print(f"  Checked: {total} | Moved: {moved} | Kept: {kept} | Skipped: {skipped}")

    @staticmethod
    def get_todays_meetings(client, config, target_date: date | None = None) -> list[dict]:
        """Collect meetings for a given date as a list of dicts.

        Each dict has: index (1-based), start, end, subject, email_message,
        ics_text, parsed.
        """
        folder = config.meetings_folder
        today = target_date or date.today()

        logger.info(f"Scanning '{folder}' for meetings on {today}")

        messages = client.client.get_all_messages(folder=folder)
        if not messages:
            return []

        todays: list[dict] = []
        for _, email_message in messages:
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
                        })

            except Exception as e:
                logger.debug(f"Error checking '{subject}': {e}")

        todays.sort(key=lambda m: m["start"])
        for i, meeting in enumerate(todays, 1):
            meeting["index"] = i

        return todays

    @staticmethod
    def list_todays_meetings(client, config, target_date: date | None = None) -> None:
        """List meetings for a given date with 1-based indices."""
        target = target_date or date.today()
        meetings = MeetingCleanup.get_todays_meetings(client, config, target_date=target)
        list_meetings(meetings, target)

    @staticmethod
    def show_meeting_detail(client, config, index: int) -> None:
        """Show full details for a specific meeting by 1-based index."""
        meetings = MeetingCleanup.get_todays_meetings(client, config)

        if not meetings or index < 1 or index > len(meetings):
            safe_print(f"\nInvalid meeting index: {index}. Use --todays-meetings to see available indices.")
            return

        _show_detail_fn(meetings[index - 1])
