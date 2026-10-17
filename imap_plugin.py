"""Business-assistant plugin for imap-ai-assistant commands."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from interactions_sdk import output

from src.ai.command_registry import CommandDefinition, CommandParameter, CommandRegistry
from src.plugins.loader import PluginInfo

_IMAP_ROOT = str(Path(__file__).resolve().parent)

SYSTEM_PROMPT_EXTRA = (
    Path(__file__).resolve().parent / "prompts" / "imap_plugin_system_prompt.txt"
).read_text(encoding="utf-8")

def _run_cli(*args: str, stdin_text: str | None = None) -> str:
    """Run an imap-ai-assistant CLI command and return its output."""
    run_options: dict[str, Any] = {
        "cwd": _IMAP_ROOT,
        "capture_output": True,
        "text": True,
        "timeout": 120,
    }
    if stdin_text is None:
        run_options["stdin"] = subprocess.DEVNULL
    else:
        run_options["input"] = stdin_text
    result = subprocess.run(
        ["uv", "run", "python", "main.py", *args],
        **run_options,
    )
    text = result.stdout.strip()
    if result.returncode != 0 and result.stderr.strip():
        text = f"{text}\n{result.stderr.strip()}" if text else result.stderr.strip()
    return text or "(no output)"


def _make_handler(build_args_fn: Any) -> Any:
    """Create a handler that runs a CLI command and outputs the result."""
    def handler(params: dict[str, Any]) -> None:
        args = build_args_fn(params)
        result = _run_cli(*args)
        output(result)
    return handler


def _add_date_args(params: dict[str, Any]) -> list[str]:
    """Build CLI args for add_date."""
    args = ["--add-date", params["title"]]
    if params.get("date"):
        args.append(str(params["date"]))
    if params.get("all_day"):
        args.append("allday")
    elif params.get("start_time"):
        start = str(params["start_time"])
        end = str(params.get("end_time", ""))
        if end:
            args.append(f"{start}-{end}")
        else:
            args.append(start)
    if params.get("calendar"):
        args.append(f"@{params['calendar']}")
    return args


def _search_args(params: dict[str, Any]) -> list[str]:
    """Build CLI args for search."""
    args = ["--search", params["search_term"]]
    if params.get("body_term"):
        args.extend(["--body", str(params["body_term"])])
    if params.get("date"):
        args.extend(["--date", str(params["date"])])
    if params.get("date_after"):
        args.extend(["--date-after", str(params["date_after"])])
    if params.get("date_before"):
        args.extend(["--date-before", str(params["date_before"])])
    if params.get("path"):
        args.extend(["--path", str(params["path"])])
    return args


def _add_todo_args(params: dict[str, Any]) -> list[str]:
    """Build CLI args for --add-todo."""
    args = ["--add-todo", params["title"]]
    if params.get("priority"):
        args.append(f"!{params['priority']}")
    if params.get("due_date"):
        args.append(f"^{params['due_date']}")
    if params.get("due_time"):
        args.append(params["due_time"])
    return args


def _fixed_args(flag: str, *keys: str) -> Callable[[dict[str, Any]], list[str]]:
    """Build the repeated flag-and-parameter argument shape used by plugin commands."""
    return lambda params: [flag, *(str(params[key]) for key in keys)]


def _update_search_cache_args(params: dict[str, Any]) -> list[str]:
    """Build CLI args for update_search_cache."""
    args = ["--update-cache"]
    if params.get("folders"):
        args.extend(["--folders", str(params["folders"])])
    if params.get("fast"):
        args.append("--fast")
    return args


def _list_inbox_args(params: dict[str, Any]) -> list[str]:
    """Build CLI args for list_inbox."""
    args = ["--list-inbox"]
    if params.get("unread_only"):
        args.append("--unread-only")
    return args


def _save_salutation_args(params: dict[str, Any]) -> list[str]:
    """Build CLI args for save_salutation."""
    return [
        "--save-salutation",
        params["email_address"],
        params["salutation"],
        str(params.get("is_formal", True)).lower(),
    ]


def _save_draft_reply_handler(params: dict[str, Any]) -> None:
    """Handler for save_draft_reply: sends body_text via stdin."""
    result = _run_cli(
        "--save-draft-reply", str(params["email_id"]),
        stdin_text=str(params["body_text"]),
    )
    output(result)


# Command definitions matching imap-ai-assistant's @ai_command decorators
_COMMANDS: list[tuple[CommandDefinition, Any]] = [
    (
        CommandDefinition(
            name="add_date",
            description="Create a Google Calendar event",
            parameters=[
                CommandParameter("title", "Title/name of the event", "string", required=True),
                CommandParameter("date", "Date for the event (DD.MM.YYYY, 'today', 'tomorrow')", "string"),
                CommandParameter("all_day", "Whether this is an all-day event (no specific time)", "boolean"),
                CommandParameter("start_time", "Start time in HH:MM format (e.g. 14:00)", "string"),
                CommandParameter("end_time", "End time in HH:MM format (e.g. 15:00)", "string"),
                CommandParameter("calendar", "Calendar name or ID to create the event in", "string"),
            ],
        ),
        _add_date_args,
    ),
    (
        CommandDefinition(
            name="search",
            description="Search emails by term with optional filters",
            parameters=[
                CommandParameter("search_term", "The search term or query", "string", required=True),
                CommandParameter("body_term", "Additional body text filter", "string"),
                CommandParameter("date", "Exact date filter (DD.MM.YYYY)", "string"),
                CommandParameter("date_after", "Only emails after this date (DD.MM.YYYY)", "string"),
                CommandParameter("date_before", "Only emails before this date (DD.MM.YYYY)", "string"),
                CommandParameter("path", "Specific IMAP folder to search in", "string"),
            ],
        ),
        _search_args,
    ),
    (
        CommandDefinition(
            name="add_todo",
            description="Create a Remember the Milk todo task",
            parameters=[
                CommandParameter("title", "Title/name of the todo task", "string", required=True),
                CommandParameter(
                    "priority",
                    "Priority: 1 (very important), 2 (important), 3 (not so important)",
                    "integer",
                ),
                CommandParameter("due_date", "Due date: 'today', 'tomorrow', or DD.MM.YYYY format", "string"),
                CommandParameter("due_time", "Due time in HH:MM format (e.g. '08:00', '14:30')", "string"),
            ],
        ),
        _add_todo_args,
    ),
    (
        CommandDefinition(
            name="todays_meetings",
            description="List today's meetings with start and end times",
            parameters=[],
        ),
        _fixed_args("--todays-meetings"),
    ),
    (
        CommandDefinition(
            name="meetings",
            description="List meetings for a given date",
            parameters=[
                CommandParameter(
                    "date_str",
                    "Date to list meetings for: 'today', 'tomorrow', a day number like '5' or '12', "
                    "a date like '12.03' or '12.03.2026'",
                    "string",
                    required=True,
                ),
            ],
        ),
        _fixed_args("--meetings", "date_str"),
    ),
    (
        CommandDefinition(
            name="meeting_detail",
            description="Show details for a specific meeting",
            parameters=[
                CommandParameter("date_str", "Date: 'today', 'tomorrow', DD.MM, DD.MM.YYYY", "string", required=True),
                CommandParameter("meeting_id", "The meeting ID from meetings list output", "string", required=True),
            ],
        ),
        _fixed_args("--meeting-detail", "date_str", "meeting_id"),
    ),
    (
        CommandDefinition(
            name="list_workflows",
            description="List all available workflows",
            parameters=[],
        ),
        _fixed_args("--workflow"),
    ),
    (
        CommandDefinition(
            name="run_workflow",
            description="Execute a named workflow",
            parameters=[
                CommandParameter("name", "Name of the workflow to run", "string", required=True),
            ],
        ),
        _fixed_args("--workflow", "name"),
    ),
    (
        CommandDefinition(
            name="update_search_cache",
            description="Rebuild the email search cache",
            parameters=[
                CommandParameter("folders", "Comma-separated folder names to cache (omit for all folders)", "string"),
                CommandParameter("fast", "Skip folders that already have cache files", "boolean"),
            ],
        ),
        _update_search_cache_args,
    ),
    (
        CommandDefinition(
            name="list_inbox",
            description="List all emails in INBOX with index, sender, subject, and date",
            parameters=[
                CommandParameter(
                    "unread_only",
                    "Only list unread emails (default: false, lists all)",
                    "boolean",
                ),
            ],
        ),
        _list_inbox_args,
    ),
    (
        CommandDefinition(
            name="show_email",
            description="Show full details and body of an inbox email by its ID",
            parameters=[
                CommandParameter("email_id", "The email ID from list_inbox output", "string", required=True),
            ],
        ),
        _fixed_args("--show-email", "email_id"),
    ),
    (
        CommandDefinition(
            name="move_email",
            description="Move an inbox email to a specific IMAP folder",
            parameters=[
                CommandParameter("email_id", "The email ID from list_inbox output", "string", required=True),
                CommandParameter("folder", "Target IMAP folder path to move the email to", "string", required=True),
            ],
        ),
        _fixed_args("--move-email", "email_id", "folder"),
    ),
    (
        CommandDefinition(
            name="trash_email",
            description="Move an inbox email to the trash folder",
            parameters=[
                CommandParameter("email_id", "The email ID from list_inbox output", "string", required=True),
            ],
        ),
        _fixed_args("--trash-email", "email_id"),
    ),
    (
        CommandDefinition(
            name="list_folders",
            description="List all available IMAP folders (useful for finding folder names for move_email)",
            parameters=[],
        ),
        _fixed_args("--list-folders"),
    ),
    (
        CommandDefinition(
            name="todo_from_email",
            description="Create an RTM todo from an inbox email using AI, then move it to the todo folder",
            parameters=[
                CommandParameter("email_id", "The email ID from list_inbox output", "string", required=True),
            ],
        ),
        _fixed_args("--todo-from-email", "email_id"),
    ),
    (
        CommandDefinition(
            name="send_todo_from_email",
            description=(
                "Send a confirmed todo from an inbox email and move it to the todo folder. Use this after "
                "previewing and confirming the todo details with the user."
            ),
            parameters=[
                CommandParameter("email_id", "The email ID from list_inbox output", "string", required=True),
                CommandParameter("title", "The confirmed todo title (max 50 chars)", "string", required=True),
                CommandParameter(
                    "priority",
                    "Priority: 1 (very important), 2 (important), 3 (not so important)",
                    "integer",
                    required=True,
                ),
                CommandParameter("due_date", "Due date: 'today', 'tomorrow', or DD.MM.YYYY", "string", required=True),
            ],
        ),
        _fixed_args("--send-todo-from-email", "email_id", "title", "priority", "due_date"),
    ),
    (
        CommandDefinition(
            name="list_invites",
            description="List all pending meeting invites with index, subject, time, organizer, and calendar status",
            parameters=[],
        ),
        _fixed_args("--list-invites"),
    ),
    (
        CommandDefinition(
            name="show_invite",
            description="Show details of a meeting invite including conflicts and calendar status",
            parameters=[
                CommandParameter("invite_id", "The invite ID from list_invites output", "string", required=True),
            ],
        ),
        _fixed_args("--show-invite", "invite_id"),
    ),
    (
        CommandDefinition(
            name="accept_invite",
            description="Accept a meeting invite: add to Google Calendar, send RSVP, move to meetings folder",
            parameters=[
                CommandParameter("invite_id", "The invite ID from list_invites output", "string", required=True),
            ],
        ),
        _fixed_args("--accept-invite", "invite_id"),
    ),
    (
        CommandDefinition(
            name="archive_invite",
            description="Archive (decline) a meeting invite email",
            parameters=[
                CommandParameter("invite_id", "The invite ID from list_invites output", "string", required=True),
            ],
        ),
        _fixed_args("--archive-invite", "invite_id"),
    ),
    (
        CommandDefinition(
            name="delete_cancelled_invite",
            description="Delete a cancelled invite from Google Calendar and archive the email",
            parameters=[
                CommandParameter("invite_id", "The invite ID from list_invites output", "string", required=True),
            ],
        ),
        _fixed_args("--delete-cancelled-invite", "invite_id"),
    ),
    (
        CommandDefinition(
            name="prepare_reply",
            description="Get email content and sender salutation for drafting a reply",
            parameters=[
                CommandParameter("email_id", "The email ID from list_inbox output", "string", required=True),
            ],
        ),
        _fixed_args("--prepare-reply", "email_id"),
    ),
    (
        CommandDefinition(
            name="save_salutation",
            description="Save how to address a contact (salutation) for future emails",
            parameters=[
                CommandParameter("email_address", "The contact's email address", "string", required=True),
                CommandParameter(
                    "salutation", "The salutation text (e.g. 'Herr Mueller', 'Tamara')", "string", required=True
                ),
                CommandParameter(
                    "is_formal", "Whether to use formal address (true) or informal (false)", "boolean", required=True
                ),
            ],
        ),
        _save_salutation_args,
    ),
]


_SAVE_DRAFT_REPLY_CMD = CommandDefinition(
    name="save_draft_reply",
    description="Save a reply draft to the IMAP Drafts folder",
    parameters=[
        CommandParameter("email_id", "The email ID from list_inbox output", "string", required=True),
        CommandParameter("body_text", "The full reply text (greeting + body + closing)", "string", required=True),
    ],
)


def register(registry: CommandRegistry, config: dict[str, Any], executor: Any) -> PluginInfo:
    """Register imap-ai-assistant commands as business-assistant plugin."""
    handlers: dict[str, Any] = {}

    for cmd_def, args_fn in _COMMANDS:
        registry.register(cmd_def)
        handlers[cmd_def.name] = _make_handler(args_fn)

    # save_draft_reply uses a custom handler (stdin-based)
    registry.register(_SAVE_DRAFT_REPLY_CMD)
    handlers[_SAVE_DRAFT_REPLY_CMD.name] = _save_draft_reply_handler

    executor.add_handlers(handlers)

    return PluginInfo(
        name="IMAP AI Assistant",
        description="Email and calendar management",
        system_prompt_extra=SYSTEM_PROMPT_EXTRA,
    )
