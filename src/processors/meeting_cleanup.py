from __future__ import annotations

import logging
import re
import subprocess
import webbrowser
from datetime import datetime, date, timezone, timedelta
from typing import Optional, Tuple

from dateutil.tz import gettz, UTC as dateutil_UTC
from dateutil.rrule import rrulestr

logger = logging.getLogger(__name__)


def _safe_print(text):
    """Print text safely on Windows console by replacing unencodable chars."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))


class MeetingCleanup:
    """Handles archiving and listing of meeting emails based on ICS calendar data."""

    @staticmethod
    def _get_ics_data(email_message) -> Optional[bytes]:
        """Extract raw ICS data from an email message."""
        # Strategy 1: Check attachments for text/calendar
        attachments = getattr(email_message, "attachments", []) or []
        for attachment in attachments:
            if attachment.content_type == "text/calendar" and attachment.data:
                return attachment.data

        # Strategy 2: Fall back to text/calendar MIME part
        try:
            calendar_text = email_message.get_body("text/calendar")
            if calendar_text:
                return calendar_text.encode("utf-8")
        except Exception:
            pass

        return None

    @staticmethod
    def _parse_dt_field(vevent_text: str, field: str) -> Optional[datetime]:
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
    def _parse_vevent(ics_text: str) -> Optional[dict]:
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
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

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
    def _extract_meeting_links(email_message, ics_text: str | None) -> list[dict[str, str]]:
        """Extract meeting URLs from ICS data and email body.

        Returns a list of dicts with 'type' and 'url' keys.
        """
        seen_urls: set[str] = set()
        links: list[dict[str, str]] = []

        # Base paths without an actual meeting identifier
        _generic_paths = re.compile(
            r'^https://teams\.microsoft\.com/l/meetup-join/?$'
            r'|^https://teams\.microsoft\.com/?$'
            r'|^https://(?:[\w-]+\.)?zoom\.us/j/?$'
            r'|^https://meet\.google\.com/?$'
        )

        def _add(link_type: str, url: str) -> None:
            if url in seen_urls:
                return
            if _generic_paths.match(url):
                return
            seen_urls.add(url)
            links.append({"type": link_type, "url": url})

        # 1. ICS: X-MICROSOFT-SKYPETEAMSMEETINGURL
        if ics_text:
            skype_m = re.search(r'X-MICROSOFT-SKYPETEAMSMEETINGURL[:]([^\r\n]+)', ics_text)
            if skype_m:
                _add("Teams", skype_m.group(1).strip())

        # 2. Email plain-text body
        body = ""
        try:
            body = email_message.get_body("text/plain") or ""
        except Exception:
            pass

        url_patterns = [
            ("Teams", r'https://teams\.microsoft\.com/[^\s<>"]+'),
            ("Zoom", r'https://(?:[\w-]+\.)?zoom\.us/j/[^\s<>"]+'),
            ("Google Meet", r'https://meet\.google\.com/[^\s<>"]+'),
        ]
        for link_type, pattern in url_patterns:
            for m in re.finditer(pattern, body):
                _add(link_type, m.group(0))

        # 3. ICS LOCATION (if it looks like a URL)
        if ics_text:
            loc_m = re.search(r'LOCATION[:]([^\r\n]+)', ics_text)
            if loc_m:
                loc_val = loc_m.group(1).strip()
                if loc_val.startswith("http"):
                    _add("Location link", loc_val)

        return links

    @staticmethod
    def extract_meeting_datetime(email_message) -> Optional[datetime]:
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
    def extract_meeting_times(email_message) -> Tuple[Optional[datetime], Optional[datetime]]:
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
    def _parse_event_from_email(email_message) -> Optional[dict]:
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
        cutoff = datetime.now(timezone.utc) - timedelta(hours=age_limit_hours)

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

        print(f"\nMeeting cleanup complete:")
        print(f"  Checked: {total} | Moved: {moved} | Kept: {kept} | Skipped: {skipped}")

    @staticmethod
    def get_todays_meetings(client, config) -> list[dict]:
        """Collect today's meetings as a list of dicts.

        Each dict has: index (1-based), start, end, subject, email_message,
        ics_text, parsed.
        """
        folder = config.meetings_folder
        today = datetime.now().date()

        logger.info(f"Scanning '{folder}' for today's meetings ({today})")

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
    def list_todays_meetings(client, config) -> None:
        """List all meetings scheduled for today with 1-based indices.

        Args:
            client: Connected EnhancedImapClient instance
            config: ConfigManager instance
        """
        today = datetime.now().date()
        meetings = MeetingCleanup.get_todays_meetings(client, config)

        if not meetings:
            print(f"\nNo meetings today ({today})")
            return

        _safe_print(f"\nToday's meetings ({today}):\n")
        for m in meetings:
            start_str = m["start"].strftime("%H:%M")
            end_str = m["end"].strftime("%H:%M") if m["end"] else "??:??"
            _safe_print(f"  {m['index']:>2}.  {start_str} - {end_str}  {m['subject']}")
        _safe_print(f"\nTotal: {len(meetings)} meeting(s)")

    @staticmethod
    def show_meeting_detail(client, config, index: int) -> None:
        """Show full details for a specific meeting by 1-based index.

        Extracts meeting links and copies/opens the first one found.
        """
        meetings = MeetingCleanup.get_todays_meetings(client, config)

        if not meetings or index < 1 or index > len(meetings):
            _safe_print(f"\nInvalid meeting index: {index}. Use --todays-meetings to see available indices.")
            return

        m = meetings[index - 1]
        start_str = m["start"].strftime("%H:%M")
        end_str = m["end"].strftime("%H:%M") if m["end"] else "??:??"

        organizer = m["parsed"].get("organizer") or "(unknown)"
        location = m["parsed"].get("location") or "(none)"
        links = MeetingCleanup._extract_meeting_links(m["email_message"], m["ics_text"])

        _safe_print(f"\nMeeting #{index}: {m['subject']}\n")
        _safe_print(f"  Time:       {start_str} - {end_str}")
        _safe_print(f"  Organizer:  {organizer}")
        _safe_print(f"  Location:   {location}")

        if links:
            _safe_print("\n  Links:")
            for i, link in enumerate(links, 1):
                _safe_print(f"    {i}. {link['type']}: {link['url']}")

            _safe_print("\n  [c] Copy link to clipboard")
            _safe_print("  [o] Open link in browser")
            _safe_print("  [a] Abort")
            choice = input("\n  > ").strip().lower()

            if choice in ("c", "o"):
                # Pick link index (skip prompt if only one link)
                if len(links) == 1:
                    link_idx = 0
                else:
                    idx_input = input(f"  Link number [1-{len(links)}]: ").strip()
                    try:
                        link_idx = int(idx_input) - 1
                        if link_idx < 0 or link_idx >= len(links):
                            _safe_print("  Invalid link number. Aborted.")
                            return
                    except ValueError:
                        _safe_print("  Invalid input. Aborted.")
                        return

                url = links[link_idx]["url"]
                if choice == "c":
                    try:
                        subprocess.run(["clip"], input=url, text=True, check=False)
                        _safe_print("  Link copied to clipboard.")
                    except Exception:
                        _safe_print("  Failed to copy to clipboard.")
                else:
                    try:
                        webbrowser.open(url)
                        _safe_print("  Link opened in browser.")
                    except Exception:
                        _safe_print("  Failed to open browser.")
            else:
                _safe_print("  Aborted.")
        else:
            _safe_print("\n  Links:      (none found)")
