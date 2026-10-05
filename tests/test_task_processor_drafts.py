"""Tests for TaskProcessor drafts-only mode: no mail may leave via SMTP."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest

from src.ai.openai_client import OpenAIClient, TodoResult
from src.config.settings import ConfigManager
from src.email.imap_client import EnhancedImapClient
from src.email.smtp_client import SmtpClient
from src.processors.task_processor import TaskProcessor

MODULE = "src.processors.task_processor"


@dataclass
class Harness:
    """Mocks a TaskProcessor run touches, bundled for assertions."""

    config: MagicMock
    todo_service: MagicMock
    draft_writer: MagicMock
    source_client: MagicMock
    processor_imap: MagicMock

    def run(self, drafts_only: bool) -> bool:
        """Process one forwarded email assigned to markus."""
        processor = TaskProcessor(
            self.config, MagicMock(spec=SmtpClient), MagicMock(spec=OpenAIClient), drafts_only=drafts_only,
        )
        incoming = MagicMock()
        incoming.from_address = "me@example.com"
        return processor.process_single_email(self.processor_imap, "1", incoming)


@pytest.fixture()
def harness() -> Iterator[Harness]:
    """Wire a processor run where the AI assigns the task to markus."""
    config = MagicMock(spec=ConfigManager)
    config.get_other_people_names.return_value = ["markus"]
    config.get_processing_rules.return_value = {
        "target_folder": "Waits",
        "additional_subject_tag": "#tag",
        "email_address": "markus@example.com",
        "bcc": "",
    }
    config.processor_done_folder = ""
    config.processor_sent_folder = "Sent"
    config.get_source_account_by_email.return_value = {"name": "Main", "email_address": "me@example.com"}

    processor_imap = MagicMock(spec=EnhancedImapClient)
    processor_imap.extract_email_content.return_value = ("Fwd: Hello", "markus", "body")

    original = MagicMock()
    original.subject = "Hello"

    with (
        patch(f"{MODULE}.TodoService") as todo_cls,
        patch(f"{MODULE}.TaskDraftWriter") as writer_cls,
        patch(f"{MODULE}.EnhancedImapClient") as source_cls,
        patch(f"{MODULE}.scheduler_choose", return_value=1),
        patch(f"{MODULE}.scheduler_confirm", return_value=True),
        patch(f"{MODULE}.send_output"),
    ):
        todo_cls.generate_todo.return_value = TodoResult(
            title="Buy milk", priority=2, due_date="tomorrow", assignee="markus",
        )
        todo_cls.edit_todo.side_effect = lambda result: result
        todo_cls.edit_tags.side_effect = lambda tags: tags
        todo_service = todo_cls.return_value
        todo_service.resolve_rule_assignee.return_value = None
        todo_service.resolve_extra_tags.return_value = ""
        todo_service.send_todo.return_value = (True, b"sent")

        source_client = source_cls.return_value
        source_client.connect.return_value = True
        source_client._strip_subject_prefixes.side_effect = lambda subject: subject.replace("Fwd: ", "")
        source_client.client.get_all_messages.return_value = [("42", original)]
        source_client.client.move_to_folder.return_value = True
        source_client.client.forward_email.return_value = True

        yield Harness(config, todo_service, writer_cls.return_value, source_client, processor_imap)


def test_drafts_only_saves_drafts_and_sends_nothing(harness: Harness) -> None:
    """Both mails become drafts; side effects still happen so a rerun skips the email."""
    assert harness.run(drafts_only=True)

    harness.draft_writer.save_rtm_todo.assert_called_once()
    harness.draft_writer.save_forward.assert_called_once()
    harness.todo_service.send_todo.assert_not_called()
    harness.source_client.client.forward_email.assert_not_called()
    harness.processor_imap.append_to_folder.assert_not_called()
    harness.processor_imap.mark_message_as_read.assert_called_once_with("1")
    harness.source_client.client.move_to_folder.assert_called_once()


def test_failed_todo_draft_leaves_email_unprocessed(harness: Harness) -> None:
    """A draft that was not saved must not mark the email as handled."""
    harness.draft_writer.save_rtm_todo.return_value = False

    assert not harness.run(drafts_only=True)

    harness.processor_imap.mark_message_as_read.assert_not_called()
    harness.source_client.client.move_to_folder.assert_not_called()


def test_default_mode_still_sends(harness: Harness) -> None:
    """Without the switch the workflow sends as before and writes no drafts."""
    assert harness.run(drafts_only=False)

    harness.todo_service.send_todo.assert_called_once()
    harness.source_client.client.forward_email.assert_called_once()
    harness.draft_writer.save_rtm_todo.assert_not_called()
    harness.draft_writer.save_forward.assert_not_called()
