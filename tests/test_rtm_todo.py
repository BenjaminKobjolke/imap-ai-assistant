"""Tests for TodoService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.ai.openai_client import TodoResult
from src.config.settings import ConfigManager
from src.services.todo_service import RtmTodoCreator, TodoService


class TestTodoResultRtmText:
    """Tests for TodoResult.rtm_text property."""

    def test_rtm_text_with_time(self) -> None:
        """Verify rtm_text includes time when due_time is set."""
        result = TodoResult(title="Buy milk", priority=2, due_date="tomorrow", assignee="self", due_time="08:00")
        assert result.rtm_text == "Buy milk !2 ^tomorrow 08:00"

    def test_rtm_text_without_time(self) -> None:
        """Verify rtm_text omits time when due_time is empty."""
        result = TodoResult(title="Buy milk", priority=2, due_date="tomorrow", assignee="self")
        assert result.rtm_text == "Buy milk !2 ^tomorrow"


class TestTodoServiceInit:
    """Tests for TodoService constructor."""

    def test_creates_own_smtp_client(self) -> None:
        """Verify constructor creates SmtpClient from config.smtp_config."""
        config = MagicMock(spec=ConfigManager)
        config.smtp_config = {
            "server": "smtp.example.com",
            "port": 587,
            "username": "user@example.com",
            "password": "secret",
        }

        with patch("src.services.todo_service.SmtpClient") as mock_smtp_cls:
            proc = TodoService(config)
            mock_smtp_cls.assert_called_once_with(config.smtp_config)
            assert proc._smtp_client is mock_smtp_cls.return_value

    def test_backwards_compatible_alias(self) -> None:
        """Verify RtmTodoCreator is an alias for TodoService."""
        assert RtmTodoCreator is TodoService


class TestSendDirect:
    """Tests for TodoService.send_direct."""

    @pytest.fixture()
    def todo_processor(self) -> TodoService:
        """Create a TodoService with mocked internals."""
        config = MagicMock(spec=ConfigManager)
        config.smtp_config = {}
        config.get_processing_rules.return_value = {
            "additional_subject_tag": "#BKToDo",
        }
        config.rtm_email = "rtm@example.com"

        with patch("src.services.todo_service.SmtpClient"):
            proc = TodoService(config)
        return proc

    @patch("src.services.todo_service.send_output")
    def test_send_direct_success(self, mock_output: MagicMock, todo_processor: TodoService) -> None:
        """Verify send_direct calls send_rtm_todo with correct RTM format."""
        todo_processor._smtp_client.send_rtm_todo.return_value = (True, b"message")

        result = todo_processor.send_direct("Buy milk", priority=2, due_date="tomorrow")

        assert result is True
        todo_processor._smtp_client.send_rtm_todo.assert_called_once_with(
            rtm_email="rtm@example.com",
            todo_text="Buy milk !2 ^tomorrow",
            subject_tag="#BKToDo",
            original_subject="",
            original_sender="AI Chat",
            task_tracking_headers=None,
        )
        mock_output.assert_called_with("Todo sent: Buy milk !2 ^tomorrow #BKToDo")

    @patch("src.services.todo_service.send_output")
    def test_send_direct_defaults(self, mock_output: MagicMock, todo_processor: TodoService) -> None:
        """Verify send_direct uses priority=3 and due_date=today by default."""
        todo_processor._smtp_client.send_rtm_todo.return_value = (True, b"message")

        result = todo_processor.send_direct("Do laundry")

        assert result is True
        call_kwargs = todo_processor._smtp_client.send_rtm_todo.call_args
        assert call_kwargs.kwargs["todo_text"] == "Do laundry !3 ^today"

    @patch("src.services.todo_service.send_output")
    def test_send_direct_missing_rtm_email(self, mock_output: MagicMock) -> None:
        """Verify graceful failure when rtm_email is not configured."""
        config = MagicMock(spec=ConfigManager)
        config.smtp_config = {}
        config.get_processing_rules.return_value = {
            "additional_subject_tag": "#BKToDo",
        }
        config.rtm_email = ""

        with patch("src.services.todo_service.SmtpClient"):
            proc = TodoService(config)

        result = proc.send_direct("Buy milk")

        assert result is False
        mock_output.assert_called_with("Failed to send todo to RTM.")

    @patch("src.services.todo_service.send_output")
    def test_send_direct_with_time(self, mock_output: MagicMock, todo_processor: TodoService) -> None:
        """Verify send_direct includes time in RTM format."""
        todo_processor._smtp_client.send_rtm_todo.return_value = (True, b"message")

        result = todo_processor.send_direct("Buy milk", priority=2, due_date="tomorrow", due_time="08:00")

        assert result is True
        todo_processor._smtp_client.send_rtm_todo.assert_called_once_with(
            rtm_email="rtm@example.com",
            todo_text="Buy milk !2 ^tomorrow 08:00",
            subject_tag="#BKToDo",
            original_subject="",
            original_sender="AI Chat",
            task_tracking_headers=None,
        )
        mock_output.assert_called_with("Todo sent: Buy milk !2 ^tomorrow 08:00 #BKToDo")

    @patch("src.services.todo_service.send_output")
    def test_send_direct_smtp_failure(self, mock_output: MagicMock, todo_processor: TodoService) -> None:
        """Verify failure message when SMTP send fails."""
        todo_processor._smtp_client.send_rtm_todo.return_value = (False, None)

        result = todo_processor.send_direct("Buy milk")

        assert result is False
        mock_output.assert_called_with("Failed to send todo to RTM.")
