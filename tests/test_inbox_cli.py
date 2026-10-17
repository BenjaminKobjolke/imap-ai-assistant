"""Tests for the InboxCli non-interactive inbox operations."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.constants import FOLDER_INBOX
from src.processors.inbox_cli import InboxCli
from tests.inbox_cli_helpers import make_client, make_config, make_email


# ===================================================================
# list_inbox
# ===================================================================

class TestListInbox:
    """Tests for InboxCli.list_inbox."""

    @patch.object(InboxCli, "_connect")
    def test_empty_inbox(self, mock_connect: MagicMock, capsys: object) -> None:
        """Empty inbox prints appropriate message."""
        client = make_client([])
        mock_connect.return_value = client

        cli = InboxCli(make_config())
        cli.list_inbox()

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "INBOX is empty" in captured.out
        client.disconnect.assert_called_once()

    @patch.object(InboxCli, "_connect")
    def test_with_messages(self, mock_connect: MagicMock, capsys: object) -> None:
        """Messages are listed with id, index, from, subject, date."""
        messages = [
            (1, make_email(subject="Email A", from_address="a@test.com", date="2026-03-01")),
            (2, make_email(subject="Email B", from_address="b@test.com", date="2026-03-02")),
            (3, make_email(subject="Email C", from_address="c@test.com", date="2026-03-03")),
        ]
        client = make_client(messages)
        mock_connect.return_value = client

        cli = InboxCli(make_config())
        cli.list_inbox()

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "[id:1]" in captured.out
        assert "[1]" in captured.out
        assert "a@test.com" in captured.out
        assert "Email A" in captured.out
        assert "[id:2]" in captured.out
        assert "[id:3]" in captured.out
        assert "3 email(s)" in captured.out

    @patch.object(InboxCli, "_connect")
    def test_unread_only(self, mock_connect: MagicMock, capsys: object) -> None:
        """Unread-only mode calls get_unread_messages."""
        messages = [(1, make_email())]
        client = make_client(messages)
        mock_connect.return_value = client

        cli = InboxCli(make_config())
        cli.list_inbox(unread_only=True)

        client.client.get_unread_messages.assert_called_once()
        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "unread" in captured.out


# ===================================================================
# show_email
# ===================================================================

class TestShowEmail:
    """Tests for InboxCli.show_email."""

    @patch.object(InboxCli, "_connect")
    def test_valid_id(self, mock_connect: MagicMock, capsys: object) -> None:
        """Valid ID prints email details and body."""
        messages = [(1, make_email(subject="Important email", from_address="boss@work.com"))]
        client = make_client(messages)
        mock_connect.return_value = client

        cli = InboxCli(make_config())
        cli.show_email("1")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "boss@work.com" in captured.out
        assert "Important email" in captured.out
        assert "Hello, this is the body." in captured.out

    @patch.object(InboxCli, "_connect")
    def test_invalid_id(self, mock_connect: MagicMock, capsys: object) -> None:
        """Unknown ID prints error."""
        messages = [(1, make_email())]
        client = make_client(messages)
        mock_connect.return_value = client

        cli = InboxCli(make_config())
        cli.show_email("999")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "not found" in captured.out


# ===================================================================
# move_email
# ===================================================================

class TestMoveEmail:
    """Tests for InboxCli.move_email."""

    @patch.object(InboxCli, "_connect")
    def test_success(self, mock_connect: MagicMock, capsys: object) -> None:
        """Successful move marks as read and moves."""
        messages = [(42, make_email())]
        client = make_client(messages)
        mock_connect.return_value = client

        cli = InboxCli(make_config())
        cli.move_email("42", "Company/Sales")

        client.client.client.select_folder.assert_called_with(FOLDER_INBOX)
        client.client.mark_as_read.assert_called_with("42")
        client.client.move_to_folder.assert_called_with(42, "Company/Sales")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "Moved email 42 to 'Company/Sales'" in captured.out

    @patch.object(InboxCli, "_connect")
    def test_invalid_id(self, mock_connect: MagicMock, capsys: object) -> None:
        """Unknown ID prints error."""
        client = make_client([(1, make_email())])
        mock_connect.return_value = client

        cli = InboxCli(make_config())
        cli.move_email("999", "Trash")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "not found" in captured.out


# ===================================================================
# trash_email
# ===================================================================

class TestTrashEmail:
    """Tests for InboxCli.trash_email."""

    @patch.object(InboxCli, "_connect")
    def test_success(self, mock_connect: MagicMock, capsys: object) -> None:
        """Trash moves to config.trash_folder."""
        messages = [(10, make_email())]
        client = make_client(messages)
        mock_connect.return_value = client

        cli = InboxCli(make_config())
        cli.trash_email("10")

        client.client.move_to_folder.assert_called_with(10, "Trash")
        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "Moved email 10 to 'Trash'" in captured.out


# ===================================================================
# list_folders
# ===================================================================

class TestListFolders:
    """Tests for InboxCli.list_folders."""

    @patch.object(InboxCli, "_connect")
    def test_prints_sorted_folders(self, mock_connect: MagicMock, capsys: object) -> None:
        """Lists folders in sorted order."""
        client = make_client()
        mock_connect.return_value = client

        cli = InboxCli(make_config())
        cli.list_folders()

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "Company/@BKToDo" in captured.out
        assert "Company/Sales" in captured.out
        assert "INBOX" in captured.out
        assert "Trash" in captured.out


# ===================================================================
# todo_from_email
# ===================================================================

class TestTodoFromEmail:
    """Tests for InboxCli.todo_from_email."""

    @patch.object(InboxCli, "_connect")
    @patch("src.services.todo_service.TodoService")
    @patch("src.ai.openai_client.OpenAIClient")
    def test_success(
        self,
        mock_openai_cls: MagicMock,
        mock_todo_cls: MagicMock,
        mock_connect: MagicMock,
        capsys: object,
    ) -> None:
        """Creates todo, sends it, and moves email."""
        messages = [(7, make_email())]
        client = make_client(messages)
        mock_connect.return_value = client

        # Mock OpenAI client
        mock_openai = MagicMock()
        mock_openai_cls.return_value = mock_openai

        # Mock todo generation
        mock_result = MagicMock()
        mock_result.rtm_text = "Do the thing ^today"
        mock_todo_cls.generate_todo.return_value = mock_result

        # Mock todo service instance
        mock_todo_svc = MagicMock()
        mock_todo_svc.send_todo.return_value = (True, None)
        mock_todo_svc.resolve_extra_tags.return_value = ""
        mock_todo_cls.return_value = mock_todo_svc

        cli = InboxCli(make_config())
        cli.todo_from_email("7")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "Todo created" in captured.out
        assert "Moved email 7" in captured.out
        client.client.move_to_folder.assert_called_once()

    @patch.object(InboxCli, "_connect")
    def test_invalid_id(self, mock_connect: MagicMock, capsys: object) -> None:
        """Unknown ID prints error."""
        client = make_client([(1, make_email())])
        mock_connect.return_value = client

        cli = InboxCli(make_config())
        cli.todo_from_email("999")

        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "not found" in captured.out
