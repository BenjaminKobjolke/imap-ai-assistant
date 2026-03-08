"""Business-assistant plugin for imap-ai-assistant commands."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from interactions_sdk import output

from src.ai.command_registry import CommandDefinition, CommandParameter, CommandRegistry
from src.plugins.loader import PluginInfo

_IMAP_ROOT = str(Path(__file__).resolve().parent)

SYSTEM_PROMPT_EXTRA = (
    "You have access to email and calendar management commands. "
    "These commands let you search emails, create calendar events, "
    "manage todos, list meetings, and run workflows.\n\n"
    "## Inbox Zero Workflow\n"
    "When the user asks to do 'inbox zero', 'process inbox', 'check email', or similar:\n"
    "1. Call list_inbox to see all inbox emails\n"
    "2. Do NOT list all emails. Present only email #1 (sender, subject, date) and ask the user what to do with it?\n"
    "3. For each email, ask the user what to do:\n"
    "   - 'show'/'read': call show_email for full body\n"
    "   - 'move to FOLDER': call move_email\n"
    "   - 'trash'/'delete': call trash_email\n"
    "   - 'todo': see Todo from Email workflow below\n"
    "   - 'skip'/'next': move on\n"
    "4. If user doesn't know folder names, call list_folders\n"
    "5. After move/trash/todo, indices change — call list_inbox again before next operation\n"
    "6. When done, summarize actions taken\n\n"
    "## Todo from Email Workflow\n"
    "When the user says 'todo' for an email:\n"
    "1. Call show_email to read the full content\n"
    "2. Generate a todo suggestion based on the email:\n"
    "   - title: concise, descriptive, max 50 chars, no slashes/brackets, no dates in title\n"
    "   - priority: 1 (very important), 2 (important, default), 3 (not so important)\n"
    "   - due_date: 'today', 'tomorrow' (default), or DD.MM.YYYY\n"
    "   - Language: match the email language (default German)\n"
    "   - Use body context to add relevant info (person, company) to title\n"
    "   - The subject may be a forwarded todo for someone else — base the title on what the USER needs to do\n"
    "3. Present the suggestion and ask the user to confirm or edit\n"
    "4. If the user requests changes, apply them, present the updated values, and ask to confirm again. Repeat until the user explicitly confirms.\n"
    "5. Once confirmed, call send_todo_from_email with the final values\n\n"
    "## Meeting Invites Workflow\n"
    "When the user asks to 'process invites', 'check invites', 'meeting invites', or similar:\n"
    "1. Call list_invites to see all pending invites\n"
    "2. Do NOT list all invites. Present only invite #1 (subject, time, organizer) and ask the user what to do with it?\n"
    "3. Present details and ask the user what to do:\n"
    "   - For regular invites: accept_invite (adds to calendar) or archive_invite (decline)\n"
    "   - For cancelled invites: delete_cancelled_invite (removes from calendar) or archive_invite\n"
    "4. After each action, indices change — call list_invites again before next operation\n"
    "5. When done, summarize actions taken"
)


def _run_cli(*args: str) -> str:
    """Run an imap-ai-assistant CLI command and return its output."""
    result = subprocess.run(
        ["uv", "run", "python", "main.py", *args],
        cwd=_IMAP_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        stdin=subprocess.DEVNULL,
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
    if params.get("start_time"):
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


def _todays_meetings_args(params: dict[str, Any]) -> list[str]:
    """Build CLI args for todays_meetings."""
    return ["--todays-meetings"]


def _meetings_args(params: dict[str, Any]) -> list[str]:
    """Build CLI args for meetings."""
    return ["--meetings", str(params["date_str"])]


def _meeting_detail_args(params: dict[str, Any]) -> list[str]:
    """Build CLI args for meeting_detail."""
    return ["--todays-meeting", str(params["index"])]


def _list_workflows_args(params: dict[str, Any]) -> list[str]:
    """Build CLI args for list_workflows."""
    return ["--workflow"]


def _run_workflow_args(params: dict[str, Any]) -> list[str]:
    """Build CLI args for run_workflow."""
    return ["--workflow", params["name"]]


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


def _show_email_args(params: dict[str, Any]) -> list[str]:
    """Build CLI args for show_email."""
    return ["--show-email", str(params["index"])]


def _move_email_args(params: dict[str, Any]) -> list[str]:
    """Build CLI args for move_email."""
    return ["--move-email", str(params["index"]), str(params["folder"])]


def _trash_email_args(params: dict[str, Any]) -> list[str]:
    """Build CLI args for trash_email."""
    return ["--trash-email", str(params["index"])]


def _list_folders_args(params: dict[str, Any]) -> list[str]:
    """Build CLI args for list_folders."""
    return ["--list-folders"]


def _todo_from_email_args(params: dict[str, Any]) -> list[str]:
    """Build CLI args for todo_from_email."""
    return ["--todo-from-email", str(params["index"])]


def _send_todo_from_email_args(params: dict[str, Any]) -> list[str]:
    """Build CLI args for send_todo_from_email."""
    return [
        "--send-todo-from-email",
        str(params["index"]),
        params["title"],
        str(params["priority"]),
        params["due_date"],
    ]


def _list_invites_args(params: dict[str, Any]) -> list[str]:
    """Build CLI args for list_invites."""
    return ["--list-invites"]


def _show_invite_args(params: dict[str, Any]) -> list[str]:
    """Build CLI args for show_invite."""
    return ["--show-invite", str(params["index"])]


def _accept_invite_args(params: dict[str, Any]) -> list[str]:
    """Build CLI args for accept_invite."""
    return ["--accept-invite", str(params["index"])]


def _archive_invite_args(params: dict[str, Any]) -> list[str]:
    """Build CLI args for archive_invite."""
    return ["--archive-invite", str(params["index"])]


def _delete_cancelled_invite_args(params: dict[str, Any]) -> list[str]:
    """Build CLI args for delete_cancelled_invite."""
    return ["--delete-cancelled-invite", str(params["index"])]


# Command definitions matching imap-ai-assistant's @ai_command decorators
_COMMANDS: list[tuple[CommandDefinition, Any]] = [
    (
        CommandDefinition(
            name="add_date",
            description="Create a Google Calendar event",
            parameters=[
                CommandParameter("title", "Title/name of the event", "string", required=True),
                CommandParameter("date", "Date for the event (DD.MM.YYYY, 'today', 'tomorrow')", "string"),
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
        _todays_meetings_args,
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
        _meetings_args,
    ),
    (
        CommandDefinition(
            name="meeting_detail",
            description="Show details for a specific meeting by its index number from the meetings list",
            parameters=[
                CommandParameter("index", "Meeting index number from the meetings list", "integer", required=True),
            ],
        ),
        _meeting_detail_args,
    ),
    (
        CommandDefinition(
            name="list_workflows",
            description="List all available workflows",
            parameters=[],
        ),
        _list_workflows_args,
    ),
    (
        CommandDefinition(
            name="run_workflow",
            description="Execute a named workflow",
            parameters=[
                CommandParameter("name", "Name of the workflow to run", "string", required=True),
            ],
        ),
        _run_workflow_args,
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
            description="Show full details and body of an inbox email by its index number",
            parameters=[
                CommandParameter("index", "1-based index of the email from list_inbox", "integer", required=True),
            ],
        ),
        _show_email_args,
    ),
    (
        CommandDefinition(
            name="move_email",
            description="Move an inbox email to a specific IMAP folder",
            parameters=[
                CommandParameter("index", "1-based index of the email from list_inbox", "integer", required=True),
                CommandParameter("folder", "Target IMAP folder path to move the email to", "string", required=True),
            ],
        ),
        _move_email_args,
    ),
    (
        CommandDefinition(
            name="trash_email",
            description="Move an inbox email to the trash folder",
            parameters=[
                CommandParameter("index", "1-based index of the email from list_inbox", "integer", required=True),
            ],
        ),
        _trash_email_args,
    ),
    (
        CommandDefinition(
            name="list_folders",
            description="List all available IMAP folders (useful for finding folder names for move_email)",
            parameters=[],
        ),
        _list_folders_args,
    ),
    (
        CommandDefinition(
            name="todo_from_email",
            description="Create an RTM todo from an inbox email using AI, then move it to the todo folder",
            parameters=[
                CommandParameter("index", "1-based index of the email from list_inbox", "integer", required=True),
            ],
        ),
        _todo_from_email_args,
    ),
    (
        CommandDefinition(
            name="send_todo_from_email",
            description="Send a confirmed todo from an inbox email and move it to the todo folder. Use this after previewing and confirming the todo details with the user.",
            parameters=[
                CommandParameter("index", "1-based index of the email from list_inbox", "integer", required=True),
                CommandParameter("title", "The confirmed todo title (max 50 chars)", "string", required=True),
                CommandParameter("priority", "Priority: 1 (very important), 2 (important), 3 (not so important)", "integer", required=True),
                CommandParameter("due_date", "Due date: 'today', 'tomorrow', or DD.MM.YYYY", "string", required=True),
            ],
        ),
        _send_todo_from_email_args,
    ),
    (
        CommandDefinition(
            name="list_invites",
            description="List all pending meeting invites with index, subject, time, organizer, and calendar status",
            parameters=[],
        ),
        _list_invites_args,
    ),
    (
        CommandDefinition(
            name="show_invite",
            description="Show details of a meeting invite including conflicts and calendar status",
            parameters=[
                CommandParameter("index", "1-based index of the invite from list_invites", "integer", required=True),
            ],
        ),
        _show_invite_args,
    ),
    (
        CommandDefinition(
            name="accept_invite",
            description="Accept a meeting invite: add to Google Calendar, send RSVP, move to meetings folder",
            parameters=[
                CommandParameter("index", "1-based index of the invite from list_invites", "integer", required=True),
            ],
        ),
        _accept_invite_args,
    ),
    (
        CommandDefinition(
            name="archive_invite",
            description="Archive (decline) a meeting invite email",
            parameters=[
                CommandParameter("index", "1-based index of the invite from list_invites", "integer", required=True),
            ],
        ),
        _archive_invite_args,
    ),
    (
        CommandDefinition(
            name="delete_cancelled_invite",
            description="Delete a cancelled invite from Google Calendar and archive the email",
            parameters=[
                CommandParameter("index", "1-based index of the invite from list_invites", "integer", required=True),
            ],
        ),
        _delete_cancelled_invite_args,
    ),
]


def register(registry: CommandRegistry, config: dict[str, Any], executor: Any) -> PluginInfo:
    """Register imap-ai-assistant commands as business-assistant plugin."""
    handlers: dict[str, Any] = {}

    for cmd_def, args_fn in _COMMANDS:
        registry.register(cmd_def)
        handlers[cmd_def.name] = _make_handler(args_fn)

    executor.add_handlers(handlers)

    return PluginInfo(
        name="IMAP AI Assistant",
        description="Email and calendar management",
        system_prompt_extra=SYSTEM_PROMPT_EXTRA,
    )
