"""Tests for ChatHandler, ChatSession, and CommandExecutor."""

from __future__ import annotations

import json
import logging
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ai.chat_handler import (
    ChatHandler,
    ChatSession,
    CommandExecutor,
    DetectedIntent,
    ExitChatError,
    ValidatedCommand,
)
from src.ai.command_registry import CommandRegistry
from src.ai.openai_client import OpenAIClient
from src.config.settings import ConfigManager
from src.interaction.scheduler_prompts import SchedulerAbortError
from src.processors.email_processor import EmailProcessor

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def openai_client() -> MagicMock:
    """Create a mock OpenAIClient."""
    mock = MagicMock(spec=OpenAIClient)
    mock.build_ai_chat_system_prompt.return_value = "system prompt"
    return mock


@pytest.fixture()
def registry() -> CommandRegistry:
    """Create an empty CommandRegistry (populated by executor fixture)."""
    return CommandRegistry()


@pytest.fixture()
def processor() -> MagicMock:
    """Create a mock EmailProcessor."""
    return MagicMock(spec=EmailProcessor)


@pytest.fixture()
def config() -> MagicMock:
    """Create a mock ConfigManager with calendar data."""
    mock = MagicMock(spec=ConfigManager)
    mock.cached_calendars = [
        {"name": "Termine", "id": "abc@group.calendar.google.com"},
        {"name": "Privat", "id": "def@group.calendar.google.com"},
        {"name": "XD Mitarbeiter", "id": "ghi@group.calendar.google.com"},
    ]
    mock.add_date_calendar_name = "Termine"
    mock.chat_max_history = 100
    mock.log_dir = "logs"
    return mock


@pytest.fixture()
def executor(processor: MagicMock, registry: CommandRegistry) -> CommandExecutor:
    """Create a CommandExecutor with a mock processor, bound to registry."""
    ex = CommandExecutor(processor)
    ex.bind_to_registry(registry)
    return ex


@pytest.fixture()
def handler(
    openai_client: MagicMock,
    registry: CommandRegistry,
    executor: CommandExecutor,
    config: MagicMock,
) -> ChatHandler:
    """Create a ChatHandler with mock dependencies."""
    return ChatHandler(openai_client, registry, executor, config=config)


# ---------------------------------------------------------------------------
# ChatSession tests
# ---------------------------------------------------------------------------

class TestChatSession:
    """Tests for ChatSession."""

    def test_add_message(self) -> None:
        """Verify messages are appended correctly."""
        session = ChatSession()
        session.add_message("system", "hello")
        session.add_message("user", "world")
        assert len(session.history) == 2
        assert session.history[0].role == "system"
        assert session.history[1].content == "world"

    def test_to_openai_messages(self) -> None:
        """Verify conversion to OpenAI message format."""
        session = ChatSession()
        session.add_message("system", "sys")
        session.add_message("user", "usr")
        messages = session.to_openai_messages()
        assert messages == [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "usr"},
        ]

    def test_clear_for_new_request_keeps_system(self) -> None:
        """Verify clear keeps only system messages."""
        session = ChatSession()
        session.add_message("system", "sys")
        session.add_message("user", "usr")
        session.add_message("assistant", "asst")
        session.clear_for_new_request()
        assert len(session.history) == 1
        assert session.history[0].role == "system"

    def test_trim_drops_oldest_messages(self) -> None:
        """Verify trimming keeps system prompt and most recent messages."""
        session = ChatSession(max_history=5)
        session.add_message("system", "sys")
        for i in range(6):
            session.add_message("user", f"msg{i}")
        # 1 system + 4 most recent user messages = 5 total
        assert len(session.history) == 5
        assert session.history[0].role == "system"
        assert session.history[1].content == "msg2"
        assert session.history[-1].content == "msg5"

    def test_trim_preserves_all_when_under_limit(self) -> None:
        """Verify no trimming when under max_history."""
        session = ChatSession(max_history=10)
        session.add_message("system", "sys")
        session.add_message("user", "a")
        session.add_message("assistant", "b")
        assert len(session.history) == 3


# ---------------------------------------------------------------------------
# CommandExecutor tests
# ---------------------------------------------------------------------------

class TestCommandExecutor:
    """Tests for CommandExecutor."""

    def test_execute_todays_meetings(
        self, executor: CommandExecutor, processor: MagicMock,
    ) -> None:
        """Verify todays_meetings is called without arguments."""
        executor.execute("todays_meetings", {})
        processor.todays_meetings.assert_called_once_with()

    def test_execute_inbox_zero_default(
        self, executor: CommandExecutor, processor: MagicMock,
    ) -> None:
        """Verify inbox_zero defaults to unread_only=False."""
        executor.execute("inbox_zero", {})
        processor.inbox_zero.assert_called_once_with(unread_only=False)

    def test_execute_inbox_zero_unread(
        self, executor: CommandExecutor, processor: MagicMock,
    ) -> None:
        """Verify inbox_zero passes unread_only=True."""
        executor.execute("inbox_zero", {"unread_only": True})
        processor.inbox_zero.assert_called_once_with(unread_only=True)

    def test_execute_search(
        self, executor: CommandExecutor, processor: MagicMock,
    ) -> None:
        """Verify search passes all parameters correctly."""
        executor.execute("search", {
            "search_term": "test",
            "body_term": "body",
            "date": "01.01.2026",
        })
        processor.search_emails.assert_called_once_with(
            search_term="test",
            body_term="body",
            date="01.01.2026",
            date_after=None,
            date_before=None,
            path=None,
        )

    def test_execute_add_date_minimal(
        self, executor: CommandExecutor, processor: MagicMock,
    ) -> None:
        """Verify add_date with only title."""
        executor.execute("add_date", {"title": "standup"})
        processor.add_date.assert_called_once_with(["standup"])

    def test_execute_add_date_full(
        self, executor: CommandExecutor, processor: MagicMock,
    ) -> None:
        """Verify add_date with all parameters."""
        executor.execute("add_date", {
            "title": "standup",
            "date": "tomorrow",
            "start_time": "14:00",
            "end_time": "15:00",
            "calendar": "work",
        })
        processor.add_date.assert_called_once_with(
            ["standup", "tomorrow", "14:00-15:00", "@work"],
        )

    def test_execute_add_date_start_only(
        self, executor: CommandExecutor, processor: MagicMock,
    ) -> None:
        """Verify add_date with start_time but no end_time."""
        executor.execute("add_date", {
            "title": "lunch",
            "start_time": "12:00",
        })
        processor.add_date.assert_called_once_with(["lunch", "12:00"])

    def test_execute_add_todo_minimal(
        self, executor: CommandExecutor, processor: MagicMock,
    ) -> None:
        """Verify add_todo with title only uses defaults (priority=3, due_date=today)."""
        executor.execute("add_todo", {"title": "Buy milk"})
        processor.add_todo.assert_called_once_with(
            title="Buy milk", priority=3, due_date="today", due_time="",
        )

    def test_execute_add_todo_full(
        self, executor: CommandExecutor, processor: MagicMock,
    ) -> None:
        """Verify add_todo passes all parameters correctly."""
        executor.execute("add_todo", {
            "title": "Buy milk",
            "priority": 2,
            "due_date": "tomorrow",
        })
        processor.add_todo.assert_called_once_with(
            title="Buy milk", priority=2, due_date="tomorrow", due_time="",
        )

    def test_execute_add_todo_with_time(
        self, executor: CommandExecutor, processor: MagicMock,
    ) -> None:
        """Verify add_todo passes due_time through to processor."""
        executor.execute("add_todo", {
            "title": "Morning jog",
            "priority": 1,
            "due_date": "tomorrow",
            "due_time": "08:00",
        })
        processor.add_todo.assert_called_once_with(
            title="Morning jog", priority=1, due_date="tomorrow", due_time="08:00",
        )

    def test_execute_meetings(
        self, executor: CommandExecutor, processor: MagicMock,
    ) -> None:
        """Verify meetings passes date_str to processor."""
        executor.execute("meetings", {"date_str": "tomorrow"})
        processor.meetings.assert_called_once_with(date_str="tomorrow")

    def test_execute_meeting_detail(
        self, executor: CommandExecutor, processor: MagicMock,
    ) -> None:
        """Verify meeting_detail passes index as int to processor."""
        executor.execute("meeting_detail", {"index": 2})
        processor.todays_meeting_detail.assert_called_once_with(index=2)

    def test_execute_list_workflows(
        self, executor: CommandExecutor, processor: MagicMock,
    ) -> None:
        """Verify list_workflows is called without parameters."""
        executor.execute("list_workflows", {})
        processor.list_workflows.assert_called_once()

    def test_execute_run_workflow(
        self, executor: CommandExecutor, processor: MagicMock,
    ) -> None:
        """Verify run_workflow passes name to processor."""
        executor.execute("run_workflow", {"name": "daily_report"})
        processor.run_workflow.assert_called_once_with(name="daily_report")

    def test_execute_update_search_cache_default(
        self, executor: CommandExecutor, processor: MagicMock,
    ) -> None:
        """Verify update_search_cache defaults to folders=None, fast=False."""
        executor.execute("update_search_cache", {})
        processor.update_search_cache.assert_called_once_with(
            folders=None, fast=False,
        )

    def test_execute_exit_raises_exit_chat_error(
        self, executor: CommandExecutor,
    ) -> None:
        """Verify exit command raises ExitChatError."""
        with pytest.raises(ExitChatError):
            executor.execute("exit", {})

    def test_execute_unknown_command(self, executor: CommandExecutor) -> None:
        """Verify unknown commands raise ValueError."""
        with pytest.raises(ValueError, match="Unknown command"):
            executor.execute("nonexistent", {})


# ---------------------------------------------------------------------------
# ChatHandler tests
# ---------------------------------------------------------------------------

class TestChatHandler:
    """Tests for ChatHandler."""

    def test_phase1_detect_intent_success(
        self, handler: ChatHandler, openai_client: MagicMock,
    ) -> None:
        """Verify Phase 1 parses a valid intent response."""
        intent_json = json.dumps({
            "command": "todays_meetings",
            "parameters": {},
            "follow_up_question": None,
            "summary": "List today's meetings",
        })
        openai_client.ai_chat_detect_intent.return_value = intent_json

        handler._initialize_session()
        handler._session.add_message("user", "show my meetings today")
        intent = handler._phase1_detect_intent()

        assert intent is not None
        assert intent.command_name == "todays_meetings"
        assert intent.follow_up_question is None

    def test_phase1_detect_intent_follow_up(
        self, handler: ChatHandler, openai_client: MagicMock,
    ) -> None:
        """Verify Phase 1 returns follow-up question when command is missing."""
        intent_json = json.dumps({
            "command": None,
            "parameters": {},
            "follow_up_question": "What would you like to search for?",
            "summary": "",
        })
        openai_client.ai_chat_detect_intent.return_value = intent_json

        handler._initialize_session()
        handler._session.add_message("user", "search")
        intent = handler._phase1_detect_intent()

        assert intent is not None
        assert intent.command_name is None
        assert intent.follow_up_question == "What would you like to search for?"

    def test_phase1_detect_intent_api_failure(
        self, handler: ChatHandler, openai_client: MagicMock,
    ) -> None:
        """Verify Phase 1 returns None on API failure."""
        openai_client.ai_chat_detect_intent.return_value = None

        handler._initialize_session()
        handler._session.add_message("user", "hello")
        intent = handler._phase1_detect_intent()

        assert intent is None

    def test_phase2_validate_parameters(
        self, handler: ChatHandler, openai_client: MagicMock,
    ) -> None:
        """Verify Phase 2 returns a ValidatedCommand."""
        openai_client.ai_chat_validate_parameters.return_value = {
            "name": "add_date",
            "arguments": {"title": "standup", "date": "06.03.2026"},
        }

        intent = DetectedIntent(
            command_name="add_date",
            parameters={"title": "standup", "date": "06.03.2026"},
            follow_up_question=None,
            summary="Create standup event",
        )
        validated = handler._phase2_validate_parameters(intent)

        assert validated is not None
        assert validated.command_name == "add_date"
        assert validated.parameters["title"] == "standup"

    def test_phase2_unknown_command(
        self, handler: ChatHandler,
    ) -> None:
        """Verify Phase 2 returns None for unknown commands."""
        intent = DetectedIntent(
            command_name="nonexistent",
            parameters={},
            follow_up_question=None,
            summary="",
        )
        validated = handler._phase2_validate_parameters(intent)
        assert validated is None

    @patch("src.ai.chat_handler.scheduler_choose")
    def test_confirm_or_edit_execute(
        self,
        mock_choose: MagicMock,
        handler: ChatHandler,
    ) -> None:
        """Verify 'execute' is returned when user selects Execute."""
        mock_choose.return_value = 0
        command = ValidatedCommand(
            command_name="todays_meetings",
            parameters={},
            summary="List meetings",
        )
        assert handler._confirm_or_edit(command) == "execute"

    @patch("src.ai.chat_handler.scheduler_choose")
    def test_confirm_or_edit_change(
        self,
        mock_choose: MagicMock,
        handler: ChatHandler,
    ) -> None:
        """Verify 'change' is returned when user selects Change."""
        mock_choose.return_value = 1
        command = ValidatedCommand(
            command_name="todays_meetings",
            parameters={},
            summary="List meetings",
        )
        assert handler._confirm_or_edit(command) == "change"

    @patch("src.ai.chat_handler.scheduler_choose")
    def test_confirm_or_edit_cancel(
        self,
        mock_choose: MagicMock,
        handler: ChatHandler,
    ) -> None:
        """Verify 'cancel' is returned when user selects Cancel."""
        mock_choose.return_value = 2
        command = ValidatedCommand(
            command_name="todays_meetings",
            parameters={},
            summary="List meetings",
        )
        assert handler._confirm_or_edit(command) == "cancel"

    @patch("src.ai.chat_handler.scheduler_choose")
    def test_confirm_or_edit_abort(
        self,
        mock_choose: MagicMock,
        handler: ChatHandler,
    ) -> None:
        """Verify 'cancel' on SchedulerAbortError."""
        mock_choose.side_effect = SchedulerAbortError("timeout")
        command = ValidatedCommand(
            command_name="todays_meetings",
            parameters={},
            summary="List meetings",
        )
        assert handler._confirm_or_edit(command) == "cancel"

    @patch("src.ai.chat_handler.stop_output_capture", return_value="")
    @patch("src.ai.chat_handler.start_output_capture")
    @patch("src.ai.chat_handler.send_output")
    def test_execute_command_success(
        self,
        mock_output: MagicMock,
        mock_start: MagicMock,
        mock_stop: MagicMock,
        handler: ChatHandler,
        processor: MagicMock,
    ) -> None:
        """Verify successful command execution uses silent capture API."""
        command = ValidatedCommand(
            command_name="todays_meetings",
            parameters={},
            summary="List meetings",
        )
        handler._execute_command(command)
        processor.todays_meetings.assert_called_once()
        mock_start.assert_called_once_with(silent=True)
        mock_stop.assert_called_once()

    @patch("src.ai.chat_handler.stop_output_capture", return_value="")
    @patch("src.ai.chat_handler.start_output_capture")
    @patch("src.ai.chat_handler.send_output")
    def test_history_preserved_after_execution(
        self,
        mock_output: MagicMock,
        mock_start: MagicMock,
        mock_stop: MagicMock,
        handler: ChatHandler,
        processor: MagicMock,
    ) -> None:
        """Verify assistant result message is added to session history."""
        handler._initialize_session()
        handler._session.add_message("user", "show meetings")
        command = ValidatedCommand(
            command_name="todays_meetings",
            parameters={},
            summary="List meetings",
        )
        handler._execute_command(command)
        # History should contain system + user + assistant result
        roles = [m.role for m in handler._session.history]
        assert "assistant" in roles
        last_asst = [m for m in handler._session.history if m.role == "assistant"][-1]
        assert "todays_meetings" in last_asst.content

    @patch("src.ai.chat_handler.stop_output_capture", return_value="")
    @patch("src.ai.chat_handler.start_output_capture")
    @patch("src.ai.chat_handler.send_output")
    def test_execute_command_failure(
        self,
        mock_output: MagicMock,
        mock_start: MagicMock,
        mock_stop: MagicMock,
        handler: ChatHandler,
        processor: MagicMock,
    ) -> None:
        """Verify failed command execution is handled gracefully."""
        processor.todays_meetings.side_effect = RuntimeError("connection failed")
        command = ValidatedCommand(
            command_name="todays_meetings",
            parameters={},
            summary="List meetings",
        )
        handler._execute_command(command)
        # Should not raise, should output error
        assert any(
            "failed" in str(call).lower() for call in mock_output.call_args_list
        )
        mock_start.assert_called_once()
        mock_stop.assert_called_once()

    @patch("src.ai.chat_handler.stop_output_capture", return_value="Unrecognised argument: xyz")
    @patch("src.ai.chat_handler.start_output_capture")
    @patch("src.ai.chat_handler.send_output")
    def test_execute_command_error_keyword_logged(
        self,
        mock_output: MagicMock,
        mock_start: MagicMock,
        mock_stop: MagicMock,
        handler: ChatHandler,
        processor: MagicMock,
    ) -> None:
        """Verify error keywords in captured output trigger error logging."""
        command = ValidatedCommand(
            command_name="add_date",
            parameters={"title": "test"},
            summary="Add date",
        )
        handler._execute_command(command)
        # The error logger should have been called due to 'unrecognised' keyword
        assert handler._error_logger.log_path.exists()

    @patch("src.ai.chat_handler.scheduler_ask")
    @patch("src.ai.chat_handler.send_output")
    def test_run_quit(
        self,
        mock_output: MagicMock,
        mock_ask: MagicMock,
        handler: ChatHandler,
    ) -> None:
        """Verify 'quit' exits the loop."""
        mock_ask.return_value = "quit"
        handler.run()
        assert any(
            "goodbye" in str(call).lower() for call in mock_output.call_args_list
        )

    @patch("src.ai.chat_handler.is_interactive", return_value=True)
    @patch("src.ai.chat_handler.scheduler_ask")
    @patch("src.ai.chat_handler.send_output")
    def test_run_empty_input_exits_under_scheduler(
        self,
        mock_output: MagicMock,
        mock_ask: MagicMock,
        mock_interactive: MagicMock,
        handler: ChatHandler,
    ) -> None:
        """Verify empty input exits the loop when running under scheduler."""
        mock_ask.return_value = ""
        handler.run()
        assert any(
            "goodbye" in str(call).lower() for call in mock_output.call_args_list
        )

    @patch("src.ai.chat_handler.scheduler_ask")
    @patch("src.ai.chat_handler.send_output")
    def test_clear_command_resets_history(
        self,
        mock_output: MagicMock,
        mock_ask: MagicMock,
        handler: ChatHandler,
    ) -> None:
        """Verify 'clear' resets history and re-initializes session."""
        mock_ask.side_effect = ["clear", "quit"]
        handler.run()
        assert any(
            "history cleared" in str(call).lower()
            for call in mock_output.call_args_list
        )

    @patch("src.ai.chat_handler.scheduler_ask")
    @patch("src.ai.chat_handler.send_output")
    def test_run_scheduler_abort_exits(
        self,
        mock_output: MagicMock,
        mock_ask: MagicMock,
        handler: ChatHandler,
    ) -> None:
        """Verify SchedulerAbortError exits the loop gracefully."""
        mock_ask.side_effect = SchedulerAbortError("timeout")
        handler.run()
        assert any(
            "goodbye" in str(call).lower() for call in mock_output.call_args_list
        )

    @patch("src.ai.chat_handler.stop_output_capture", return_value="")
    @patch("src.ai.chat_handler.start_output_capture")
    @patch("src.ai.chat_handler.send_output")
    def test_execute_command_exit_returns_true(
        self,
        mock_output: MagicMock,
        mock_start: MagicMock,
        mock_stop: MagicMock,
        handler: ChatHandler,
    ) -> None:
        """Verify _execute_command returns True on ExitChatError."""
        command = ValidatedCommand(
            command_name="exit",
            parameters={},
            summary="User wants to exit",
        )
        result = handler._execute_command(command)
        assert result is True
        assert any(
            "goodbye" in str(call).lower() for call in mock_output.call_args_list
        )

    @patch("src.ai.chat_handler.scheduler_ask")
    @patch("src.ai.chat_handler.send_output")
    def test_run_exits_when_ai_detects_exit_intent(
        self,
        mock_output: MagicMock,
        mock_ask: MagicMock,
        handler: ChatHandler,
        openai_client: MagicMock,
    ) -> None:
        """Verify run loop terminates when AI returns exit command."""
        # Phase 1: AI detects exit intent
        intent_json = json.dumps({
            "command": "exit",
            "parameters": {},
            "follow_up_question": None,
            "summary": "User wants to leave",
        })
        openai_client.ai_chat_detect_intent.return_value = intent_json

        # Phase 2: function calling validates exit command
        openai_client.ai_chat_validate_parameters.return_value = {
            "name": "exit",
            "arguments": {},
        }

        mock_ask.return_value = "I'm done, thanks"
        handler.run()
        assert any(
            "goodbye" in str(call).lower() for call in mock_output.call_args_list
        )


# ---------------------------------------------------------------------------
# Log suppression during command execution tests
# ---------------------------------------------------------------------------

class TestLogSuppression:
    """Tests for INFO log suppression during command execution."""

    @patch("src.ai.chat_handler.stop_output_capture", return_value="some output")
    @patch("src.ai.chat_handler.start_output_capture")
    @patch("src.ai.chat_handler.send_output")
    def test_execute_command_suppresses_info_logs(
        self,
        mock_output: MagicMock,
        mock_start: MagicMock,
        mock_stop: MagicMock,
        handler: ChatHandler,
        openai_client: MagicMock,
        processor: MagicMock,
    ) -> None:
        """Verify root logger level is raised to WARNING during command execution."""
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        captured_level: int | None = None

        def capture_level() -> None:
            nonlocal captured_level
            captured_level = root_logger.level

        processor.todays_meetings.side_effect = capture_level
        openai_client.ai_chat_interpret_output.return_value = "interpreted"

        command = ValidatedCommand(
            command_name="todays_meetings",
            parameters={},
            summary="List meetings",
        )
        handler._execute_command(command, "show meetings")

        assert captured_level == logging.WARNING
        assert root_logger.level == logging.INFO

    @patch("src.ai.chat_handler.stop_output_capture", return_value="")
    @patch("src.ai.chat_handler.start_output_capture")
    @patch("src.ai.chat_handler.send_output")
    def test_execute_command_restores_log_level_on_error(
        self,
        mock_output: MagicMock,
        mock_start: MagicMock,
        mock_stop: MagicMock,
        handler: ChatHandler,
        processor: MagicMock,
    ) -> None:
        """Verify root log level is restored even when command raises."""
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        processor.todays_meetings.side_effect = RuntimeError("boom")

        command = ValidatedCommand(
            command_name="todays_meetings",
            parameters={},
            summary="List meetings",
        )
        handler._execute_command(command)

        assert root_logger.level == logging.INFO


# ---------------------------------------------------------------------------
# _build_calendar_list tests
# ---------------------------------------------------------------------------

class TestBuildCalendarList:
    """Tests for ChatHandler._build_calendar_list()."""

    def test_with_cached_calendars_marks_default(
        self, handler: ChatHandler,
    ) -> None:
        """Verify cached calendars are formatted with default marker."""
        result = handler._build_calendar_list()
        assert "- Termine (default for add_date)" in result
        assert "- Privat" in result
        assert "- XD Mitarbeiter" in result

    def test_fallback_when_no_cached_calendars(
        self, openai_client: MagicMock, registry: CommandRegistry,
        executor: CommandExecutor,
    ) -> None:
        """Verify fallback to default calendar name when cache is empty."""
        cfg = MagicMock(spec=ConfigManager)
        cfg.cached_calendars = []
        cfg.add_date_calendar_name = "MyDefault"
        h = ChatHandler(openai_client, registry, executor, config=cfg)
        result = h._build_calendar_list()
        assert result == "- MyDefault (default for add_date)"

    def test_empty_when_no_config(
        self, openai_client: MagicMock, registry: CommandRegistry,
        executor: CommandExecutor,
    ) -> None:
        """Verify empty string when no config is provided."""
        h = ChatHandler(openai_client, registry, executor)
        result = h._build_calendar_list()
        assert result == ""

    def test_empty_when_no_calendars_and_no_default(
        self, openai_client: MagicMock, registry: CommandRegistry,
        executor: CommandExecutor,
    ) -> None:
        """Verify empty string when cache is empty and no default name."""
        cfg = MagicMock(spec=ConfigManager)
        cfg.cached_calendars = []
        cfg.add_date_calendar_name = ""
        h = ChatHandler(openai_client, registry, executor, config=cfg)
        result = h._build_calendar_list()
        assert result == ""


# ---------------------------------------------------------------------------
# Output capture tests
# ---------------------------------------------------------------------------

class TestOutputCapture:
    """Tests for start_output_capture / stop_output_capture."""

    def test_capture_collects_send_output(self) -> None:
        """Verify send_output calls are captured between start/stop."""
        from src.interaction.scheduler_prompts import (
            send_output as _send,
        )
        from src.interaction.scheduler_prompts import (
            start_output_capture,
            stop_output_capture,
        )

        start_output_capture()
        _send("hello")
        _send("world")
        result = stop_output_capture()
        assert result == "hello\nworld"

    def test_capture_returns_empty_when_no_output(self) -> None:
        """Verify stop returns empty string when nothing was sent."""
        from src.interaction.scheduler_prompts import (
            start_output_capture,
            stop_output_capture,
        )

        start_output_capture()
        result = stop_output_capture()
        assert result == ""

    def test_no_capture_when_not_started(self) -> None:
        """Verify send_output works normally without capture active."""
        from src.interaction.scheduler_prompts import (
            send_output as _send,
        )
        from src.interaction.scheduler_prompts import (
            stop_output_capture,
        )

        # Should not raise even though capture was never started
        _send("no-op")
        result = stop_output_capture()
        assert result == ""

    def test_silent_capture_suppresses_print(self) -> None:
        """Verify silent capture captures text without printing."""
        from src.interaction.scheduler_prompts import (
            send_output as _send,
        )
        from src.interaction.scheduler_prompts import (
            start_output_capture,
            stop_output_capture,
        )

        with (
            patch("src.interaction.scheduler_prompts.is_interactive", return_value=False),
            patch("builtins.print") as mock_print,
        ):
            start_output_capture(silent=True)
            _send("hidden message")
            result = stop_output_capture()

        assert result == "hidden message"
        mock_print.assert_not_called()

    def test_non_silent_capture_still_prints(self) -> None:
        """Verify non-silent capture captures text AND prints."""
        from src.interaction.scheduler_prompts import (
            send_output as _send,
        )
        from src.interaction.scheduler_prompts import (
            start_output_capture,
            stop_output_capture,
        )

        with (
            patch("src.interaction.scheduler_prompts.is_interactive", return_value=False),
            patch("builtins.print") as mock_print,
        ):
            start_output_capture(silent=False)
            _send("visible message")
            result = stop_output_capture()

        assert result == "visible message"
        mock_print.assert_called_once_with("visible message")


# ---------------------------------------------------------------------------
# Phase 3: Interpret output tests
# ---------------------------------------------------------------------------

class TestPhase3InterpretOutput:
    """Tests for Phase 3 output interpretation in ChatHandler."""

    @patch("src.ai.chat_handler.stop_output_capture", return_value="Meeting 1: 08:00 Standup\nMeeting 2: 14:00 Review")
    @patch("src.ai.chat_handler.start_output_capture")
    @patch("src.ai.chat_handler.send_output")
    def test_phase3_calls_interpret_when_output_exists(
        self,
        mock_output: MagicMock,
        mock_start: MagicMock,
        mock_stop: MagicMock,
        handler: ChatHandler,
        openai_client: MagicMock,
        processor: MagicMock,
    ) -> None:
        """Verify Phase 3 calls ai_chat_interpret_output when there is captured output."""
        openai_client.ai_chat_interpret_output.return_value = "You have 2 meetings today."
        command = ValidatedCommand(
            command_name="todays_meetings",
            parameters={},
            summary="List meetings",
        )
        handler._execute_command(command, "what meetings do I have today")
        openai_client.ai_chat_interpret_output.assert_called_once_with(
            user_question="what meetings do I have today",
            command_output="Meeting 1: 08:00 Standup\nMeeting 2: 14:00 Review",
        )
        # The interpretation should be shown to the user
        assert any(
            "You have 2 meetings today" in str(call)
            for call in mock_output.call_args_list
        )

    @patch("src.ai.chat_handler.stop_output_capture", return_value="")
    @patch("src.ai.chat_handler.start_output_capture")
    @patch("src.ai.chat_handler.send_output")
    def test_phase3_skipped_when_output_empty(
        self,
        mock_output: MagicMock,
        mock_start: MagicMock,
        mock_stop: MagicMock,
        handler: ChatHandler,
        openai_client: MagicMock,
        processor: MagicMock,
    ) -> None:
        """Verify Phase 3 is skipped when captured output is empty."""
        command = ValidatedCommand(
            command_name="todays_meetings",
            parameters={},
            summary="List meetings",
        )
        handler._execute_command(command, "show meetings")
        openai_client.ai_chat_interpret_output.assert_not_called()
        # Should show fallback "Done!" message
        assert any(
            "Done!" in str(call)
            for call in mock_output.call_args_list
        )

    @patch("src.ai.chat_handler.stop_output_capture", return_value="Meeting 1: 08:00 Standup")
    @patch("src.ai.chat_handler.start_output_capture")
    @patch("src.ai.chat_handler.send_output")
    def test_phase3_skipped_when_no_original_question(
        self,
        mock_output: MagicMock,
        mock_start: MagicMock,
        mock_stop: MagicMock,
        handler: ChatHandler,
        openai_client: MagicMock,
        processor: MagicMock,
    ) -> None:
        """Verify Phase 3 is skipped when no original_question is provided."""
        command = ValidatedCommand(
            command_name="todays_meetings",
            parameters={},
            summary="List meetings",
        )
        handler._execute_command(command)
        openai_client.ai_chat_interpret_output.assert_not_called()
        # Raw output should be shown as fallback
        assert any(
            "Meeting 1: 08:00 Standup" in str(call)
            for call in mock_output.call_args_list
        )

    @patch("src.ai.chat_handler.stop_output_capture", return_value="Meeting 1: 08:00 Standup")
    @patch("src.ai.chat_handler.start_output_capture")
    @patch("src.ai.chat_handler.send_output")
    def test_phase3_fallback_on_interpretation_failure(
        self,
        mock_output: MagicMock,
        mock_start: MagicMock,
        mock_stop: MagicMock,
        handler: ChatHandler,
        openai_client: MagicMock,
        processor: MagicMock,
    ) -> None:
        """Verify fallback to raw output when interpretation returns None."""
        openai_client.ai_chat_interpret_output.return_value = None
        command = ValidatedCommand(
            command_name="todays_meetings",
            parameters={},
            summary="List meetings",
        )
        handler._execute_command(command, "show meetings")
        # Should fall back to raw output + Done!
        assert any(
            "Meeting 1: 08:00 Standup" in str(call)
            for call in mock_output.call_args_list
        )
        assert any(
            "Done!" in str(call)
            for call in mock_output.call_args_list
        )

    @patch("src.ai.chat_handler.stop_output_capture", return_value="Meeting 1: 08:00 Standup")
    @patch("src.ai.chat_handler.start_output_capture")
    @patch("src.ai.chat_handler.send_output")
    def test_phase3_interpretation_added_to_history(
        self,
        mock_output: MagicMock,
        mock_start: MagicMock,
        mock_stop: MagicMock,
        handler: ChatHandler,
        openai_client: MagicMock,
        processor: MagicMock,
    ) -> None:
        """Verify interpretation is added to conversation history."""
        openai_client.ai_chat_interpret_output.return_value = "You have 1 meeting."
        handler._initialize_session()
        handler._session.add_message("user", "what meetings")
        command = ValidatedCommand(
            command_name="todays_meetings",
            parameters={},
            summary="List meetings",
        )
        handler._execute_command(command, "what meetings")
        assistant_msgs = [m for m in handler._session.history if m.role == "assistant"]
        # Should have both the result summary and the interpretation
        assert len(assistant_msgs) >= 2
        assert any("You have 1 meeting." in m.content for m in assistant_msgs)


# ---------------------------------------------------------------------------
# ChatConversationLogger tests
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Guard test: no AI command may call interactive functions
# ---------------------------------------------------------------------------

# Commands that are inherently interactive or special — excluded from the guard
_INTERACTIVE_COMMANDS = {"exit", "inbox_zero"}

# Minimal dummy values by param type for auto-generating valid params
_DUMMY_VALUES: dict[str, object] = {"string": "test", "integer": 1, "boolean": False}


class TestAiCommandsNonInteractive:
    """Guard test ensuring AI commands never call interactive functions."""

    def test_ai_commands_are_non_interactive(
        self,
        registry: CommandRegistry,
        executor: CommandExecutor,
        processor: MagicMock,
    ) -> None:
        """Every AI command (except explicitly interactive ones) must not call input/ask/choose."""
        for cmd in registry.all_commands():
            if cmd.name in _INTERACTIVE_COMMANDS:
                continue
            # Build minimal params from CommandDefinition.parameters
            params: dict[str, object] = {}
            for p in cmd.parameters:
                if p.required:
                    params[p.name] = _DUMMY_VALUES.get(p.param_type, "test")
            with (
                patch("builtins.input", side_effect=AssertionError(f"{cmd.name} called input()")),
                patch("src.ai.chat_handler.scheduler_ask", side_effect=AssertionError(f"{cmd.name} called scheduler_ask")),
                patch("src.ai.chat_handler.scheduler_choose", side_effect=AssertionError(f"{cmd.name} called scheduler_choose")),
            ):
                executor.execute(cmd.name, params)  # should NOT trigger any interactive call


# ---------------------------------------------------------------------------
# ChatConversationLogger tests
# ---------------------------------------------------------------------------

class TestChatConversationLogger:
    """Tests for ChatConversationLogger."""

    def test_creates_log_file_with_correct_name(self, tmp_path: Path) -> None:
        """First session of the day produces _01 suffix."""
        from src.logging.chat_conversation_logger import ChatConversationLogger

        conv_logger = ChatConversationLogger(str(tmp_path))
        today = date.today().strftime("%Y%m%d")
        assert conv_logger.log_path.name == f"{today}_chat_01.log"

    def test_increments_sequence_number(self, tmp_path: Path) -> None:
        """Second session of the day produces _02 suffix."""
        from src.logging.chat_conversation_logger import ChatConversationLogger

        today = date.today().strftime("%Y%m%d")
        (tmp_path / f"{today}_chat_01.log").touch()

        conv_logger = ChatConversationLogger(str(tmp_path))
        assert conv_logger.log_path.name == f"{today}_chat_02.log"

    def test_log_writes_timestamped_entry(self, tmp_path: Path) -> None:
        """log() writes a timestamped step entry."""
        from src.logging.chat_conversation_logger import ChatConversationLogger

        conv_logger = ChatConversationLogger(str(tmp_path))
        conv_logger.log("USER", "show my meetings")

        content = conv_logger.log_path.read_text(encoding="utf-8").strip()
        assert "USER: show my meetings" in content
        assert content.startswith("[")  # starts with timestamp

    def test_log_multiple_steps(self, tmp_path: Path) -> None:
        """Multiple log calls produce multiple lines."""
        from src.logging.chat_conversation_logger import ChatConversationLogger

        conv_logger = ChatConversationLogger(str(tmp_path))
        conv_logger.log("USER", "hello")
        conv_logger.log("PHASE1_INTENT", '{"command": "todays_meetings"}')
        conv_logger.log("COMMAND_OUTPUT", "Meeting 1")

        lines = conv_logger.log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3
        assert "USER: hello" in lines[0]
        assert "PHASE1_INTENT:" in lines[1]
        assert "COMMAND_OUTPUT: Meeting 1" in lines[2]
