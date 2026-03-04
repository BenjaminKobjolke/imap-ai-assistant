"""Tests for the InviteProcessor public API (detect, options, execute)."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from src.calendar.google_calendar_client import GoogleCalendarClient
from src.config.settings import ConfigManager
from src.constants import (
    ACTION_ADD_CALENDAR,
    ACTION_ARCHIVE_INVITE,
    ACTION_DELETE_CALENDAR,
    ACTION_MOVE_MEETINGS,
)
from src.email.imap_client import EnhancedImapClient
from src.processors.action_result import ActionResult
from src.processors.invite_processor import InviteProcessor, ParsedInvite


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_email(subject: str = "Meeting invite") -> MagicMock:
    """Create a minimal mock email message."""
    msg = MagicMock()
    msg.subject = subject
    msg.from_address = "organizer@example.com"
    msg.get_body = MagicMock(return_value="Meeting body text")
    return msg


def _make_invite(
    *,
    method: str | None = None,
    uid: str | None = "abc-123",
    summary: str | None = "Team standup",
    dtstart: datetime | None = None,
    dtend: datetime | None = None,
) -> ParsedInvite:
    """Build a ParsedInvite with sensible defaults."""
    return ParsedInvite(
        message_id=42,
        email_message=_make_email(),
        subject="Meeting invite",
        ics_data=b"BEGIN:VCALENDAR\nEND:VCALENDAR",
        uid=uid,
        summary=summary,
        dtstart=dtstart or datetime(2026, 3, 10, 14, 0),
        dtend=dtend or datetime(2026, 3, 10, 15, 0),
        organizer="Alice",
        organizer_email="alice@example.com",
        location="Room 42",
        method=method,
    )


def _processor(
    *,
    gcal: MagicMock | None = "default",
    account_config: dict | None = None,
) -> InviteProcessor:
    """Create an InviteProcessor with mocked dependencies."""
    client = MagicMock(spec=EnhancedImapClient)
    config = MagicMock(spec=ConfigManager)
    config.meetings_folder = "Meetings"
    config.meetings_archive_folder = "Meetings/Archive"

    if gcal == "default":
        gcal = MagicMock(spec=GoogleCalendarClient)
        gcal.event_exists = MagicMock(return_value=False)
        gcal.calendar_id = "cal-id-1"

    return InviteProcessor(client, config, gcal_client=gcal, account_config=account_config)


# ===================================================================
# detect_invite
# ===================================================================

class TestDetectInvite:
    """Tests for InviteProcessor.detect_invite."""

    @patch("src.processors.invite_processor.MeetingCleanup._get_ics_data")
    def test_returns_none_when_no_ics(self, mock_get_ics: MagicMock) -> None:
        """When the email has no ICS data, detect_invite returns None."""
        mock_get_ics.return_value = None
        proc = _processor()
        email_msg = _make_email()

        result = proc.detect_invite(1, email_msg)

        assert result is None
        mock_get_ics.assert_called_once_with(email_msg)

    @patch("src.processors.invite_processor.MeetingCleanup._get_ics_data")
    def test_returns_parsed_invite_when_ics_found(self, mock_get_ics: MagicMock) -> None:
        """When ICS data exists, detect_invite returns a ParsedInvite."""
        ics_bytes = (
            b"BEGIN:VCALENDAR\r\nMETHOD:REQUEST\r\n"
            b"BEGIN:VEVENT\r\nUID:test-uid\r\nSUMMARY:Sprint Review\r\n"
            b"DTSTART:20260310T140000Z\r\nDTEND:20260310T150000Z\r\n"
            b"ORGANIZER;CN=Alice:mailto:alice@example.com\r\n"
            b"LOCATION:Room 5\r\n"
            b"END:VEVENT\r\nEND:VCALENDAR"
        )
        mock_get_ics.return_value = ics_bytes
        proc = _processor()
        email_msg = _make_email(subject="Sprint Review")

        result = proc.detect_invite(99, email_msg)

        assert result is not None
        assert isinstance(result, ParsedInvite)
        assert result.message_id == 99
        assert result.email_message is email_msg
        assert result.subject == "Sprint Review"
        assert result.ics_data == ics_bytes
        assert result.uid == "test-uid"
        assert result.summary == "Sprint Review"
        assert result.method == "REQUEST"

    @patch("src.processors.invite_processor.MeetingCleanup._get_ics_data")
    def test_subject_defaults_to_no_subject(self, mock_get_ics: MagicMock) -> None:
        """When email has no subject, detect_invite uses '(no subject)'."""
        mock_get_ics.return_value = b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nEND:VEVENT\r\nEND:VCALENDAR"
        proc = _processor()
        email_msg = _make_email()
        email_msg.subject = None

        result = proc.detect_invite(1, email_msg)

        assert result is not None
        assert result.subject == "(no subject)"


# ===================================================================
# get_invite_options
# ===================================================================

class TestGetInviteOptions:
    """Tests for InviteProcessor.get_invite_options."""

    def test_regular_invite_with_calendar(self) -> None:
        """Regular invite with gcal shows add + archive."""
        proc = _processor()
        invite = _make_invite()

        options = proc.get_invite_options(invite)

        assert options == [
            ("Add to calendar", ACTION_ADD_CALENDAR),
            ("Archive", ACTION_ARCHIVE_INVITE),
        ]

    def test_regular_invite_already_in_calendar(self) -> None:
        """Regular invite already in calendar shows move + archive."""
        proc = _processor()
        proc._gcal_client.event_exists.return_value = True
        invite = _make_invite()

        options = proc.get_invite_options(invite)

        assert options == [
            ("Move to meetings", ACTION_MOVE_MEETINGS),
            ("Archive", ACTION_ARCHIVE_INVITE),
        ]

    def test_regular_invite_without_calendar(self) -> None:
        """Regular invite without gcal shows only archive."""
        proc = _processor(gcal=None)
        invite = _make_invite()

        options = proc.get_invite_options(invite)

        assert options == [("Archive", ACTION_ARCHIVE_INVITE)]

    def test_cancellation_with_calendar_and_exists(self) -> None:
        """Cancellation in calendar shows delete + archive."""
        proc = _processor()
        proc._gcal_client.event_exists.return_value = True
        invite = _make_invite(method="CANCEL")

        options = proc.get_invite_options(invite)

        assert options == [
            ("Delete from calendar & archive", ACTION_DELETE_CALENDAR),
            ("Archive", ACTION_ARCHIVE_INVITE),
        ]

    def test_cancellation_with_calendar_not_exists(self) -> None:
        """Cancellation not in calendar shows only archive."""
        proc = _processor()
        proc._gcal_client.event_exists.return_value = False
        invite = _make_invite(method="CANCEL")

        options = proc.get_invite_options(invite)

        assert options == [("Archive", ACTION_ARCHIVE_INVITE)]

    def test_cancellation_without_calendar(self) -> None:
        """Cancellation without gcal shows only archive."""
        proc = _processor(gcal=None)
        invite = _make_invite(method="CANCEL")

        options = proc.get_invite_options(invite)

        assert options == [("Archive", ACTION_ARCHIVE_INVITE)]


# ===================================================================
# execute_invite_action
# ===================================================================

class TestExecuteAddCalendar:
    """Tests for the add_calendar action."""

    @patch("src.processors.invite_processor.send_output")
    def test_add_calendar_dry_run(self, _out: MagicMock) -> None:
        """Dry-run add_calendar returns success without calling gcal."""
        proc = _processor()
        invite = _make_invite()

        result = proc.execute_invite_action(ACTION_ADD_CALENDAR, invite, dry_run=True)

        assert result == ActionResult(success=True, action_type="calendar_added")
        proc._gcal_client.add_event_from_ics.assert_not_called()

    @patch("src.processors.invite_processor.InviteRsvp.handle_rsvp")
    @patch("src.processors.invite_processor.send_output")
    def test_add_calendar_success(self, _out: MagicMock, _rsvp: MagicMock) -> None:
        """Successful add_calendar adds event and moves to meetings."""
        proc = _processor(account_config={"name": "test"})
        proc._gcal_client.add_event_from_ics.return_value = "event-id-1"
        invite = _make_invite()

        with patch.object(proc, "_prompt_rsvp", return_value=False):
            result = proc.execute_invite_action(ACTION_ADD_CALENDAR, invite, source_folder="INBOX")

        assert result == ActionResult(success=True, action_type="calendar_added")
        proc._gcal_client.add_event_from_ics.assert_called_once_with(invite.ics_data)

    @patch("src.processors.invite_processor.send_output")
    def test_add_calendar_gcal_fails(self, _out: MagicMock) -> None:
        """When gcal returns None, add_calendar fails gracefully."""
        proc = _processor()
        proc._gcal_client.add_event_from_ics.return_value = None
        invite = _make_invite()

        result = proc.execute_invite_action(ACTION_ADD_CALENDAR, invite)

        assert result == ActionResult(success=False, action_type="skipped")

    @patch("src.processors.invite_processor.send_output")
    def test_add_calendar_no_gcal_client(self, _out: MagicMock) -> None:
        """Without gcal client, add_calendar fails."""
        proc = _processor(gcal=None)
        invite = _make_invite()

        result = proc.execute_invite_action(ACTION_ADD_CALENDAR, invite)

        assert result == ActionResult(success=False, action_type="skipped")

    @patch("src.processors.invite_processor.InviteRsvp.handle_rsvp")
    @patch("src.processors.invite_processor.send_output")
    def test_add_calendar_triggers_rsvp(self, _out: MagicMock, mock_rsvp: MagicMock) -> None:
        """When user confirms RSVP, handle_rsvp is called."""
        proc = _processor(account_config={"name": "test"})
        proc._gcal_client.add_event_from_ics.return_value = "event-id-1"
        invite = _make_invite()

        with patch.object(proc, "_prompt_rsvp", return_value=True):
            proc.execute_invite_action(ACTION_ADD_CALENDAR, invite)

        mock_rsvp.assert_called_once()


class TestExecuteMoveMeetings:
    """Tests for the move_meetings action."""

    @patch("src.processors.invite_processor.send_output")
    def test_move_meetings_dry_run(self, _out: MagicMock) -> None:
        """Dry-run move_meetings returns success without moving."""
        proc = _processor()
        invite = _make_invite()

        result = proc.execute_invite_action(ACTION_MOVE_MEETINGS, invite, dry_run=True)

        assert result == ActionResult(success=True, action_type="moved")

    @patch("src.processors.invite_processor.send_output")
    def test_move_meetings_success(self, _out: MagicMock) -> None:
        """Successful move returns moved result."""
        proc = _processor()
        invite = _make_invite()

        with patch.object(proc, "_move_to_meetings", return_value=True):
            result = proc.execute_invite_action(ACTION_MOVE_MEETINGS, invite, source_folder="INBOX")

        assert result == ActionResult(success=True, action_type="moved")

    @patch("src.processors.invite_processor.send_output")
    def test_move_meetings_failure(self, _out: MagicMock) -> None:
        """When move fails, returns skipped result."""
        proc = _processor()
        invite = _make_invite()

        with patch.object(proc, "_move_to_meetings", return_value=False):
            result = proc.execute_invite_action(ACTION_MOVE_MEETINGS, invite)

        assert result == ActionResult(success=False, action_type="skipped")


class TestExecuteArchive:
    """Tests for the archive_invite action."""

    @patch("src.processors.invite_processor.send_output")
    def test_archive_dry_run(self, _out: MagicMock) -> None:
        """Dry-run archive returns success without archiving."""
        proc = _processor()
        invite = _make_invite()

        result = proc.execute_invite_action(ACTION_ARCHIVE_INVITE, invite, dry_run=True)

        assert result == ActionResult(success=True, action_type="archived")

    @patch("src.processors.invite_processor.send_output")
    def test_archive_success(self, _out: MagicMock) -> None:
        """Successful archive returns archived result."""
        proc = _processor()
        invite = _make_invite()

        with patch.object(proc, "_archive_invite", return_value=True):
            result = proc.execute_invite_action(ACTION_ARCHIVE_INVITE, invite)

        assert result == ActionResult(success=True, action_type="archived")

    @patch("src.processors.invite_processor.send_output")
    def test_archive_failure(self, _out: MagicMock) -> None:
        """When archive fails, returns skipped result."""
        proc = _processor()
        invite = _make_invite()

        with patch.object(proc, "_archive_invite", return_value=False):
            result = proc.execute_invite_action(ACTION_ARCHIVE_INVITE, invite)

        assert result == ActionResult(success=False, action_type="skipped")


class TestExecuteDeleteCalendar:
    """Tests for the delete_calendar action."""

    @patch("src.processors.invite_processor.send_output")
    def test_delete_calendar_dry_run(self, _out: MagicMock) -> None:
        """Dry-run delete_calendar returns success without calling gcal."""
        proc = _processor()
        invite = _make_invite(method="CANCEL")

        result = proc.execute_invite_action(ACTION_DELETE_CALENDAR, invite, dry_run=True)

        assert result == ActionResult(success=True, action_type="calendar_deleted")
        proc._gcal_client.delete_event.assert_not_called()

    @patch("src.processors.invite_processor.send_output")
    def test_delete_calendar_success(self, _out: MagicMock) -> None:
        """Successful delete removes event and archives email."""
        proc = _processor()
        proc._gcal_client.delete_event.return_value = True
        invite = _make_invite(method="CANCEL")

        with patch.object(proc, "_archive_invite", return_value=True):
            result = proc.execute_invite_action(ACTION_DELETE_CALENDAR, invite)

        assert result == ActionResult(success=True, action_type="calendar_deleted")
        proc._gcal_client.delete_event.assert_called_once_with(
            uid=invite.uid,
            summary=invite.summary or invite.subject,
            start_time=invite.dtstart,
        )

    @patch("src.processors.invite_processor.send_output")
    def test_delete_calendar_no_gcal(self, _out: MagicMock) -> None:
        """Without gcal client, delete_calendar still archives and succeeds."""
        proc = _processor(gcal=None)
        invite = _make_invite(method="CANCEL")

        with patch.object(proc, "_archive_invite", return_value=True):
            result = proc.execute_invite_action(ACTION_DELETE_CALENDAR, invite)

        assert result == ActionResult(success=True, action_type="calendar_deleted")


class TestExecuteUnknownAction:
    """Tests for unknown action values."""

    def test_unknown_action_returns_skipped(self) -> None:
        """An unrecognized action string returns a failed/skipped result."""
        proc = _processor()
        invite = _make_invite()

        result = proc.execute_invite_action("unknown_action", invite)

        assert result == ActionResult(success=False, action_type="skipped")


# ===================================================================
# ParsedInvite.is_cancellation
# ===================================================================

class TestParsedInviteCancellation:
    """Tests for the is_cancellation property."""

    def test_cancel_method(self) -> None:
        """Method CANCEL is detected as cancellation."""
        invite = _make_invite(method="CANCEL")
        assert invite.is_cancellation is True

    def test_cancel_method_lowercase(self) -> None:
        """Method cancel (lowercase) is detected as cancellation."""
        invite = _make_invite(method="cancel")
        assert invite.is_cancellation is True

    def test_request_method(self) -> None:
        """Method REQUEST is not a cancellation."""
        invite = _make_invite(method="REQUEST")
        assert invite.is_cancellation is False

    def test_none_method(self) -> None:
        """None method is not a cancellation."""
        invite = _make_invite(method=None)
        assert invite.is_cancellation is False
