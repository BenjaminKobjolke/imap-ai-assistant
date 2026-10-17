from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _module(name: str, **attributes: Any) -> ModuleType:
    module = ModuleType(name)
    for key, value in attributes.items():
        setattr(module, key, value)
    return module


@pytest.fixture
def imap_plugin(monkeypatch: Any) -> ModuleType:
    """Load the plugin with lightweight SDK stubs shared by plugin tests."""
    class CommandDefinition:
        def __init__(self, **values: Any) -> None:
            self.__dict__.update(values)

    class CommandParameter:
        def __init__(self, *values: Any, **named_values: Any) -> None:
            self.values = values
            self.named_values = named_values

    class CommandRegistry:
        def register(self, definition: Any, handler: Any) -> None:
            pass

    class PluginInfo:
        def __init__(self, **values: Any) -> None:
            self.__dict__.update(values)

    monkeypatch.setitem(sys.modules, "interactions_sdk", _module("interactions_sdk", output=lambda _: None))
    monkeypatch.setitem(
        sys.modules,
        "src.ai.command_registry",
        _module(
            "src.ai.command_registry",
            CommandDefinition=CommandDefinition,
            CommandParameter=CommandParameter,
            CommandRegistry=CommandRegistry,
        ),
    )
    monkeypatch.setitem(sys.modules, "src.plugins", _module("src.plugins"))
    monkeypatch.setitem(
        sys.modules,
        "src.plugins.loader",
        _module("src.plugins.loader", PluginInfo=PluginInfo),
    )

    plugin_path = Path(__file__).resolve().parents[1] / "imap_plugin.py"
    spec = importlib.util.spec_from_file_location("imap_plugin_under_test", plugin_path)
    assert spec is not None and spec.loader is not None
    plugin = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plugin)
    return plugin


def test_command_builders_preserve_cli_arguments(imap_plugin: ModuleType) -> None:
    """Keep plugin command builders compatible with the CLI argument contract."""

    params = {
        "title": "Title",
        "date": "tomorrow",
        "all_day": False,
        "start_time": "09:00",
        "end_time": "10:00",
        "calendar": "Work",
        "search_term": "invoice",
        "body_term": "paid",
        "date_after": "01.01.2026",
        "date_before": "31.01.2026",
        "date_str": "tomorrow",
        "meeting_id": "meeting-7",
        "name": "rtm_todos",
        "folders": "INBOX,Sent",
        "fast": False,
        "unread_only": False,
        "email_id": "7",
        "folder": "Archive",
        "priority": 2,
        "due_date": "tomorrow",
        "invite_id": "invite-9",
        "email_address": "alice@example.com",
        "salutation": "Alice",
        "is_formal": True,
        "body_text": "Reply",
        "path": "INBOX",
    }
    expected = {
        "add_date": ["--add-date", "Title", "tomorrow", "09:00-10:00", "@Work"],
        "search": [
            "--search", "invoice", "--body", "paid", "--date", "tomorrow",
            "--date-after", "01.01.2026", "--date-before", "31.01.2026", "--path", "INBOX",
        ],
        "add_todo": ["--add-todo", "Title", "!2", "^tomorrow"],
        "todays_meetings": ["--todays-meetings"],
        "meetings": ["--meetings", "tomorrow"],
        "meeting_detail": ["--meeting-detail", "tomorrow", "meeting-7"],
        "list_workflows": ["--workflow"],
        "run_workflow": ["--workflow", "rtm_todos"],
        "update_search_cache": ["--update-cache", "--folders", "INBOX,Sent"],
        "list_inbox": ["--list-inbox"],
        "show_email": ["--show-email", "7"],
        "move_email": ["--move-email", "7", "Archive"],
        "trash_email": ["--trash-email", "7"],
        "list_folders": ["--list-folders"],
        "todo_from_email": ["--todo-from-email", "7"],
        "send_todo_from_email": ["--send-todo-from-email", "7", "Title", "2", "tomorrow"],
        "list_invites": ["--list-invites"],
        "show_invite": ["--show-invite", "invite-9"],
        "accept_invite": ["--accept-invite", "invite-9"],
        "archive_invite": ["--archive-invite", "invite-9"],
        "delete_cancelled_invite": ["--delete-cancelled-invite", "invite-9"],
        "prepare_reply": ["--prepare-reply", "7"],
        "save_salutation": ["--save-salutation", "alice@example.com", "Alice", "true"],
    }
    actual = {definition.name: builder(params) for definition, builder in imap_plugin._COMMANDS}

    assert actual == expected
    assert imap_plugin._COMMANDS


def test_system_prompt_is_loaded_from_prompt_file(imap_plugin: ModuleType) -> None:
    """Keep the plugin's email workflow instructions available after extraction."""
    assert imap_plugin.SYSTEM_PROMPT_EXTRA
    assert imap_plugin.SYSTEM_PROMPT_EXTRA.startswith(
        "You have access to email and calendar management commands."
    )
