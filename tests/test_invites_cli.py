"""Tests for the InvitesCli non-interactive invite operations."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from src.config.settings import ConfigManager
from src.email.imap_client import EnhancedImapClient
from src.processors.invite_processor import ParsedInvite
from src.processors.invites_cli import InvitesCli

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_invite(
    *,
    subject: str = "Team Meeting",
    summary: str | None = "Team Meeting",
    dtstart: datetime | None = None,
    dtend: datetime | None = None,
    organizer: str = "Boss",
    organizer_email: str = "boss@example.com",
    location: str = "Room 1",
    method: str | None = "REQUEST",
    uid: str = "uid-123",
    message_id: object = 1,
) -> ParsedInvite:
    """Create a minimal ParsedInvite for testing."""
    if dtstart is None:
        dtstart = datetime(2026, 3, 10, 14, 0)
    if dtend is None:
        dtend = datetime(2026, 3, 10, 15, 0)
    return ParsedInvite(
        message_id=message_id,
        email_message=MagicMock(),
        subject=subject,
        ics_data=b"BEGIN:VCALENDAR\nEND:VCALENDAR",
        uid=uid,
        summary=summary,
        dtstart=dtstart,
        dtend=dtend,
        organizer=organizer,
        organizer_email=organizer_email,
        location=location,
        method=method,
    )


def _make_cancelled_invite(**kwargs: object) -> ParsedInvite:
    """Create a cancelled invite."""
    return _make_invite(method="CANCEL", subject="Cancelled Meeting", summary="Cancelled Meeting", **kwargs)


def _make_config() -> MagicMock:
    """Create a mock ConfigManager."""
    config = MagicMock(spec=ConfigManager)
    config.get_first_account.return_value = {
        "name": "Test",
        "server": "imap.test.com",
        "username": "user@test.com",
        "password": "pass",
        "port": 993,
        "use_ssl": True,
        "email_address": "user@test.com",
    }
    config.meetings_invite_scan_folder = "INBOX"
    config.meetings_folder = "Meetings"
    config.meetings_archive_folder = "Meetings/Archive"
    return config


def _make_client() -> MagicMock:
    """Create a mock EnhancedImapClient."""
    client = MagicMock(spec=EnhancedImapClient)
    inner = MagicMock()
    client.client = inner
    client.connect.return_value = True
    inner.move_to_folder.return_value = True
    return client


# ===================================================================
# list_invites
# ===================================================================

class TestListInvites:
    """Tests for InvitesCli.list_invites."""

    @patch.object(InvitesCli, "_create_gcal_client")
    @patch.object(InvitesCli, "_connect")
    def test_empty_folder(
        self, mock_connect: MagicMock, mock_gcal: MagicMock, capsys: object,
    ) -> None:
        """Empty folder prints appropriate message."""
        client = _make_client()
        mock_connect.return_value = client
        mock_gcal.return_value = None

        with patch.object(InvitesCli, "_scan_invites", return_value=[]):
            cli = InvitesCli(_make_config())
            cli.list_invites()

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "No meeting invites found" in captured.out
        client.disconnect.assert_called_once()

    @patch.object(InvitesCli, "_create_gcal_client")
    @patch.object(InvitesCli, "_connect")
    def test_with_invites(
        self, mock_connect: MagicMock, mock_gcal: MagicMock, capsys: object,
    ) -> None:
        """Invites are listed with id, index, subject, time, status."""
        invites = [
            _make_invite(subject="Meeting A", summary="Meeting A", message_id=1),
            _make_invite(subject="Meeting B", summary="Meeting B", message_id=2),
        ]
        client = _make_client()
        mock_connect.return_value = client
        mock_gcal.return_value = None

        with (
            patch.object(InvitesCli, "_scan_invites", return_value=invites),
            patch("src.processors.invite_processor.InviteProcessor._check_exists", return_value=False),
        ):
            cli = InvitesCli(_make_config())
            cli.list_invites()

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "[id:1]" in captured.out
        assert "[1]" in captured.out
        assert "Meeting A" in captured.out
        assert "[id:2]" in captured.out
        assert "Meeting B" in captured.out
        assert "2 invite(s)" in captured.out
        assert "Not in calendar" in captured.out

    @patch.object(InvitesCli, "_create_gcal_client")
    @patch.object(InvitesCli, "_connect")
    def test_cancellation_status(
        self, mock_connect: MagicMock, mock_gcal: MagicMock, capsys: object,
    ) -> None:
        """Cancelled invites show CANCELLED status."""
        invites = [_make_cancelled_invite()]
        client = _make_client()
        mock_connect.return_value = client
        mock_gcal.return_value = None

        with patch.object(InvitesCli, "_scan_invites", return_value=invites):
            cli = InvitesCli(_make_config())
            cli.list_invites()

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "CANCELLED" in captured.out


# ===================================================================
# show_invite
# ===================================================================

class TestShowInvite:
    """Tests for InvitesCli.show_invite."""

    @patch.object(InvitesCli, "_create_gcal_client")
    @patch.object(InvitesCli, "_connect")
    def test_valid_id(
        self, mock_connect: MagicMock, mock_gcal: MagicMock, capsys: object,
    ) -> None:
        """Valid ID prints invite details and conflicts."""
        invites = [_make_invite()]
        client = _make_client()
        mock_connect.return_value = client
        mock_gcal.return_value = MagicMock()

        with (
            patch.object(InvitesCli, "_scan_invites", return_value=invites),
            patch("src.processors.invite_processor.InviteProcessor._check_exists", return_value=False),
            patch(
                "src.processors.invite_processor.InviteProcessor._find_conflicts",
                return_value=([], []),
            ),
        ):
            cli = InvitesCli(_make_config())
            cli.show_invite("1")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "Team Meeting" in captured.out
        assert "Boss" in captured.out
        assert "Room 1" in captured.out
        assert "Not in calendar" in captured.out

    @patch.object(InvitesCli, "_create_gcal_client")
    @patch.object(InvitesCli, "_connect")
    def test_invalid_id(
        self, mock_connect: MagicMock, mock_gcal: MagicMock, capsys: object,
    ) -> None:
        """Unknown ID prints error."""
        invites = [_make_invite()]
        client = _make_client()
        mock_connect.return_value = client
        mock_gcal.return_value = None

        with patch.object(InvitesCli, "_scan_invites", return_value=invites):
            cli = InvitesCli(_make_config())
            cli.show_invite("999")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "not found" in captured.out

    @patch.object(InvitesCli, "_create_gcal_client")
    @patch.object(InvitesCli, "_connect")
    def test_cancellation(
        self, mock_connect: MagicMock, mock_gcal: MagicMock, capsys: object,
    ) -> None:
        """Cancelled invite shows CANCELLED status."""
        invites = [_make_cancelled_invite()]
        client = _make_client()
        mock_connect.return_value = client
        mock_gcal.return_value = None

        with (
            patch.object(InvitesCli, "_scan_invites", return_value=invites),
            patch("src.processors.invite_processor.InviteProcessor._check_exists", return_value=False),
        ):
            cli = InvitesCli(_make_config())
            cli.show_invite("1")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "CANCELLED" in captured.out


# ===================================================================
# accept_invite
# ===================================================================

class TestAcceptInvite:
    """Tests for InvitesCli.accept_invite."""

    @patch("src.processors.invites_cli.InviteRsvp")
    @patch.object(InvitesCli, "_create_gcal_client")
    @patch.object(InvitesCli, "_connect")
    def test_new_invite(
        self,
        mock_connect: MagicMock,
        mock_gcal: MagicMock,
        mock_rsvp: MagicMock,
        capsys: object,
    ) -> None:
        """New invite is added to calendar, RSVP sent, moved to meetings."""
        invites = [_make_invite()]
        client = _make_client()
        mock_connect.return_value = client

        gcal = MagicMock()
        gcal.add_event_from_ics.return_value = "event-id-1"
        mock_gcal.return_value = gcal

        with (
            patch.object(InvitesCli, "_scan_invites", return_value=invites),
            patch("src.processors.invite_processor.InviteProcessor._check_exists", return_value=False),
            patch(
                "src.processors.invite_processor.InviteProcessor._move_to_meetings",
                return_value=True,
            ),
        ):
            cli = InvitesCli(_make_config())
            cli.accept_invite("1")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "Added to Google Calendar" in captured.out
        assert "Moved to meetings folder" in captured.out
        gcal.add_event_from_ics.assert_called_once()
        mock_rsvp.handle_rsvp.assert_called_once()

    @patch.object(InvitesCli, "_create_gcal_client")
    @patch.object(InvitesCli, "_connect")
    def test_already_in_calendar(
        self, mock_connect: MagicMock, mock_gcal: MagicMock, capsys: object,
    ) -> None:
        """Already-in-calendar invite is just moved to meetings folder."""
        invites = [_make_invite()]
        client = _make_client()
        mock_connect.return_value = client
        mock_gcal.return_value = MagicMock()

        with (
            patch.object(InvitesCli, "_scan_invites", return_value=invites),
            patch("src.processors.invite_processor.InviteProcessor._check_exists", return_value=True),
            patch(
                "src.processors.invite_processor.InviteProcessor._move_to_meetings",
                return_value=True,
            ),
        ):
            cli = InvitesCli(_make_config())
            cli.accept_invite("1")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "Already in calendar" in captured.out
        assert "Moved to meetings folder" in captured.out

    @patch.object(InvitesCli, "_create_gcal_client")
    @patch.object(InvitesCli, "_connect")
    def test_no_gcal(
        self, mock_connect: MagicMock, mock_gcal: MagicMock, capsys: object,
    ) -> None:
        """No Google Calendar prints error."""
        invites = [_make_invite()]
        client = _make_client()
        mock_connect.return_value = client
        mock_gcal.return_value = None

        with (
            patch.object(InvitesCli, "_scan_invites", return_value=invites),
            patch("src.processors.invite_processor.InviteProcessor._check_exists", return_value=False),
        ):
            cli = InvitesCli(_make_config())
            cli.accept_invite("1")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "Google Calendar not available" in captured.out

    @patch.object(InvitesCli, "_create_gcal_client")
    @patch.object(InvitesCli, "_connect")
    def test_invalid_id(
        self, mock_connect: MagicMock, mock_gcal: MagicMock, capsys: object,
    ) -> None:
        """Unknown ID prints error."""
        invites = [_make_invite()]
        client = _make_client()
        mock_connect.return_value = client
        mock_gcal.return_value = None

        with patch.object(InvitesCli, "_scan_invites", return_value=invites):
            cli = InvitesCli(_make_config())
            cli.accept_invite("999")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "not found" in captured.out


# ===================================================================
# archive_invite
# ===================================================================

class TestArchiveInvite:
    """Tests for InvitesCli.archive_invite."""

    @patch.object(InvitesCli, "_create_gcal_client")
    @patch.object(InvitesCli, "_connect")
    def test_success(
        self, mock_connect: MagicMock, mock_gcal: MagicMock, capsys: object,
    ) -> None:
        """Successful archive prints confirmation."""
        invites = [_make_invite()]
        client = _make_client()
        mock_connect.return_value = client
        mock_gcal.return_value = None

        with patch.object(InvitesCli, "_scan_invites", return_value=invites), patch(
            "src.processors.invite_processor.InviteProcessor._archive_invite",
            return_value=True,
        ):
            cli = InvitesCli(_make_config())
            cli.archive_invite("1")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "Archived invite" in captured.out

    @patch.object(InvitesCli, "_create_gcal_client")
    @patch.object(InvitesCli, "_connect")
    def test_invalid_id(
        self, mock_connect: MagicMock, mock_gcal: MagicMock, capsys: object,
    ) -> None:
        """Unknown ID prints error."""
        invites = [_make_invite()]
        client = _make_client()
        mock_connect.return_value = client
        mock_gcal.return_value = None

        with patch.object(InvitesCli, "_scan_invites", return_value=invites):
            cli = InvitesCli(_make_config())
            cli.archive_invite("999")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "not found" in captured.out


# ===================================================================
# delete_cancelled_invite
# ===================================================================

class TestDeleteCancelledInvite:
    """Tests for InvitesCli.delete_cancelled_invite."""

    @patch.object(InvitesCli, "_create_gcal_client")
    @patch.object(InvitesCli, "_connect")
    def test_with_calendar(
        self, mock_connect: MagicMock, mock_gcal: MagicMock, capsys: object,
    ) -> None:
        """With calendar, deletes event and archives email."""
        invites = [_make_cancelled_invite()]
        client = _make_client()
        mock_connect.return_value = client

        gcal = MagicMock()
        gcal.delete_event.return_value = True
        mock_gcal.return_value = gcal

        with patch.object(InvitesCli, "_scan_invites", return_value=invites), patch(
            "src.processors.invite_processor.InviteProcessor._archive_invite",
            return_value=True,
        ):
            cli = InvitesCli(_make_config())
            cli.delete_cancelled_invite("1")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "Deleted from Google Calendar" in captured.out
        assert "Archived invite" in captured.out
        gcal.delete_event.assert_called_once()

    @patch.object(InvitesCli, "_create_gcal_client")
    @patch.object(InvitesCli, "_connect")
    def test_no_gcal(
        self, mock_connect: MagicMock, mock_gcal: MagicMock, capsys: object,
    ) -> None:
        """Without calendar, just archives email."""
        invites = [_make_cancelled_invite()]
        client = _make_client()
        mock_connect.return_value = client
        mock_gcal.return_value = None

        with patch.object(InvitesCli, "_scan_invites", return_value=invites), patch(
            "src.processors.invite_processor.InviteProcessor._archive_invite",
            return_value=True,
        ):
            cli = InvitesCli(_make_config())
            cli.delete_cancelled_invite("1")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "Deleted from Google Calendar" not in captured.out
        assert "Archived invite" in captured.out

    @patch.object(InvitesCli, "_create_gcal_client")
    @patch.object(InvitesCli, "_connect")
    def test_invalid_id(
        self, mock_connect: MagicMock, mock_gcal: MagicMock, capsys: object,
    ) -> None:
        """Unknown ID prints error."""
        invites = [_make_cancelled_invite()]
        client = _make_client()
        mock_connect.return_value = client
        mock_gcal.return_value = None

        with patch.object(InvitesCli, "_scan_invites", return_value=invites):
            cli = InvitesCli(_make_config())
            cli.delete_cancelled_invite("999")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "not found" in captured.out
