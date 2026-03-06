"""Conversational AI mode: terminal loop with two-phase intent detection."""

from __future__ import annotations

import json
import logging
import traceback as tb_mod
from dataclasses import dataclass, field
from typing import Any

from src.ai.ai_command import Param, ai_command
from src.ai.command_registry import CommandRegistry
from src.ai.openai_client import OpenAIClient
from src.config.settings import ConfigManager
from src.interaction.scheduler_prompts import (
    SchedulerAbortError,
    is_interactive,
    scheduler_ask,
    scheduler_choose,
    send_output,
    start_output_capture,
    stop_output_capture,
)
from src.logging.app_logger import ApplicationLogger
from src.logging.chat_error_logger import ChatErrorLogger

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ConversationMessage:
    """A single message in the conversation history."""

    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class DetectedIntent:
    """Result of Phase 1: intent detection."""

    command_name: str | None
    parameters: dict[str, Any]
    follow_up_question: str | None
    summary: str


@dataclass
class ValidatedCommand:
    """The final validated command ready for execution."""

    command_name: str
    parameters: dict[str, Any]
    summary: str


@dataclass
class ChatSession:
    """Maintains state across the conversation loop."""

    history: list[ConversationMessage] = field(default_factory=list)
    max_history: int = 100

    def add_message(self, role: str, content: str) -> None:
        """Append a message to conversation history."""
        self.history.append(ConversationMessage(role=role, content=content))
        self._trim()

    def to_openai_messages(self) -> list[dict[str, str]]:
        """Convert history to OpenAI message format."""
        return [{"role": m.role, "content": m.content} for m in self.history]

    def clear_for_new_request(self) -> None:
        """Keep system prompt, clear user/assistant turns for fresh request."""
        self.history = [m for m in self.history if m.role == "system"]

    def _trim(self) -> None:
        """Drop oldest non-system messages when history exceeds max_history."""
        if len(self.history) <= self.max_history:
            return
        system = [m for m in self.history if m.role == "system"]
        non_system = [m for m in self.history if m.role != "system"]
        keep = non_system[-(self.max_history - len(system)):]
        self.history = system + keep


# ---------------------------------------------------------------------------
# Command executor
# ---------------------------------------------------------------------------

class CommandExecutor:
    """Bridges validated AI commands to EmailProcessor methods."""

    def __init__(self, processor: Any) -> None:
        self._processor = processor
        self._handlers: dict[str, Any] = {}

    def bind_to_registry(self, registry: CommandRegistry) -> None:
        """Let the registry discover @ai_command methods and build dispatch."""
        self._handlers = registry.register_from_executor(self)

    def execute(self, command_name: str, params: dict[str, Any]) -> None:
        """Execute a command by name with the given parameters."""
        handler = self._handlers.get(command_name)
        if handler is None:
            raise ValueError(f"Unknown command: {command_name}")
        handler(params)

    @ai_command(
        name="add_date",
        description="Create a Google Calendar event",
        params=[
            Param("title", "Title/name of the event", "string", required=True),
            Param("date", "Date for the event (DD.MM.YYYY, 'today', 'tomorrow')", "string"),
            Param("start_time", "Start time in HH:MM format (e.g. 14:00)", "string"),
            Param("end_time", "End time in HH:MM format (e.g. 15:00)", "string"),
            Param("calendar", "Calendar name or ID to create the event in", "string"),
        ],
    )
    def add_date(self, params: dict[str, Any]) -> None:
        """Translate AI parameters into the add_date CLI format."""
        raw_args: list[str] = [params["title"]]
        if params.get("date"):
            raw_args.append(str(params["date"]))
        if params.get("start_time"):
            start = str(params["start_time"])
            end = str(params.get("end_time", ""))
            if end:
                raw_args.append(f"{start}-{end}")
            else:
                raw_args.append(start)
        if params.get("calendar"):
            raw_args.append(f"@{params['calendar']}")
        self._processor.add_date(raw_args)

    @ai_command(
        name="inbox_zero",
        description="Process inbox emails interactively one by one to achieve inbox zero",
        params=[
            Param("unread_only", "Only process unread emails", "boolean"),
        ],
    )
    def inbox_zero(self, params: dict[str, Any]) -> None:
        """Execute inbox-zero with optional unread_only flag."""
        unread_only = bool(params.get("unread_only", False))
        self._processor.inbox_zero(unread_only=unread_only)

    @ai_command(
        name="search",
        description="Search emails by term with optional filters",
        params=[
            Param("search_term", "The search term or query", "string", required=True),
            Param("body_term", "Additional body text filter", "string"),
            Param("date", "Exact date filter (DD.MM.YYYY)", "string"),
            Param("date_after", "Only emails after this date (DD.MM.YYYY)", "string"),
            Param("date_before", "Only emails before this date (DD.MM.YYYY)", "string"),
            Param("path", "Specific IMAP folder to search in", "string"),
        ],
    )
    def search(self, params: dict[str, Any]) -> None:
        """Execute email search with optional filters."""
        self._processor.search_emails(
            search_term=params["search_term"],
            body_term=params.get("body_term"),
            date=params.get("date"),
            date_after=params.get("date_after"),
            date_before=params.get("date_before"),
            path=params.get("path"),
        )

    @ai_command(
        name="add_todo",
        description="Create a Remember the Milk todo task",
        params=[
            Param("title", "Title/name of the todo task", "string", required=True),
            Param("priority", "Priority: 1 (very important), 2 (important), 3 (not so important)", "integer"),
            Param("due_date", "Due date: 'today', 'tomorrow', or DD.MM.YYYY format", "string"),
            Param("due_time", "Due time in HH:MM format (e.g. '08:00', '14:30')", "string"),
        ],
    )
    def add_todo(self, params: dict[str, Any]) -> None:
        """Create an RTM todo with the given parameters."""
        self._processor.add_todo(
            title=params["title"],
            priority=int(params.get("priority", 3)),
            due_date=str(params.get("due_date", "today")),
            due_time=str(params.get("due_time") or ""),
        )

    @ai_command(
        name="todays_meetings",
        description="List today's meetings with start and end times",
    )
    def todays_meetings(self, params: dict[str, Any]) -> None:
        """Execute today's meetings listing."""
        self._processor.todays_meetings()


# ---------------------------------------------------------------------------
# Main chat handler
# ---------------------------------------------------------------------------

class ChatHandler:
    """Orchestrates the --ai conversational CLI mode."""

    def __init__(
        self,
        openai_client: OpenAIClient,
        registry: CommandRegistry,
        executor: CommandExecutor,
        app_logger: ApplicationLogger | None = None,
        config: ConfigManager | None = None,
    ) -> None:
        self._openai = openai_client
        self._registry = registry
        self._executor = executor
        self._app_logger = app_logger
        self._config = config
        max_hist = config.chat_max_history if config else 100
        self._session = ChatSession(max_history=max_hist)
        log_dir = config.log_dir if config else "logs"
        self._error_logger = ChatErrorLogger(log_dir)

    def run(self, initial_message: str | None = None) -> None:
        """Main conversational loop."""
        self._print_welcome()
        self._initialize_session()

        first_input = initial_message

        while True:
            if first_input is not None:
                user_input = first_input
                first_input = None
                send_output(f"You: {user_input}")
            else:
                try:
                    user_input = scheduler_ask("You", default="").strip()
                except (SchedulerAbortError, EOFError, KeyboardInterrupt):
                    send_output("\nGoodbye!")
                    break

                if not user_input:
                    if is_interactive():
                        send_output("\nGoodbye!")
                        break
                    continue

                if user_input.lower() in {"exit", "quit", "q"}:
                    send_output("Goodbye!")
                    break

                if user_input.lower() in {"clear", "reset"}:
                    self._session.clear_for_new_request()
                    self._initialize_session()
                    send_output("AI: History cleared. What can I do for you?")
                    continue

            self._handle_user_input(user_input)

    def _print_welcome(self) -> None:
        """Display welcome banner."""
        send_output("")
        send_output("=" * 50)
        send_output("  IMAP AI Assistant - Conversational Mode")
        send_output("=" * 50)
        send_output("Describe what you want to do in natural language.")
        send_output("Type 'exit' or 'quit' to leave. Type 'clear' to reset context.")
        send_output("")
        available = ", ".join(cmd.name for cmd in self._registry.all_commands())
        send_output(f"Available commands: {available}")
        send_output("")

    def _initialize_session(self) -> None:
        """Set up the system prompt in the conversation."""
        calendars_text = self._build_calendar_list()
        system_prompt = self._openai.build_ai_chat_system_prompt(
            self._registry.all_descriptions(),
            calendars=calendars_text,
        )
        self._session.add_message("system", system_prompt)

    def _build_calendar_list(self) -> str:
        """Build a formatted calendar list for the system prompt."""
        if self._config is None:
            return ""

        cached = self._config.cached_calendars
        default_name = self._config.add_date_calendar_name

        if not cached:
            if default_name:
                return f"- {default_name} (default for add_date)"
            return ""

        lines: list[str] = []
        for cal in cached:
            name = cal.get("name", "")
            if not name:
                continue
            if name == default_name:
                lines.append(f"- {name} (default for add_date)")
            else:
                lines.append(f"- {name}")
        return "\n".join(lines)

    def _handle_user_input(self, user_input: str) -> None:
        """Process a single user input through the two-phase flow."""
        self._session.add_message("user", user_input)
        send_output("AI: Thinking...")
        logger.debug("Phase 1: detecting intent for input: %s", user_input)

        intent = self._phase1_detect_intent()
        logger.debug("Phase 1 result: %s", intent)

        if intent is None:
            send_output("AI: I'm sorry, I couldn't understand that. Could you rephrase?")
            return

        # If AI needs more information, ask the follow-up
        if intent.follow_up_question and not intent.command_name:
            ai_msg = f"AI: {intent.follow_up_question}"
            self._session.add_message("assistant", intent.follow_up_question)
            send_output(ai_msg)
            return

        if intent.command_name is None:
            ai_msg = "AI: I couldn't determine which command you need. Could you be more specific?"
            self._session.add_message("assistant", ai_msg)
            send_output(ai_msg)
            return

        # Phase 2: Validate parameters via function calling
        logger.debug("Phase 2: validating parameters for command: %s", intent.command_name)
        validated = self._phase2_validate_parameters(intent)
        logger.debug("Phase 2 result: %s", validated)

        if validated is None:
            send_output("AI: I had trouble validating the parameters. Let's try again.")
            self._session.clear_for_new_request()
            self._initialize_session()
            return

        # Confirm, edit, or cancel
        action = self._confirm_or_edit(validated)

        if action == "cancel":
            send_output("AI: Cancelled. What else can I do for you?")
            self._session.clear_for_new_request()
            self._initialize_session()
            return

        if action == "change":
            # Preserve context: record what was proposed
            param_lines = ", ".join(f"{k}={v}" for k, v in validated.parameters.items())
            self._session.add_message(
                "assistant",
                f"I proposed: {validated.command_name}({param_lines}). What would you like to change?",
            )
            send_output("AI: What would you like to change?")
            try:
                modification = scheduler_ask("You", default="").strip()
            except (SchedulerAbortError, EOFError, KeyboardInterrupt):
                send_output("\nGoodbye!")
                return
            if not modification:
                send_output("AI: No changes specified. Cancelled.")
                self._session.clear_for_new_request()
                self._initialize_session()
                return
            self._handle_user_input(modification)
            return

        # action == "execute"
        self._execute_command(validated)

    def _phase1_detect_intent(self) -> DetectedIntent | None:
        """Phase 1: Use regular chat completion to detect intent."""
        response_text = self._openai.ai_chat_detect_intent(
            self._session.to_openai_messages(),
        )
        if not response_text:
            return None

        try:
            data = json.loads(response_text)
            return DetectedIntent(
                command_name=data.get("command"),
                parameters=data.get("parameters", {}),
                follow_up_question=data.get("follow_up_question"),
                summary=data.get("summary", ""),
            )
        except json.JSONDecodeError:
            return DetectedIntent(
                command_name=None,
                parameters={},
                follow_up_question=response_text,
                summary="",
            )

    def _phase2_validate_parameters(
        self, intent: DetectedIntent,
    ) -> ValidatedCommand | None:
        """Phase 2: Use function calling to get validated parameters."""
        if intent.command_name is None:
            return None

        command_def = self._registry.get(intent.command_name)
        if command_def is None:
            return None

        tool_call_result = self._openai.ai_chat_validate_parameters(
            command_name=intent.command_name,
            extracted_params=intent.parameters,
            summary=intent.summary,
            tools=[command_def.to_openai_tool()],
        )

        if tool_call_result is None:
            return None

        return ValidatedCommand(
            command_name=tool_call_result["name"],
            parameters=tool_call_result["arguments"],
            summary=intent.summary,
        )

    def _confirm_or_edit(self, command: ValidatedCommand) -> str:
        """Ask the user to execute, change, or cancel the proposed command.

        Returns ``"execute"``, ``"change"``, or ``"cancel"``.
        """
        send_output("")
        send_output("AI: I'll execute the following:")
        send_output(f"  Command: {command.command_name}")
        for key, value in command.parameters.items():
            send_output(f"  {key}: {value}")
        send_output("")

        options = ["Execute", "Change", "Cancel"]
        try:
            index = scheduler_choose("Action?", options, default=0)
        except (SchedulerAbortError, EOFError, KeyboardInterrupt):
            return "cancel"

        return ["execute", "change", "cancel"][index]

    _ERROR_KEYWORDS = ("unrecognised", "failed", "error")

    def _execute_command(self, command: ValidatedCommand) -> None:
        """Execute the validated command, logging errors to the session log."""
        send_output(f"\nAI: Executing {command.command_name}...")

        start_output_capture()
        try:
            self._executor.execute(command.command_name, command.parameters)
        except Exception as e:
            captured = stop_output_capture()
            logger.error(f"Command execution failed: {e}")
            self._error_logger.log_error(
                command_name=command.command_name,
                parameters=command.parameters,
                error=str(e),
                traceback=tb_mod.format_exc(),
            )
            error_summary = f"Command {command.command_name} failed: {e}"
            self._session.add_message("assistant", error_summary)
            send_output(f"\nAI: The command failed: {e}")
            send_output("What else can I do for you?")
            return

        captured = stop_output_capture()

        if any(kw in captured.lower() for kw in self._ERROR_KEYWORDS):
            self._error_logger.log_error(
                command_name=command.command_name,
                parameters=command.parameters,
                error=captured.strip(),
            )

        result_summary = f"Executed {command.command_name} with parameters: {json.dumps(command.parameters)}"
        if captured:
            result_summary += f"\nOutput: {captured.strip()}"
        self._session.add_message("assistant", result_summary)

        send_output("\nAI: Done! What else can I do for you?")
