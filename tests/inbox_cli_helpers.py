"""Shared test fixtures for inbox CLI behavior."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.config.settings import ConfigManager
from src.constants import CFG_ADDITIONAL_SUBJECT_TAG, CFG_TARGET_FOLDER
from src.email.imap_client import EnhancedImapClient


def make_email(
    *,
    subject: str = "Test subject",
    from_address: str = "sender@example.com",
    date: str = "2026-03-08",
) -> MagicMock:
    """Create a minimal mock email message."""
    msg = MagicMock()
    msg.subject = subject
    msg.from_address = from_address
    msg.date = date
    msg.get_body = MagicMock(return_value="Hello, this is the body.")
    return msg


def make_config() -> MagicMock:
    """Create a mock ConfigManager."""
    config = MagicMock(spec=ConfigManager)
    config.get_first_account.return_value = {
        "name": "Test",
        "server": "imap.test.com",
        "username": "user@test.com",
        "password": "pass",
        "port": 993,
        "use_ssl": True,
    }
    config.trash_folder = "Trash"
    config.get_processing_rules.return_value = {
        CFG_TARGET_FOLDER: "Company/@BKToDo",
        CFG_ADDITIONAL_SUBJECT_TAG: "#BKToDo",
    }
    config.openai_api_key = "test-key"
    config.openai_model = "gpt-4o"
    config.openai_max_completion_tokens = 100
    config.openai_temperature = 0.3
    config.get_other_people_names.return_value = []
    return config


def make_client(messages: list[tuple[object, object]] | None = None) -> MagicMock:
    """Create a mock EnhancedImapClient."""
    client = MagicMock(spec=EnhancedImapClient)
    inner = MagicMock()
    client.client = inner
    client.connect.return_value = True

    if messages is None:
        messages = []

    inner.get_all_messages.return_value = messages
    inner.get_unread_messages.return_value = messages
    inner.move_to_folder.return_value = True
    inner.list_folders.return_value = ["INBOX", "Trash", "Company/Sales", "Company/@BKToDo"]
    client.extract_email_content.return_value = ("Test subject", "First line", "Body excerpt")

    return client


