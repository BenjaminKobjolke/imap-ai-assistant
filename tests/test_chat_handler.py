"""Tests for ChatHandler, ChatSession, and CommandExecutor."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.ai.chat_handler import (
    ChatHandler,
    ChatSession,
    CommandExecutor,
    DetectedIntent,
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
        """Verify todays_meetings is called without parameters."""
        executor.execute("todays_meetings", {})
        processor.todays_meetings.assert_called_once()

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
        """Verify successful command execution uses capture API."""
        command = ValidatedCommand(
            command_name="todays_meetings",
            parameters={},
            summary="List meetings",
        )
        handler._execute_command(command)
        processor.todays_meetings.assert_called_once()
        mock_start.assert_called_once()
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
