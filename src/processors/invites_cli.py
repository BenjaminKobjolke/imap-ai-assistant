"""Non-interactive invite CLI operations for subprocess-based plugin usage."""

from __future__ import annotations

import logging

from src.config.settings import ConfigManager
from src.email.imap_client import EnhancedImapClient
from src.interaction.scheduler_prompts import send_output
from src.processors.invite_processor import InviteProcessor, ParsedInvite
from src.processors.invite_rsvp import InviteRsvp

logger = logging.getLogger(__name__)


class InvitesCli:
    """Non-interactive invite operations invoked via CLI flags."""

    def __init__(self, config: ConfigManager) -> None:
        self._config = config

    def _connect(self) -> EnhancedImapClient | None:
        """Connect to the main IMAP account. Returns client or None on failure."""
        account_config = self._config.get_first_account()
        if not account_config:
            send_output("Error: no main account configuration found")
            return None
        client = EnhancedImapClient(account_config)
        if not client.connect():
            send_output("Error: failed to connect to IMAP server")
            return None
        return client

    def _create_gcal_client(self) -> object | None:
        """Create a Google Calendar client, or None if unavailable."""
        from src.calendar.google_calendar_client import GoogleCalendarClient

        try:
            return GoogleCalendarClient.from_config(self._config)
        except Exception:
            return None

    def _scan_invites(
        self, client: EnhancedImapClient, gcal_client: object | None,
    ) -> list[ParsedInvite]:
        """Scan the invite folder and return parsed invites."""
        folder = self._config.meetings_invite_scan_folder
        account_config = self._config.get_first_account()
        processor = InviteProcessor(client, self._config, gcal_client, account_config)
        return processor._scan_for_invites(folder)

    def _find_by_id(
        self,
        invites: list[ParsedInvite],
        invite_id: str,
    ) -> ParsedInvite | None:
        """Find an invite by its IMAP message ID. Returns None and prints error if not found."""
        for invite in invites:
            if str(invite.message_id) == invite_id:
                return invite
        send_output(f"Error: Invite with id {invite_id} not found")
        return None

    def list_invites(self) -> None:
        """List pending meeting invites with index, subject, time, organizer, status."""
        client = self._connect()
        if not client:
            return
        try:
            gcal_client = self._create_gcal_client()
            invites = self._scan_invites(client, gcal_client)
            if not invites:
                send_output("No meeting invites found.")
                return

            processor = InviteProcessor(client, self._config, gcal_client)

            send_output(f"Found {len(invites)} invite(s):\n")
            for i, invite in enumerate(invites, 1):
                subject = invite.summary or invite.subject
                when = ""
                if invite.dtstart:
                    when = invite.dtstart.strftime("%a %d.%m.%Y %H:%M")
                    if invite.dtend:
                        when += f" - {invite.dtend.strftime('%H:%M')}"
                organizer = invite.organizer or "(unknown)"

                if invite.is_cancellation:
                    status = "CANCELLED"
                elif processor._check_exists(invite):
                    status = "In calendar"
                else:
                    status = "Not in calendar"

                send_output(f"[id:{invite.message_id}] [{i}] {subject} | {when} | {organizer} | {status}")
        finally:
            client.disconnect()

    def show_invite(self, invite_id: str) -> None:
        """Show details of a meeting invite by ID."""
        client = self._connect()
        if not client:
            return
        try:
            gcal_client = self._create_gcal_client()
            invites = self._scan_invites(client, gcal_client)
            if not invites:
                send_output("No meeting invites found.")
                return

            invite = self._find_by_id(invites, invite_id)
            if invite is None:
                return

            account_config = self._config.get_first_account()
            processor = InviteProcessor(client, self._config, gcal_client, account_config)
            already_exists = processor._check_exists(invite)

            send_output(f"Subject:   {invite.summary or invite.subject}")

            if invite.dtstart:
                start_str = invite.dtstart.strftime("%a %d.%m.%Y %H:%M")
                if invite.dtend:
                    end_str = invite.dtend.strftime("%H:%M")
                    send_output(f"When:      {start_str} - {end_str}")
                else:
                    send_output(f"When:      {start_str}")
            else:
                send_output("When:      (unknown)")

            send_output(f"Organizer: {invite.organizer or '(unknown)'}")
            send_output(f"Location:  {invite.location or '(none)'}")

            if invite.is_cancellation:
                send_output("Status:    CANCELLED")
            elif already_exists:
                send_output("Status:    In calendar")
            else:
                send_output("Status:    Not in calendar")

            if invite.dtstart and not invite.is_cancellation and gcal_client is not None:
                overlapping, nearby = processor._find_conflicts(invite.dtstart, invite.dtend)
                if overlapping:
                    send_output(f"Conflicts: {len(overlapping)} overlapping event(s)")
                    for cal_name, summary, time_range in overlapping:
                        send_output(f"           {time_range}  {summary} ({cal_name})")
                if nearby:
                    send_output(f"Nearby:    {len(nearby)} event(s)")
                    for cal_name, summary, time_range in nearby:
                        send_output(f"           {time_range}  {summary} ({cal_name})")
        finally:
            client.disconnect()

    def accept_invite(self, invite_id: str) -> None:
        """Accept invite: add to calendar, RSVP, move to meetings folder."""
        client = self._connect()
        if not client:
            return
        try:
            gcal_client = self._create_gcal_client()
            invites = self._scan_invites(client, gcal_client)
            if not invites:
                send_output("No meeting invites found.")
                return

            invite = self._find_by_id(invites, invite_id)
            if invite is None:
                return

            folder = self._config.meetings_invite_scan_folder
            account_config = self._config.get_first_account()
            processor = InviteProcessor(client, self._config, gcal_client, account_config)

            already_exists = processor._check_exists(invite)

            if already_exists:
                success = processor._move_to_meetings(invite.message_id, folder)
                if success:
                    send_output("Already in calendar. Moved to meetings folder.")
                else:
                    send_output("Already in calendar. Failed to move to meetings folder.")
                return

            if gcal_client is None:
                send_output("Error: Google Calendar not available")
                return

            event_id = gcal_client.add_event_from_ics(invite.ics_data)
            if event_id is None:
                send_output("Failed to add to Google Calendar.")
                return

            send_output("Added to Google Calendar.")

            if account_config and invite.organizer_email:
                InviteRsvp.handle_rsvp(client, self._config, account_config, invite)
                send_output("RSVP sent.")

            success = processor._move_to_meetings(invite.message_id, folder)
            if success:
                send_output("Moved to meetings folder.")
            else:
                send_output("Failed to move to meetings folder.")
        finally:
            client.disconnect()

    def archive_invite(self, invite_id: str) -> None:
        """Archive a meeting invite email."""
        client = self._connect()
        if not client:
            return
        try:
            gcal_client = self._create_gcal_client()
            invites = self._scan_invites(client, gcal_client)
            if not invites:
                send_output("No meeting invites found.")
                return

            invite = self._find_by_id(invites, invite_id)
            if invite is None:
                return

            folder = self._config.meetings_invite_scan_folder
            processor = InviteProcessor(client, self._config, gcal_client)
            success = processor._archive_invite(invite.message_id, folder)
            if success:
                send_output("Archived invite.")
            else:
                send_output("Failed to archive invite.")
        finally:
            client.disconnect()

    def delete_cancelled_invite(self, invite_id: str) -> None:
        """Delete cancelled event from calendar and archive email."""
        client = self._connect()
        if not client:
            return
        try:
            gcal_client = self._create_gcal_client()
            invites = self._scan_invites(client, gcal_client)
            if not invites:
                send_output("No meeting invites found.")
                return

            invite = self._find_by_id(invites, invite_id)
            if invite is None:
                return

            folder = self._config.meetings_invite_scan_folder

            if gcal_client is not None:
                success = gcal_client.delete_event(
                    uid=invite.uid,
                    summary=invite.summary or invite.subject,
                    start_time=invite.dtstart,
                )
                if success:
                    send_output("Deleted from Google Calendar.")
                else:
                    send_output("Failed to delete from Google Calendar.")

            processor = InviteProcessor(client, self._config, gcal_client)
            success = processor._archive_invite(invite.message_id, folder)
            if success:
                send_output("Archived invite.")
            else:
                send_output("Failed to archive invite.")
        finally:
            client.disconnect()
