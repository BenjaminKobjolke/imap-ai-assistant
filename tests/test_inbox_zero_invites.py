"""Integration-style tests for InboxZero orchestrator invite handling."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

from src.ai.openai_client import OpenAIClient
from src.config.settings import ConfigManager
from src.constants import ACTION_SHOW_BODY
from src.email.imap_client import EnhancedImapClient
from src.email.smtp_client import SmtpClient
from src.processors.action_result import ActionResult
from src.processors.inbox_zero import InboxZero, InboxZeroCounters
from src.processors.invite_processor import InviteProcessor, ParsedInvite

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_email(subject: str = "Regular email", from_addr: str = "sender@example.com") -> MagicMock:
    """Create a minimal mock email message."""
    msg = MagicMock()
    msg.subject = subject
    msg.from_address = from_addr
    msg.date = "2026-03-04"
    msg.get_body = MagicMock(return_value="Body text")
    return msg


def _make_invite(
    *,
    msg_id: object = 42,
    method: str | None = None,
    summary: str | None = "Team standup",
) -> ParsedInvite:
    """Build a ParsedInvite with sensible defaults."""
    return ParsedInvite(
        message_id=msg_id,
        email_message=_make_email(subject="Meeting invite"),
        subject="Meeting invite",
        ics_data=b"BEGIN:VCALENDAR\nEND:VCALENDAR",
        uid="abc-123",
        summary=summary,
        dtstart=datetime(2026, 3, 10, 14, 0),
        dtend=datetime(2026, 3, 10, 15, 0),
        organizer="Alice",
        organizer_email="alice@example.com",
        location="Room 42",
        method=method,
    )


def _make_deps() -> tuple[MagicMock, MagicMock, MagicMock, MagicMock]:
    """Create mocked dependencies for InboxZero.process_inbox.

    EnhancedImapClient sets ``self.client`` in __init__, so the spec-mock
    does not expose it automatically.  We create the outer mock with spec
    and then attach a plain inner mock as the ``client`` attribute.
    """
    client = MagicMock(spec=EnhancedImapClient)
    # The production code accesses client.client.get_all_messages(), etc.
    client.client = MagicMock()
    config = MagicMock(spec=ConfigManager)
    config.search_cache_path = ":memory:"
    config.trash_folder = "Trash"
    smtp_client = MagicMock(spec=SmtpClient)
    openai_client = MagicMock(spec=OpenAIClient)
    return client, config, smtp_client, openai_client


# ===================================================================
# _update_counters — direct unit tests
# ===================================================================

class TestUpdateCounters:
    """Test the _update_counters static method directly."""

    def test_calendar_added_increments(self) -> None:
        """action_type 'calendar_added' increments calendar_added counter."""
        counters = InboxZeroCounters(total=1)
        InboxZero._update_counters(counters, "calendar_added")
        assert counters.calendar_added == 1

    def test_calendar_deleted_increments(self) -> None:
        """action_type 'calendar_deleted' increments calendar_deleted counter."""
        counters = InboxZeroCounters(total=1)
        InboxZero._update_counters(counters, "calendar_deleted")
        assert counters.calendar_deleted == 1

    def test_archived_increments_moved(self) -> None:
        """action_type 'archived' increments the moved counter."""
        counters = InboxZeroCounters(total=1)
        InboxZero._update_counters(counters, "archived")
        assert counters.moved == 1

    def test_moved_increments_moved(self) -> None:
        """action_type 'moved' increments the moved counter."""
        counters = InboxZeroCounters(total=1)
        InboxZero._update_counters(counters, "moved")
        assert counters.moved == 1

    def test_todoed_increments_todoed(self) -> None:
        """action_type 'todoed' increments the todoed counter."""
        counters = InboxZeroCounters(total=1)
        InboxZero._update_counters(counters, "todoed")
        assert counters.todoed == 1

    def test_unknown_action_type_no_change(self) -> None:
        """An unrecognized action_type leaves all counters at zero."""
        counters = InboxZeroCounters(total=1)
        InboxZero._update_counters(counters, "unknown_thing")
        assert counters.moved == 0
        assert counters.todoed == 0
        assert counters.calendar_added == 0
        assert counters.calendar_deleted == 0
        assert counters.skipped == 0
        assert counters.trashed == 0


# ===================================================================
# Invite detection branch
# ===================================================================

class TestInviteDetectionBranch:
    """When invite_processor detects an invite, the invite path is used."""

    @patch("src.processors.inbox_zero.SearchCache")
    @patch("src.processors.inbox_zero.EmailActionProcessor")
    @patch("src.processors.inbox_zero.send_output")
    @patch("src.processors.inbox_zero.SchedulerChoice")
    def test_invite_uses_invite_display_and_options(
        self,
        mock_scheduler_cls: MagicMock,
        _out: MagicMock,
        mock_action_proc_cls: MagicMock,
        mock_cache_cls: MagicMock,
    ) -> None:
        """When detect_invite returns a ParsedInvite, display_invite and
        get_invite_options are called instead of the regular email display."""
        client, config, smtp, openai = _make_deps()
        email_msg = _make_email(subject="Meeting invite")
        client.client.get_all_messages.return_value = [(1, email_msg)]

        invite = _make_invite(msg_id=1)
        invite_proc = MagicMock(spec=InviteProcessor)
        invite_proc.detect_invite.return_value = invite
        invite_proc.get_invite_options.return_value = [("Add to calendar", "add_calendar")]
        invite_proc.execute_invite_action.return_value = ActionResult(
            success=True, action_type="calendar_added",
        )

        # User picks the first (and only invite-specific) option: "add_calendar"
        mock_choice = MagicMock()
        mock_choice.choose.return_value = "add_calendar"
        mock_scheduler_cls.return_value = mock_choice

        mock_cache_cls.return_value = MagicMock()

        InboxZero.process_inbox(
            client, config, smtp, openai, invite_processor=invite_proc,
        )

        invite_proc.detect_invite.assert_called_once_with(1, email_msg)
        invite_proc.display_invite.assert_called_once_with(invite, 1, 1)
        invite_proc.get_invite_options.assert_called_once_with(invite)
        invite_proc.execute_invite_action.assert_called_once_with(
            "add_calendar", invite, dry_run=False,
        )

    @patch("src.processors.inbox_zero.SearchCache")
    @patch("src.processors.inbox_zero.EmailActionProcessor")
    @patch("src.processors.inbox_zero.send_output")
    @patch("src.processors.inbox_zero.SchedulerChoice")
    def test_invite_branch_appends_generic_options(
        self,
        mock_scheduler_cls: MagicMock,
        _out: MagicMock,
        mock_action_proc_cls: MagicMock,
        mock_cache_cls: MagicMock,
    ) -> None:
        """Both invite and regular branches append Skip, Trash, Show body."""
        client, config, smtp, openai = _make_deps()
        email_msg = _make_email()
        client.client.get_all_messages.return_value = [(1, email_msg)]

        invite = _make_invite(msg_id=1)
        invite_proc = MagicMock(spec=InviteProcessor)
        invite_proc.detect_invite.return_value = invite
        invite_proc.get_invite_options.return_value = [("Archive", "archive_invite")]

        # User picks "skip" to exit the loop
        mock_choice = MagicMock()
        mock_choice.choose.return_value = "skip"
        mock_scheduler_cls.return_value = mock_choice

        mock_cache_cls.return_value = MagicMock()

        InboxZero.process_inbox(
            client, config, smtp, openai, invite_processor=invite_proc,
        )

        # Verify SchedulerChoice was constructed with the appended generic options
        call_args = mock_scheduler_cls.call_args
        options_passed = call_args[0][1]  # second positional arg is the options list
        assert ("Skip", "skip") in options_passed
        assert ("Trash", "trash") in options_passed
        assert ("Show body", ACTION_SHOW_BODY) in options_passed


# ===================================================================
# Regular email branch (invite_processor returns None)
# ===================================================================

class TestRegularEmailBranch:
    """When detect_invite returns None, the regular email path is used."""

    @patch("src.processors.inbox_zero.SearchCache")
    @patch("src.processors.inbox_zero.EmailActionProcessor")
    @patch("src.processors.inbox_zero.send_output")
    @patch("src.processors.inbox_zero.SchedulerChoice")
    def test_regular_path_when_detect_returns_none(
        self,
        mock_scheduler_cls: MagicMock,
        _out: MagicMock,
        mock_action_proc_cls: MagicMock,
        mock_cache_cls: MagicMock,
    ) -> None:
        """When detect_invite returns None, EmailActionProcessor.get_options is called."""
        client, config, smtp, openai = _make_deps()
        email_msg = _make_email()
        client.client.get_all_messages.return_value = [(1, email_msg)]

        invite_proc = MagicMock(spec=InviteProcessor)
        invite_proc.detect_invite.return_value = None

        mock_action = MagicMock()
        mock_action.get_options.return_value = [("Move to folder", "move_other")]
        mock_action.execute_action.return_value = ActionResult(
            success=True, action_type="moved",
        )
        mock_action_proc_cls.return_value = mock_action

        mock_cache = MagicMock()
        mock_cache.suggest_folder_for_sender.return_value = None
        mock_cache_cls.return_value = mock_cache

        mock_choice = MagicMock()
        mock_choice.choose.return_value = "move_other"
        mock_scheduler_cls.return_value = mock_choice

        InboxZero.process_inbox(
            client, config, smtp, openai, invite_processor=invite_proc,
        )

        invite_proc.detect_invite.assert_called_once_with(1, email_msg)
        invite_proc.display_invite.assert_not_called()
        invite_proc.get_invite_options.assert_not_called()
        mock_action.get_options.assert_called_once()

    @patch("src.processors.inbox_zero.SearchCache")
    @patch("src.processors.inbox_zero.EmailActionProcessor")
    @patch("src.processors.inbox_zero.send_output")
    @patch("src.processors.inbox_zero.SchedulerChoice")
    def test_regular_branch_appends_generic_options(
        self,
        mock_scheduler_cls: MagicMock,
        _out: MagicMock,
        mock_action_proc_cls: MagicMock,
        mock_cache_cls: MagicMock,
    ) -> None:
        """Regular branch also appends Skip, Trash, Show body options."""
        client, config, smtp, openai = _make_deps()
        email_msg = _make_email()
        client.client.get_all_messages.return_value = [(1, email_msg)]

        invite_proc = MagicMock(spec=InviteProcessor)
        invite_proc.detect_invite.return_value = None

        mock_action = MagicMock()
        mock_action.get_options.return_value = [("Move to folder", "move_other")]
        mock_action_proc_cls.return_value = mock_action

        mock_cache = MagicMock()
        mock_cache.suggest_folder_for_sender.return_value = None
        mock_cache_cls.return_value = mock_cache

        mock_choice = MagicMock()
        mock_choice.choose.return_value = "skip"
        mock_scheduler_cls.return_value = mock_choice

        InboxZero.process_inbox(
            client, config, smtp, openai, invite_processor=invite_proc,
        )

        call_args = mock_scheduler_cls.call_args
        options_passed = call_args[0][1]
        assert ("Skip", "skip") in options_passed
        assert ("Trash", "trash") in options_passed
        assert ("Show body", ACTION_SHOW_BODY) in options_passed


# ===================================================================
# No invite_processor provided
# ===================================================================

class TestNoInviteProcessor:
    """When invite_processor is None, all emails go through the regular path."""

    @patch("src.processors.inbox_zero.SearchCache")
    @patch("src.processors.inbox_zero.EmailActionProcessor")
    @patch("src.processors.inbox_zero.send_output")
    @patch("src.processors.inbox_zero.SchedulerChoice")
    def test_none_processor_uses_regular_path(
        self,
        mock_scheduler_cls: MagicMock,
        _out: MagicMock,
        mock_action_proc_cls: MagicMock,
        mock_cache_cls: MagicMock,
    ) -> None:
        """With invite_processor=None, no invite detection occurs."""
        client, config, smtp, openai = _make_deps()
        email_msg = _make_email()
        client.client.get_all_messages.return_value = [(1, email_msg)]

        mock_action = MagicMock()
        mock_action.get_options.return_value = [("Move to folder", "move_other")]
        mock_action.execute_action.return_value = ActionResult(
            success=True, action_type="moved",
        )
        mock_action_proc_cls.return_value = mock_action

        mock_cache = MagicMock()
        mock_cache.suggest_folder_for_sender.return_value = None
        mock_cache_cls.return_value = mock_cache

        mock_choice = MagicMock()
        mock_choice.choose.return_value = "move_other"
        mock_scheduler_cls.return_value = mock_choice

        InboxZero.process_inbox(
            client, config, smtp, openai, invite_processor=None,
        )

        # Regular path was used
        mock_action.get_options.assert_called_once()
        mock_action.execute_action.assert_called_once()


# ===================================================================
# Counter updates after execute_invite_action
# ===================================================================

class TestInviteCounterUpdates:
    """Verify counters are updated correctly after invite action execution."""

    @patch("src.processors.inbox_zero.SearchCache")
    @patch("src.processors.inbox_zero.EmailActionProcessor")
    @patch("src.processors.inbox_zero.send_output")
    @patch("src.processors.inbox_zero.SchedulerChoice")
    def _run_with_action_type(
        self,
        action_type: str,
        mock_scheduler_cls: MagicMock,
        _out: MagicMock,
        mock_action_proc_cls: MagicMock,
        mock_cache_cls: MagicMock,
    ) -> InboxZeroCounters:
        """Helper: run process_inbox with an invite that resolves to the given action_type."""
        client, config, smtp, openai = _make_deps()
        email_msg = _make_email()
        client.client.get_all_messages.return_value = [(1, email_msg)]

        invite = _make_invite(msg_id=1)
        invite_proc = MagicMock(spec=InviteProcessor)
        invite_proc.detect_invite.return_value = invite
        invite_proc.get_invite_options.return_value = [("Action", "the_action")]
        invite_proc.execute_invite_action.return_value = ActionResult(
            success=True, action_type=action_type,
        )

        mock_choice = MagicMock()
        mock_choice.choose.return_value = "the_action"
        mock_scheduler_cls.return_value = mock_choice

        mock_cache_cls.return_value = MagicMock()

        # Capture the counters by patching _display_summary
        captured: list[InboxZeroCounters] = []
        original_display = InboxZero._display_summary

        def capture_summary(counters: InboxZeroCounters) -> None:
            captured.append(counters)
            original_display(counters)

        with patch.object(InboxZero, "_display_summary", side_effect=capture_summary):
            InboxZero.process_inbox(
                client, config, smtp, openai, invite_processor=invite_proc,
            )

        assert len(captured) == 1
        return captured[0]

    def test_calendar_added_counter(self) -> None:
        """calendar_added action increments calendar_added counter."""
        counters = self._run_with_action_type("calendar_added")
        assert counters.calendar_added == 1
        assert counters.moved == 0

    def test_calendar_deleted_counter(self) -> None:
        """calendar_deleted action increments calendar_deleted counter."""
        counters = self._run_with_action_type("calendar_deleted")
        assert counters.calendar_deleted == 1
        assert counters.moved == 0

    def test_archived_counter(self) -> None:
        """archived action increments moved counter."""
        counters = self._run_with_action_type("archived")
        assert counters.moved == 1
        assert counters.calendar_added == 0

    def test_moved_counter(self) -> None:
        """moved action increments moved counter."""
        counters = self._run_with_action_type("moved")
        assert counters.moved == 1

    def test_todoed_counter(self) -> None:
        """todoed action increments todoed counter."""
        counters = self._run_with_action_type("todoed")
        assert counters.todoed == 1
