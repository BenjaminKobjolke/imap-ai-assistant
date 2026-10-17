from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta

from dateutil.rrule import rrulestr

from src.interaction.scheduler_prompts import send_output
from src.processors.meeting_display import (
    list_meetings,
)
from src.processors.meeting_display import (
    show_meeting_detail as _show_detail_fn,
)
from src.processors.ics_parser import IcsParser

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
        "id": f"gcal:{event['id']}",
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
                parsed = IcsParser.parse_event_from_email(email_message)

                if parsed is None:
                    logger.warning(f"No calendar data found in '{subject}', skipping")
                    skipped += 1
                    continue

                # Recurring events: keep if they have future occurrences
                if parsed.get('rrule') and IcsParser.has_future_occurrence(
                    parsed, datetime.now(parsed['dtstart'].tzinfo)
                ):
                    logger.debug(f"Kept (recurring, has future occurrences): '{subject}'")
                    kept += 1
                    continue
                # RRULE expired — fall through to archive

                meeting_dt = IcsParser.normalize_to_utc(parsed['dtstart'])

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
        for imap_msg_id, email_message in (messages or []):
            subject = email_message.subject or "(no subject)"
            try:
                ics_data = IcsParser.get_ics_data(email_message)
                ics_text = ics_data.decode('utf-8', errors='replace') if ics_data else None
                parsed = IcsParser.parse_vevent(ics_text) if ics_text else None

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
                                "id": f"imap:{imap_msg_id}",
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
                            "id": f"imap:{imap_msg_id}",
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
                    # Prefer GCal ID for merged meetings
                    imap_m["id"] = gcal_m["id"]
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
    ) -> None:
        """List meetings for a given date."""
        target = target_date or date.today()
        meetings = MeetingCleanup.get_todays_meetings(
            client, config, target_date=target, gcal_client=gcal_client,
        )
        list_meetings(meetings, target)

    @staticmethod
    def show_meeting_detail_by_id(
        client,
        config,
        date_str: str,
        meeting_id: str,
        gcal_client: object | None = None,
    ) -> None:
        """Show full details for a specific meeting by date and ID."""
        target_date = MeetingCleanup._parse_date(date_str)
        meetings = MeetingCleanup.get_todays_meetings(
            client, config, target_date=target_date, gcal_client=gcal_client,
        )

        for m in meetings:
            if m.get("id") == meeting_id:
                _show_detail_fn(m)
                return

        send_output(f"\nMeeting with id {meeting_id} not found for {target_date}.")
