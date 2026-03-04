"""Interactive processor for meeting invite emails with Google Calendar integration."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.calendar.google_calendar_client import GoogleCalendarClient

from src.config.settings import ConfigManager
from src.constants import (
    ACTION_ADD_CALENDAR,
    ACTION_ARCHIVE_INVITE,
    ACTION_DELETE_CALENDAR,
    ACTION_MOVE_MEETINGS,
    FOLDER_INBOX,
)
from src.email.imap_client import EnhancedImapClient
from src.interaction.scheduler_prompts import SchedulerChoice, scheduler_choose, scheduler_confirm, send_output
from src.processors.action_result import ActionResult
from src.processors.invite_rsvp import InviteRsvp
from src.processors.meeting_cleanup import MeetingCleanup

logger = logging.getLogger(__name__)


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
    """Processes meeting invite emails with Google Calendar integration.

    Provides a public API for callers (e.g. inbox-zero) and a standalone
    ``process_invites`` workflow for the ``--process-invites`` CLI command.
    """

    def __init__(
        self,
        client: EnhancedImapClient,
        config: ConfigManager,
        gcal_client: GoogleCalendarClient | None = None,
        account_config: dict | None = None,
    ) -> None:
        self._client = client
        self._config = config
        self._gcal_client = gcal_client
        self._account_config = account_config

    # ------------------------------------------------------------------
    # Public API — used by inbox-zero and other callers
    # ------------------------------------------------------------------

    def detect_invite(self, msg_id: object, email_msg: object) -> ParsedInvite | None:
        """Check whether *email_msg* contains ICS data and return a parsed invite."""
        ics_data = MeetingCleanup._get_ics_data(email_msg)
        if ics_data is None:
            return None

        details = self._parse_invite_details(ics_data)
        subject = getattr(email_msg, "subject", "(no subject)") or "(no subject)"

        return ParsedInvite(
            message_id=msg_id,
            email_message=email_msg,
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
        )

    def display_invite(self, invite: ParsedInvite, index: int, total: int) -> None:
        """Display invite details including calendar status and conflicts."""
        already_exists = self._check_exists(invite)

        conflicts = None
        if invite.dtstart and not invite.is_cancellation and self._gcal_client is not None:
            conflicts = self._find_conflicts(invite.dtstart, invite.dtend)

        self._display_invite(invite, index, total, already_exists, conflicts)

    def get_invite_options(self, invite: ParsedInvite) -> list[tuple[str, str]]:
        """Return invite-specific action choices based on state and calendar availability."""
        already_exists = self._check_exists(invite)
        has_calendar = self._gcal_client is not None

        if invite.is_cancellation:
            return self._cancellation_options(already_exists, has_calendar=has_calendar)
        return self._regular_options(already_exists, has_calendar=has_calendar)

    def execute_invite_action(
        self,
        action: str,
        invite: ParsedInvite,
        *,
        dry_run: bool = False,
        source_folder: str = FOLDER_INBOX,
    ) -> ActionResult:
        """Execute an invite-specific action and return the result."""
        if action == ACTION_ADD_CALENDAR:
            return self._act_add_to_calendar(invite, source_folder, dry_run=dry_run)

        if action == ACTION_MOVE_MEETINGS:
            return self._act_move_to_meetings(invite, source_folder, dry_run=dry_run)

        if action == ACTION_ARCHIVE_INVITE:
            return self._act_archive(invite, source_folder, dry_run=dry_run)

        if action == ACTION_DELETE_CALENDAR:
            return self._act_delete_from_calendar(invite, source_folder, dry_run=dry_run)

        return ActionResult(success=False, action_type="skipped")

    def ensure_calendar_selected(self) -> None:
        """Make sure a calendar is selected (prompts interactively if needed)."""
        if self._gcal_client is not None:
            self._select_calendar()

    # ------------------------------------------------------------------
    # Standalone workflow — used by --process-invites
    # ------------------------------------------------------------------

    def process_invites(self) -> None:
        """Scan for invites and let the user accept, decline, or skip each one."""
        if self._gcal_client is None:
            logger.error("Google Calendar client required for process_invites")
            return

        folder = self._config.meetings_invite_scan_folder
        self._select_calendar()

        send_output(f"\nScanning '{folder}' for meeting invites...")

        invites = self._scan_for_invites(folder)
        if not invites:
            send_output("No meeting invites found.")
            return

        send_output(f"Found {len(invites)} invite(s).\n")

        added = 0
        deleted = 0
        archived = 0
        skipped = 0

        for i, invite in enumerate(invites, 1):
            already_exists = self._check_exists(invite)

            conflicts = None
            if invite.dtstart and not invite.is_cancellation:
                conflicts = self._find_conflicts(invite.dtstart, invite.dtend)

            self._display_invite(invite, i, len(invites), already_exists, conflicts)

            if invite.is_cancellation:
                action = self._prompt_cancellation(already_exists, invite)

                if action == "delete":
                    result = self._act_delete_from_calendar(invite, folder)
                    if result.success:
                        deleted += 1

                elif action == "archive":
                    result = self._act_archive(invite, folder)
                    if result.success:
                        archived += 1
                    else:
                        skipped += 1

                else:
                    skipped += 1

                send_output("")
                continue

            action = self._prompt_user(already_exists, invite)

            if action == "move":
                result = self._act_move_to_meetings(invite, folder)
                if result.success:
                    added += 1

            elif action == "yes":
                result = self._act_add_to_calendar(invite, folder)
                if result.success:
                    added += 1
                else:
                    skipped += 1
                    continue

            elif action == "no":
                result = self._act_archive(invite, folder)
                if result.success:
                    archived += 1
                else:
                    skipped += 1

            else:
                skipped += 1

            send_output("")

        send_output(
            f"\nSummary: {len(invites)} invite(s) processed | "
            f"{added} added | {deleted} deleted | {archived} archived | {skipped} skipped"
        )

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    def _act_add_to_calendar(
        self, invite: ParsedInvite, source_folder: str, *, dry_run: bool = False,
    ) -> ActionResult:
        """Add invite to calendar, optionally RSVP, then move to meetings."""
        if self._gcal_client is None:
            send_output("  Google Calendar not available.")
            return ActionResult(success=False, action_type="skipped")

        if dry_run:
            send_output("  DRY RUN: would add to Google Calendar")
            return ActionResult(success=True, action_type="calendar_added")

        event_id = self._gcal_client.add_event_from_ics(invite.ics_data)
        if event_id is None:
            send_output("  Failed to add to Google Calendar.")
            return ActionResult(success=False, action_type="skipped")

        send_output("  Added to Google Calendar.")

        if self._account_config is not None and self._prompt_rsvp(invite):
            InviteRsvp.handle_rsvp(
                self._client, self._config, self._account_config, invite,
            )

        self._move_to_meetings(invite.message_id, source_folder)
        send_output("  Moved to meetings folder.")

        return ActionResult(success=True, action_type="calendar_added")

    def _act_move_to_meetings(
        self, invite: ParsedInvite, source_folder: str, *, dry_run: bool = False,
    ) -> ActionResult:
        """Move an invite email to the meetings folder."""
        if dry_run:
            send_output(f"  DRY RUN: would move to '{self._config.meetings_folder}'")
            return ActionResult(success=True, action_type="moved")

        success = self._move_to_meetings(invite.message_id, source_folder)
        if success:
            send_output("  Moved to meetings folder.")
            return ActionResult(success=True, action_type="moved")
        send_output("  Failed to move to meetings folder.")
        return ActionResult(success=False, action_type="skipped")

    def _act_archive(
        self, invite: ParsedInvite, source_folder: str, *, dry_run: bool = False,
    ) -> ActionResult:
        """Archive an invite email."""
        if dry_run:
            send_output(f"  DRY RUN: would archive to '{self._config.meetings_archive_folder}'")
            return ActionResult(success=True, action_type="archived")

        success = self._archive_invite(invite.message_id, source_folder)
        if success:
            send_output("  Moved to archive folder.")
            return ActionResult(success=True, action_type="archived")
        send_output("  Failed to archive.")
        return ActionResult(success=False, action_type="skipped")

    def _act_delete_from_calendar(
        self, invite: ParsedInvite, source_folder: str, *, dry_run: bool = False,
    ) -> ActionResult:
        """Delete a cancelled event from calendar and archive the email."""
        if self._gcal_client is not None and not dry_run:
            success = self._gcal_client.delete_event(
                uid=invite.uid,
                summary=invite.summary or invite.subject,
                start_time=invite.dtstart,
            )
            if success:
                send_output("  Deleted from Google Calendar.")
            else:
                send_output("  Failed to delete from Google Calendar.")
        elif dry_run:
            send_output("  DRY RUN: would delete from Google Calendar")

        if dry_run:
            send_output(f"  DRY RUN: would archive to '{self._config.meetings_archive_folder}'")
        else:
            self._archive_invite(invite.message_id, source_folder)
            send_output("  Moved to archive folder.")

        return ActionResult(success=True, action_type="calendar_deleted")

    # ------------------------------------------------------------------
    # Options builders
    # ------------------------------------------------------------------

    @staticmethod
    def _regular_options(
        already_exists: bool, *, has_calendar: bool,
    ) -> list[tuple[str, str]]:
        """Build action choices for a regular (non-cancellation) invite."""
        choices: list[tuple[str, str]] = []
        if has_calendar:
            if already_exists:
                choices.append(("Move to meetings", ACTION_MOVE_MEETINGS))
            else:
                choices.append(("Add to calendar", ACTION_ADD_CALENDAR))
        choices.append(("Archive", ACTION_ARCHIVE_INVITE))
        return choices

    @staticmethod
    def _cancellation_options(
        already_exists: bool, *, has_calendar: bool,
    ) -> list[tuple[str, str]]:
        """Build action choices for a cancelled invite."""
        choices: list[tuple[str, str]] = []
        if has_calendar and already_exists:
            choices.append(("Delete from calendar & archive", ACTION_DELETE_CALENDAR))
        choices.append(("Archive", ACTION_ARCHIVE_INVITE))
        return choices

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_exists(self, invite: ParsedInvite) -> bool:
        """Check whether the invite event already exists in Google Calendar."""
        if self._gcal_client is None:
            return False
        return self._gcal_client.event_exists(
            uid=invite.uid,
            summary=invite.summary or invite.subject,
            start_time=invite.dtstart,
        )

    def _select_calendar(self) -> None:
        """Use the stored calendar or let the user pick one interactively."""
        if self._gcal_client is None:
            return
        if self._gcal_client.calendar_id != "primary":
            send_output(f"\nUsing calendar: {self._gcal_client.calendar_id}")
            return

        calendars = self._gcal_client.list_calendars()
        if not calendars:
            send_output("Could not retrieve calendars. Using current setting.")
            return

        options = [
            f"{cal.get('summary', '(unnamed)')}{' (primary)' if cal.get('primary') else ''} — {cal.get('id', '')}"
            for cal in calendars
        ]
        choice_index = scheduler_choose("No calendar configured yet. Please pick one:", options, default=0)
        selected = calendars[choice_index]
        self._gcal_client.calendar_id = selected["id"]
        self._config.save_setting(
            ["meetings", "google_calendar", "accepts_meetings_calendar"],
            {"name": selected.get("summary", ""), "id": selected["id"]},
        )
        send_output(f"  Saved: {selected.get('summary', '')} ({selected['id']})")

    def _scan_for_invites(self, folder: str) -> list[ParsedInvite]:
        """Scan a folder for emails containing calendar invites."""
        messages = self._client.client.get_all_messages(folder=folder)
        if not messages:
            return []

        invites: list[ParsedInvite] = []
        for message_id, email_message in messages:
            invite = self.detect_invite(message_id, email_message)
            if invite is not None:
                invites.append(invite)

        return invites

    def _find_conflicts(
        self,
        dtstart: datetime,
        dtend: datetime | None,
    ) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
        """Find events near the invite time, split into overlapping and nearby."""
        if self._gcal_client is None:
            return [], []

        buffer = timedelta(minutes=30)
        invite_end = dtend or dtstart
        query_start = dtstart - buffer
        query_end = invite_end + buffer

        calendar_ids = [self._gcal_client.calendar_id, *self._config.free_check_calendar_ids]

        cal_names: dict[str, str] = {}
        for cal in self._gcal_client.list_calendars():
            cal_names[cal.get("id", "")] = cal.get("summary", cal.get("id", ""))

        overlapping: list[tuple[str, str, str]] = []
        nearby: list[tuple[str, str, str]] = []
        for cal_id in calendar_ids:
            events = self._gcal_client.list_events_in_range(cal_id, query_start, query_end)
            cal_name = cal_names.get(cal_id, cal_id)
            for event in events:
                summary = event.get("summary", "(no title)")
                start = event.get("start", {})
                end = event.get("end", {})
                start_str = start.get("dateTime", start.get("date", "?"))[:16].replace("T", " ")
                end_str = end.get("dateTime", end.get("date", "?"))[11:16] if "dateTime" in end else ""
                time_range = f"{start_str}-{end_str}" if end_str else start_str

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
        send_output(line)
        send_output(f"  Invite {index}/{total}")
        send_output(f"  Subject:   {invite.summary or invite.subject}")

        if invite.dtstart:
            start_str = invite.dtstart.strftime("%a %d.%m.%Y %H:%M")
            if invite.dtend:
                end_str = invite.dtend.strftime("%H:%M")
                send_output(f"  When:      {start_str} - {end_str}")
            else:
                send_output(f"  When:      {start_str}")
        else:
            send_output("  When:      (unknown)")

        send_output(f"  Organizer: {invite.organizer or '(unknown)'}")
        send_output(f"  Location:  {invite.location or '(none)'}")

        if conflicts and (conflicts[0] or conflicts[1]):
            overlapping, nearby = conflicts
            if overlapping:
                label = "Overlapping"
                send_output(f"  {label}: {len(overlapping)} event(s)")
                padding = " " * (len(label) + 2)
                for cal_name, summary, time_range in overlapping:
                    send_output(f"  {padding}{time_range}  {summary} ({cal_name})")
            if nearby:
                label = "Nearby"
                send_output(f"  {label}:      {len(nearby)} event(s)")
                for cal_name, summary, time_range in nearby:
                    send_output(f"               {time_range}  {summary} ({cal_name})")

        if invite.is_cancellation:
            send_output("  Status:    CANCELLED")
        elif already_in_calendar:
            send_output("  Status:    Already in Google Calendar")
        else:
            send_output("  Status:    Not in Google Calendar")

        send_output(line)

    @staticmethod
    def _format_invite_header(invite: ParsedInvite) -> str:
        """Build a summary string with title and date/time for prompt messages."""
        title = invite.summary or invite.subject
        if invite.dtstart:
            when = invite.dtstart.strftime("%a %d.%m.%Y %H:%M")
            if invite.dtend:
                when += f" - {invite.dtend.strftime('%H:%M')}"
            return f"{title} ({when})"
        return title

    @staticmethod
    def _prompt_user(already_in_calendar: bool, invite: ParsedInvite) -> str:
        """Prompt user for action on an invite (standalone workflow)."""
        header = InviteProcessor._format_invite_header(invite)
        if already_in_calendar:
            choices = [("Move to meetings", "move"), ("Archive", "no"), ("Skip", "skip")]
        else:
            choices = [("Add to calendar", "yes"), ("Archive", "no"), ("Skip", "skip")]
        return SchedulerChoice(f"{header}\nAction:", choices).choose()

    @staticmethod
    def _prompt_cancellation(already_in_calendar: bool, invite: ParsedInvite) -> str:
        """Prompt user for action on a cancelled invite (standalone workflow)."""
        header = InviteProcessor._format_invite_header(invite)
        if already_in_calendar:
            choices = [
                ("Delete from calendar & archive", "delete"),
                ("Archive only", "archive"),
                ("Skip", "skip"),
            ]
        else:
            choices = [("Archive", "archive"), ("Skip", "skip")]
        return SchedulerChoice(f"CANCELLED: {header}\nAction:", choices).choose()

    @staticmethod
    def _prompt_rsvp(invite: ParsedInvite) -> bool:
        """Ask user if they want to send an RSVP acceptance."""
        if not invite.organizer_email:
            return False
        return scheduler_confirm(
            f"Send RSVP acceptance to {invite.organizer_email}?", default=True,
        )

    def _move_to_meetings(self, message_id: object, folder: str) -> bool:
        """Move an accepted invite email to the meetings folder."""
        meetings_folder = self._config.meetings_folder
        try:
            self._client.client.client.select_folder(folder)
            return bool(self._client.client.move_to_folder(message_id, meetings_folder))
        except Exception as e:
            logger.error("Failed to move invite to meetings folder: %s", e)
            return False

    def _archive_invite(self, message_id: object, folder: str) -> bool:
        """Move an invite email to the archive folder."""
        archive_folder = self._config.meetings_archive_folder
        try:
            self._client.client.client.select_folder(folder)
            return bool(self._client.client.move_to_folder(message_id, archive_folder))
        except Exception as e:
            logger.error("Failed to archive invite: %s", e)
            return False

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
