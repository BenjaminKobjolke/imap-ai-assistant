"""Tests for the EmailActionProcessor public API (get_options, execute_action)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.ai.openai_client import OpenAIClient
from src.config.settings import ConfigManager
from src.constants import ACTION_DRAFT_REPLY, CFG_TARGET_FOLDER
from src.email.imap_client import EnhancedImapClient
from src.email.smtp_client import SmtpClient
from src.processors.action_result import ActionResult
from src.processors.email_action_processor import EmailActionProcessor
from src.search.search_cache import SearchCache


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_email(
    *,
    subject: str = "Test email",
    from_address: str = "sender@example.com",
) -> MagicMock:
    """Create a minimal mock email message."""
    msg = MagicMock()
    msg.subject = subject
    msg.from_address = from_address
    msg.get_body = MagicMock(return_value="Some body text")
    return msg


def _processor() -> EmailActionProcessor:
    """Create an EmailActionProcessor with mocked dependencies."""
    client = MagicMock(spec=EnhancedImapClient)
    # EnhancedImapClient.client is set in __init__; wire the nested mock chain
    # so that client.client.client.select_folder / client.client.mark_as_read etc. work.
    inner_imap = MagicMock()
    client.client = inner_imap
    # extract_email_content returns (subject, first_line, body_excerpt)
    client.extract_email_content = MagicMock(
        return_value=("Test email", "First line", "Body excerpt"),
    )

    config = MagicMock(spec=ConfigManager)
    smtp_client = MagicMock(spec=SmtpClient)
    openai_client = MagicMock(spec=OpenAIClient)
    cache = MagicMock(spec=SearchCache)

    config.get_processing_rules.return_value = {
        CFG_TARGET_FOLDER: "Company/@BKToDo",
    }

    return EmailActionProcessor(client, config, smtp_client, openai_client, cache)


# ===================================================================
# get_options
# ===================================================================

class TestGetOptions:
    """Tests for EmailActionProcessor.get_options."""

    def test_with_suggestion(self) -> None:
        """When a suggestion is provided, the first option targets that folder."""
        proc = _processor()

        options = proc.get_options("Company/Sales")

        assert options == [
            ("Move to 'Company/Sales'", "move_suggested"),
            ("Move to other folder", "move_other"),
            ("Add todo", "todo"),
            ("Draft a reply", ACTION_DRAFT_REPLY),
        ]

    def test_without_suggestion(self) -> None:
        """When suggestion is None, there is no move_suggested option."""
        proc = _processor()

        options = proc.get_options(None)

        assert options == [
            ("Move to folder", "move_other"),
            ("Add todo", "todo"),
            ("Draft a reply", ACTION_DRAFT_REPLY),
        ]

    def test_empty_string_suggestion_treated_as_no_suggestion(self) -> None:
        """An empty string is falsy, so it behaves like None."""
        proc = _processor()

        options = proc.get_options("")

        assert options == [
            ("Move to folder", "move_other"),
            ("Add todo", "todo"),
            ("Draft a reply", ACTION_DRAFT_REPLY),
        ]


# ===================================================================
# execute_action — move_suggested
# ===================================================================

class TestExecuteMoveSuggested:
    """Tests for the move_suggested action."""

    @patch("src.processors.email_action_processor.send_output")
    def test_move_suggested_success(self, _out: MagicMock) -> None:
        """move_suggested moves to the suggested folder and returns success."""
        proc = _processor()
        proc._client.client.move_to_folder.return_value = True
        msg_id = 42
        email_msg = _make_email()

        result = proc.execute_action(
            "move_suggested", msg_id, email_msg, suggestion="Company/Sales",
        )

        assert result == ActionResult(success=True, action_type="moved")
        proc._client.client.client.select_folder.assert_called_once_with("INBOX")
        proc._client.client.mark_as_read.assert_called_once_with("42")
        proc._client.client.move_to_folder.assert_called_once_with(42, "Company/Sales")

    @patch("src.processors.email_action_processor.send_output")
    def test_move_suggested_dry_run(self, _out: MagicMock) -> None:
        """Dry-run move_suggested returns success without calling IMAP."""
        proc = _processor()
        msg_id = 10
        email_msg = _make_email()

        result = proc.execute_action(
            "move_suggested", msg_id, email_msg, suggestion="Archive", dry_run=True,
        )

        assert result == ActionResult(success=True, action_type="moved")
        proc._client.client.move_to_folder.assert_not_called()

    @patch("src.processors.email_action_processor.send_output")
    def test_move_suggested_imap_failure(self, _out: MagicMock) -> None:
        """When IMAP move returns False, result reports failure."""
        proc = _processor()
        proc._client.client.move_to_folder.return_value = False
        msg_id = 7
        email_msg = _make_email()

        result = proc.execute_action(
            "move_suggested", msg_id, email_msg, suggestion="Trash",
        )

        assert result == ActionResult(success=False, action_type="skipped")


# ===================================================================
# execute_action — move_other
# ===================================================================

class TestExecuteMoveOther:
    """Tests for the move_other action (interactive folder search)."""

    @patch("src.processors.email_action_processor.send_output")
    def test_move_other_abort_returns_abort(self, _out: MagicMock) -> None:
        """When folder search returns _abort_, result is abort."""
        proc = _processor()
        msg_id = 5
        email_msg = _make_email()

        with patch.object(proc, "_search_folder", return_value="_abort_"):
            result = proc.execute_action("move_other", msg_id, email_msg)

        assert result == ActionResult(success=False, action_type="abort")

    @patch("src.processors.email_action_processor.send_output")
    def test_move_other_cancel_returns_skipped(self, _out: MagicMock) -> None:
        """When folder search returns None (cancel), result is skipped."""
        proc = _processor()
        msg_id = 5
        email_msg = _make_email()

        with patch.object(proc, "_search_folder", return_value=None):
            result = proc.execute_action("move_other", msg_id, email_msg)

        assert result == ActionResult(success=False, action_type="skipped")

    @patch("src.processors.email_action_processor.send_output")
    def test_move_other_folder_found(self, _out: MagicMock) -> None:
        """When folder search finds a folder, email is moved there."""
        proc = _processor()
        proc._client.client.move_to_folder.return_value = True
        msg_id = 5
        email_msg = _make_email()

        with patch.object(proc, "_search_folder", return_value="Company/HR"):
            result = proc.execute_action("move_other", msg_id, email_msg)

        assert result == ActionResult(success=True, action_type="moved")
        proc._client.client.move_to_folder.assert_called_once_with(5, "Company/HR")


# ===================================================================
# execute_action — todo
# ===================================================================

class TestExecuteTodo:
    """Tests for the todo action."""

    @patch("src.processors.email_action_processor.send_output")
    @patch("src.processors.email_action_processor.RtmTodoCreator.create_and_send")
    def test_todo_success(self, mock_create: MagicMock, _out: MagicMock) -> None:
        """Successful todo creation moves email to target folder."""
        proc = _processor()
        mock_create.return_value = (True, "Buy milk !2 ^today")
        msg_id = 99
        email_msg = _make_email()

        result = proc.execute_action("todo", msg_id, email_msg)

        assert result == ActionResult(success=True, action_type="todoed")
        mock_create.assert_called_once()
        proc._client.client.client.select_folder.assert_called_once_with("INBOX")
        proc._client.client.mark_as_read.assert_called_once_with("99")
        proc._client.client.move_to_folder.assert_called_once_with(99, "Company/@BKToDo")

    @patch("src.processors.email_action_processor.send_output")
    @patch("src.processors.email_action_processor.RtmTodoCreator.create_and_send")
    def test_todo_dry_run(self, mock_create: MagicMock, _out: MagicMock) -> None:
        """Dry-run todo returns success without moving."""
        proc = _processor()
        mock_create.return_value = (True, "Call client !1 ^tomorrow")
        msg_id = 50
        email_msg = _make_email()

        result = proc.execute_action("todo", msg_id, email_msg, dry_run=True)

        assert result == ActionResult(success=True, action_type="todoed")
        proc._client.client.move_to_folder.assert_not_called()

    @patch("src.processors.email_action_processor.RtmTodoCreator.create_and_send")
    def test_todo_creation_fails(self, mock_create: MagicMock) -> None:
        """When RtmTodoCreator fails, result is skipped."""
        proc = _processor()
        mock_create.return_value = (False, "")
        msg_id = 33
        email_msg = _make_email()

        result = proc.execute_action("todo", msg_id, email_msg)

        assert result == ActionResult(success=False, action_type="skipped")
        proc._client.client.move_to_folder.assert_not_called()


# ===================================================================
# execute_action — draft_reply
# ===================================================================

class TestExecuteDraftReply:
    """Tests for the draft_reply action."""

    @patch("src.processors.email_action_processor.EmailActionProcessor._action_draft_reply")
    def test_draft_reply_returns_continue_loop(self, mock_draft: MagicMock) -> None:
        """draft_reply always returns continue_loop=True."""
        proc = _processor()
        msg_id = 1
        email_msg = _make_email()

        result = proc.execute_action(ACTION_DRAFT_REPLY, msg_id, email_msg)

        assert result == ActionResult(success=True, action_type="drafted", continue_loop=True)
        mock_draft.assert_called_once_with(email_msg)

    @patch("src.processors.email_action_processor.EmailActionProcessor._action_draft_reply")
    def test_draft_reply_continue_loop_is_true(self, mock_draft: MagicMock) -> None:
        """Verify continue_loop is explicitly True so the menu re-appears."""
        proc = _processor()
        email_msg = _make_email()

        result = proc.execute_action(ACTION_DRAFT_REPLY, 1, email_msg)

        assert result.continue_loop is True


# ===================================================================
# execute_action — unknown action
# ===================================================================

class TestExecuteUnknownAction:
    """Tests for unrecognized action strings."""

    def test_unknown_action_returns_skipped(self) -> None:
        """An unrecognized action returns a failed/skipped result."""
        proc = _processor()
        email_msg = _make_email()

        result = proc.execute_action("nonexistent", 1, email_msg)

        assert result == ActionResult(success=False, action_type="skipped")
