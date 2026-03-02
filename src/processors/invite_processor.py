"""Interactive processor for meeting invite emails with Google Calendar integration."""

from __future__ import annotations

import logging
import re
import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.nonmultipart import MIMENonMultipart
from email.mime.text import MIMEText

from src.calendar.google_calendar_client import GoogleCalendarClient
from src.config.settings import ConfigManager
from src.email.imap_client import EnhancedImapClient
from src.processors.meeting_cleanup import MeetingCleanup

logger = logging.getLogger(__name__)


def _safe_print(text: str) -> None:
    """Print text safely on Windows console by replacing unencodable chars."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", errors="replace").decode("ascii"))


@dataclass
class ParsedInvite:
    """Holds parsed data from a calendar invite email."""

    message_id: object
    email_message: object
    subject: str
    ics_data: bytes
    uid: str | None
    summary: str | None
    dtstart: datetime | None
    dtend: datetime | None
    organizer: str | None
    organizer_email: str | None
    location: str | None
    method: str | None

    @property
    def is_cancellation(self) -> bool:
        """Whether this invite is a METHOD:CANCEL cancellation."""
        return bool(self.method and self.method.upper() == "CANCEL")


class InviteProcessor:
    """Processes meeting invite emails interactively with Google Calendar."""

    @staticmethod
    def select_calendar(gcal_client: GoogleCalendarClient, config: ConfigManager) -> None:
        """Use the stored calendar or let the user pick one interactively."""
        if gcal_client.calendar_id != "primary":
            _safe_print(f"\nUsing calendar: {gcal_client.calendar_id}")
            return

        calendars = gcal_client.list_calendars()
        if not calendars:
            _safe_print("Could not retrieve calendars. Using current setting.")
            return

        _safe_print("\nNo calendar configured yet. Please pick one:\n")
        for i, cal in enumerate(calendars, 1):
            summary = cal.get("summary", "(unnamed)")
            cal_id = cal.get("id", "")
            primary = " (primary)" if cal.get("primary") else ""
            _safe_print(f"  {i}. {summary}{primary} — {cal_id}")

        while True:
            choice = input("  > ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(calendars):
                selected = calendars[int(choice) - 1]
                gcal_client.calendar_id = selected["id"]
                config.save_setting(
                    ["meetings", "google_calendar", "accepts_meetings_calendar"],
                    {"name": selected.get("summary", ""), "id": selected["id"]},
                )
                _safe_print(f"  Saved: {selected.get('summary', '')} ({selected['id']})")
                return
            _safe_print("  Invalid choice. Try again.")

    @staticmethod
    def process_invites(
        client: EnhancedImapClient,
        config: ConfigManager,
        gcal_client: GoogleCalendarClient,
        account_config: dict,
    ) -> None:
        """Scan for invites and let the user accept, decline, or skip each one."""
        folder = config.meetings_invite_scan_folder

        InviteProcessor.select_calendar(gcal_client, config)

        _safe_print(f"\nScanning '{folder}' for meeting invites...")

        invites = InviteProcessor._scan_for_invites(client, folder)
        if not invites:
            _safe_print("No meeting invites found.")
            return

        _safe_print(f"Found {len(invites)} invite(s).\n")

        added = 0
        deleted = 0
        archived = 0
        skipped = 0

        for i, invite in enumerate(invites, 1):
            already_exists = gcal_client.event_exists(
                uid=invite.uid,
                summary=invite.summary or invite.subject,
                start_time=invite.dtstart,
            )

            conflicts = None
            if invite.dtstart and not invite.is_cancellation:
                conflicts = InviteProcessor._find_conflicts(
                    gcal_client, config, invite.dtstart, invite.dtend,
                )

            InviteProcessor._display_invite(invite, i, len(invites), already_exists, conflicts)

            if invite.is_cancellation:
                action = InviteProcessor._prompt_cancellation(already_exists)

                if action == "delete":
                    success = gcal_client.delete_event(
                        uid=invite.uid,
                        summary=invite.summary or invite.subject,
                        start_time=invite.dtstart,
                    )
                    if success:
                        _safe_print("  Deleted from Google Calendar.")
                        deleted += 1
                    else:
                        _safe_print("  Failed to delete from Google Calendar.")

                    InviteProcessor._archive_invite(
                        client, config, invite.message_id, folder,
                    )
                    _safe_print("  Moved to archive folder.")

                elif action == "archive":
                    success = InviteProcessor._archive_invite(
                        client, config, invite.message_id, folder,
                    )
                    if success:
                        _safe_print("  Moved to archive folder.")
                        archived += 1
                    else:
                        _safe_print("  Failed to archive.")
                        skipped += 1

                else:
                    skipped += 1

                print()
                continue

            action = InviteProcessor._prompt_user(already_exists)

            if action == "yes":
                success = InviteProcessor._add_to_calendar(gcal_client, invite)
                if success:
                    _safe_print("  Added to Google Calendar.")
                    added += 1

                    rsvp_choice = InviteProcessor._prompt_rsvp(invite)
                    if rsvp_choice:
                        InviteProcessor._handle_rsvp(
                            client, config, account_config, invite,
                        )

                    InviteProcessor._move_to_meetings(client, config, invite.message_id, folder)
                    _safe_print("  Moved to meetings folder.")
                else:
                    _safe_print("  Failed to add to Google Calendar.")
                    skipped += 1
                    continue

            elif action == "no":
                success = InviteProcessor._archive_invite(client, config, invite.message_id, folder)
                if success:
                    _safe_print("  Moved to archive folder.")
                    archived += 1
                else:
                    _safe_print("  Failed to archive.")
                    skipped += 1

            else:
                skipped += 1

            print()

        _safe_print(
            f"\nSummary: {len(invites)} invite(s) processed | "
            f"{added} added | {deleted} deleted | {archived} archived | {skipped} skipped"
        )

    @staticmethod
    def _scan_for_invites(client: EnhancedImapClient, folder: str) -> list[ParsedInvite]:
        """Scan a folder for emails containing calendar invites."""
        messages = client.client.get_all_messages(folder=folder)
        if not messages:
            return []

        invites: list[ParsedInvite] = []
        for message_id, email_message in messages:
            ics_data = MeetingCleanup._get_ics_data(email_message)
            if ics_data is None:
                continue

            details = InviteProcessor._parse_invite_details(ics_data)
            subject = email_message.subject or "(no subject)"

            invites.append(ParsedInvite(
                message_id=message_id,
                email_message=email_message,
                subject=subject,
                ics_data=ics_data,
                uid=details.get("uid"),
                summary=details.get("summary"),
                dtstart=details.get("dtstart"),
                dtend=details.get("dtend"),
                organizer=details.get("organizer"),
                organizer_email=details.get("organizer_email"),
                location=details.get("location"),
                method=details.get("method"),
            ))

        return invites

    @staticmethod
    def _parse_invite_details(ics_data: bytes) -> dict:
        """Parse ICS data using the icalendar library for full detail extraction."""
        result: dict = {}
        try:
            from icalendar import Calendar

            cal = Calendar.from_ical(ics_data)
            result["method"] = str(cal.get("method", "")) or None

            for component in cal.walk():
                if component.name != "VEVENT":
                    continue

                uid = component.get("uid")
                if uid:
                    result["uid"] = str(uid)

                summary = component.get("summary")
                if summary:
                    result["summary"] = str(summary)

                location = component.get("location")
                if location:
                    result["location"] = str(location)

                dtstart = component.get("dtstart")
                if dtstart:
                    dt = dtstart.dt
                    if isinstance(dt, datetime):
                        result["dtstart"] = dt
                    else:
                        result["dtstart"] = datetime(dt.year, dt.month, dt.day)

                dtend = component.get("dtend")
                if dtend:
                    dt = dtend.dt
                    if isinstance(dt, datetime):
                        result["dtend"] = dt
                    else:
                        result["dtend"] = datetime(dt.year, dt.month, dt.day)

                organizer = component.get("organizer")
                if organizer:
                    org_email = str(organizer).replace("mailto:", "").replace("MAILTO:", "")
                    result["organizer_email"] = org_email
                    cn = organizer.params.get("CN", "") if hasattr(organizer, "params") else ""
                    result["organizer"] = str(cn) if cn else org_email

                break  # Only process the first VEVENT

        except Exception as e:
            logger.warning("Failed to parse ICS with icalendar library: %s", e)
            # Fallback to regex-based parsing
            try:
                ics_text = ics_data.decode("utf-8", errors="replace")
                parsed = MeetingCleanup._parse_vevent(ics_text)
                if parsed:
                    result["dtstart"] = parsed.get("dtstart")
                    result["dtend"] = parsed.get("dtend")
                    result["organizer"] = parsed.get("organizer")
                    result["location"] = parsed.get("location")

                    uid_m = re.search(r"UID[:]([^\r\n]+)", ics_text)
                    if uid_m:
                        result["uid"] = uid_m.group(1).strip()
                    summary_m = re.search(r"SUMMARY[:]([^\r\n]+)", ics_text)
                    if summary_m:
                        result["summary"] = summary_m.group(1).strip()
            except Exception as fallback_err:
                logger.error("Fallback ICS parsing also failed: %s", fallback_err)

        return result

    @staticmethod
    def _find_conflicts(
        gcal_client: GoogleCalendarClient,
        config: ConfigManager,
        dtstart: datetime,
        dtend: datetime | None,
    ) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
        """Find events near the invite time, split into overlapping and nearby.

        Returns (overlapping, nearby) where each is a list of
        (calendar_name, event_summary, time_range) tuples.
        Overlapping: event_start < invite_end AND event_end > invite_start.
        Nearby: everything else within the 30-min buffer window.
        """
        buffer = timedelta(minutes=30)
        invite_end = dtend or dtstart
        query_start = dtstart - buffer
        query_end = invite_end + buffer

        calendar_ids = [gcal_client.calendar_id, *config.free_check_calendar_ids]

        # Build a name lookup from available calendars
        cal_names: dict[str, str] = {}
        for cal in gcal_client.list_calendars():
            cal_names[cal.get("id", "")] = cal.get("summary", cal.get("id", ""))

        overlapping: list[tuple[str, str, str]] = []
        nearby: list[tuple[str, str, str]] = []
        for cal_id in calendar_ids:
            events = gcal_client.list_events_in_range(cal_id, query_start, query_end)
            cal_name = cal_names.get(cal_id, cal_id)
            for event in events:
                summary = event.get("summary", "(no title)")
                start = event.get("start", {})
                end = event.get("end", {})
                start_str = start.get("dateTime", start.get("date", "?"))[:16].replace("T", " ")
                end_str = end.get("dateTime", end.get("date", "?"))[11:16] if "dateTime" in end else ""
                time_range = f"{start_str}-{end_str}" if end_str else start_str

                # Classify as overlapping or nearby
                event_start_raw = start.get("dateTime")
                event_end_raw = end.get("dateTime")
                if event_start_raw and event_end_raw:
                    event_start_dt = datetime.fromisoformat(event_start_raw)
                    event_end_dt = datetime.fromisoformat(event_end_raw)
                    if event_start_dt < invite_end and event_end_dt > dtstart:
                        overlapping.append((cal_name, summary, time_range))
                        continue

                nearby.append((cal_name, summary, time_range))

        return overlapping, nearby

    @staticmethod
    def _display_invite(
        invite: ParsedInvite,
        index: int,
        total: int,
        already_in_calendar: bool,
        conflicts: tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]] | None = None,
    ) -> None:
        """Display invite details to the user."""
        line = "\u2501" * 50
        _safe_print(line)
        _safe_print(f"  Invite {index}/{total}")
        _safe_print(f"  Subject:   {invite.summary or invite.subject}")

        if invite.dtstart:
            start_str = invite.dtstart.strftime("%a %d.%m.%Y %H:%M")
            if invite.dtend:
                end_str = invite.dtend.strftime("%H:%M")
                _safe_print(f"  When:      {start_str} - {end_str}")
            else:
                _safe_print(f"  When:      {start_str}")
        else:
            _safe_print("  When:      (unknown)")

        _safe_print(f"  Organizer: {invite.organizer or '(unknown)'}")
        _safe_print(f"  Location:  {invite.location or '(none)'}")

        if conflicts and (conflicts[0] or conflicts[1]):
            overlapping, nearby = conflicts
            if overlapping:
                label = "Overlapping"
                _safe_print(f"  {label}: {len(overlapping)} event(s)")
                padding = " " * (len(label) + 2)
                for cal_name, summary, time_range in overlapping:
                    _safe_print(f"  {padding}{time_range}  {summary} ({cal_name})")
            if nearby:
                label = "Nearby"
                _safe_print(f"  {label}:      {len(nearby)} event(s)")
                for cal_name, summary, time_range in nearby:
                    _safe_print(f"               {time_range}  {summary} ({cal_name})")

        if invite.is_cancellation:
            _safe_print("  Status:    CANCELLED")
        elif already_in_calendar:
            _safe_print("  Status:    Already in Google Calendar")
        else:
            _safe_print("  Status:    Not in Google Calendar")

        _safe_print(line)

    @staticmethod
    def _prompt_user(already_in_calendar: bool) -> str:
        """Prompt user for action on an invite. Returns 'yes', 'no', or 'skip'."""
        if already_in_calendar:
            _safe_print("\n  [n]o - archive  |  [s]kip")
        else:
            _safe_print("\n  [y]es - add to calendar  |  [n]o - archive  |  [s]kip")

        while True:
            choice = input("  > ").strip().lower()
            if choice in ("y", "yes") and not already_in_calendar:
                return "yes"
            if choice in ("n", "no"):
                return "no"
            if choice in ("s", "skip", ""):
                return "skip"
            _safe_print("  Invalid choice. Try again.")

    @staticmethod
    def _prompt_cancellation(already_in_calendar: bool) -> str:
        """Prompt user for action on a cancelled invite. Returns 'delete', 'archive', or 'skip'."""
        if already_in_calendar:
            _safe_print("\n  [d]elete from calendar & archive  |  [n]o - archive only  |  [s]kip")
        else:
            _safe_print("\n  [n]o - archive  |  [s]kip")

        while True:
            choice = input("  > ").strip().lower()
            if choice in ("d", "delete") and already_in_calendar:
                return "delete"
            if choice in ("n", "no"):
                return "archive"
            if choice in ("s", "skip", ""):
                return "skip"
            _safe_print("  Invalid choice. Try again.")

    @staticmethod
    def _prompt_rsvp(invite: ParsedInvite) -> bool:
        """Ask user if they want to send an RSVP acceptance."""
        if not invite.organizer_email:
            return False

        _safe_print(f"\n  Send RSVP acceptance to {invite.organizer_email}?")
        _safe_print("  [y]es  |  [n]o")
        choice = input("  > ").strip().lower()
        return choice in ("y", "yes")

    @staticmethod
    def _add_to_calendar(gcal_client: GoogleCalendarClient, invite: ParsedInvite) -> bool:
        """Add the invite to Google Calendar."""
        event_id = gcal_client.add_event_from_ics(invite.ics_data)
        return event_id is not None

    @staticmethod
    def _handle_rsvp(
        client: EnhancedImapClient,
        config: ConfigManager,
        account_config: dict,
        invite: ParsedInvite,
    ) -> None:
        """Create an RSVP acceptance as a draft or send it directly via SMTP."""
        if config.meetings_rsvp_send_directly:
            success = InviteProcessor._send_rsvp_email(config, account_config, invite)
            if success:
                _safe_print(f"  RSVP sent to {invite.organizer_email}.")
            else:
                _safe_print("  Failed to send RSVP.")
        else:
            success = InviteProcessor._create_rsvp_draft(client, config, account_config, invite)
            if success:
                _safe_print("  RSVP draft created in Drafts folder.")
            else:
                _safe_print("  Failed to create RSVP draft.")

    @staticmethod
    def _build_rsvp_ics(invite: ParsedInvite, user_email: str) -> str:
        """Build a METHOD:REPLY ICS string with PARTSTAT=ACCEPTED."""
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//IMAP AI Assistant//EN",
            "METHOD:REPLY",
            "BEGIN:VEVENT",
        ]

        if invite.uid:
            lines.append(f"UID:{invite.uid}")
        if invite.dtstart:
            lines.append(f"DTSTART:{invite.dtstart.strftime('%Y%m%dT%H%M%SZ')}")
        if invite.dtend:
            lines.append(f"DTEND:{invite.dtend.strftime('%Y%m%dT%H%M%SZ')}")
        if invite.summary:
            lines.append(f"SUMMARY:{invite.summary}")
        if invite.organizer_email:
            lines.append(f"ORGANIZER:mailto:{invite.organizer_email}")

        now_utc = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        lines.append(f"DTSTAMP:{now_utc}")
        lines.append("SEQUENCE:0")

        lines.append(
            f"ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT"
            f";PARTSTAT=ACCEPTED;CN={user_email}:mailto:{user_email}"
        )
        lines.append("END:VEVENT")
        lines.append("END:VCALENDAR")

        return "\r\n".join(lines)

    @staticmethod
    def _build_rsvp_message(invite: ParsedInvite, user_email: str) -> MIMEMultipart:
        """Build an iTIP REPLY MIME message for an RSVP acceptance."""
        reply_ics = InviteProcessor._build_rsvp_ics(invite, user_email)
        subject = f"Accepted: {invite.summary or invite.subject}"
        body_html = (
            '<div style="font-family: Arial, sans-serif; font-size: 14px;">'
            f"<p>Accepted: {invite.summary or invite.subject}</p>"
            "</div>"
        )

        msg = MIMEMultipart("mixed")
        msg["From"] = user_email
        msg["To"] = invite.organizer_email
        msg["Subject"] = subject
        msg["X-IMAP-Assistant-Invite-RSVP"] = "ACCEPTED"

        html_part = MIMEText(body_html, "html")
        msg.attach(html_part)

        cal_part = MIMENonMultipart("text", "calendar", charset="utf-8", method="REPLY")
        cal_part.set_payload(reply_ics.encode("utf-8"))
        cal_part["Content-Transfer-Encoding"] = "8bit"
        cal_part.add_header("Content-Disposition", "inline", filename="invite.ics")
        msg.attach(cal_part)

        return msg

    @staticmethod
    def _create_rsvp_draft(
        client: EnhancedImapClient,
        config: ConfigManager,
        account_config: dict,
        invite: ParsedInvite,
    ) -> bool:
        """Save an iTIP RSVP acceptance as a draft in the Drafts folder."""
        if not invite.organizer_email:
            logger.warning("No organizer email found, cannot create RSVP draft")
            return False

        user_email = account_config.get("email_address", "")
        drafts_folder = config.get_drafts_folder(account_config)

        try:
            msg = InviteProcessor._build_rsvp_message(invite, user_email)
            client.client.client.append(
                drafts_folder,
                msg.as_bytes(),
                [b"\\Draft"],
            )
            logger.info("RSVP draft created for %s", invite.organizer_email)
            return True
        except Exception as e:
            logger.error("Failed to create RSVP draft: %s", e)
            return False

    @staticmethod
    def _send_rsvp_email(
        config: ConfigManager,
        account_config: dict,
        invite: ParsedInvite,
    ) -> bool:
        """Send an iTIP RSVP acceptance directly via SMTP."""
        if not invite.organizer_email:
            logger.warning("No organizer email found, cannot send RSVP")
            return False

        smtp_cfg = config.get_account_smtp_config(account_config)
        if not smtp_cfg:
            logger.error("No SMTP configuration available for RSVP send")
            return False

        user_email = account_config.get("email_address", "")

        try:
            msg = InviteProcessor._build_rsvp_message(invite, user_email)

            server = smtplib.SMTP(smtp_cfg["server"], smtp_cfg.get("port", 587))
            if smtp_cfg.get("use_tls", True):
                server.starttls()
            server.login(smtp_cfg["username"], smtp_cfg["password"])
            server.sendmail(user_email, invite.organizer_email, msg.as_string())
            server.quit()

            logger.info("RSVP sent directly to %s", invite.organizer_email)
            return True
        except Exception as e:
            logger.error("Failed to send RSVP: %s", e)
            return False

    @staticmethod
    def _move_to_meetings(client: EnhancedImapClient, config: ConfigManager, message_id: object, folder: str) -> bool:
        """Move an accepted invite email to the meetings folder."""
        meetings_folder = config.meetings_folder
        try:
            client.client.client.select_folder(folder)
            return bool(client.client.move_to_folder(message_id, meetings_folder))
        except Exception as e:
            logger.error("Failed to move invite to meetings folder: %s", e)
            return False

    @staticmethod
    def _archive_invite(client: EnhancedImapClient, config: ConfigManager, message_id: object, folder: str) -> bool:
        """Move an invite email to the archive folder."""
        archive_folder = config.meetings_archive_folder
        try:
            client.client.client.select_folder(folder)
            return bool(client.client.move_to_folder(message_id, archive_folder))
        except Exception as e:
            logger.error("Failed to archive invite: %s", e)
            return False
