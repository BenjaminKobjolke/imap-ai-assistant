"""Tests for TaskDraftWriter."""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest
from imap_client_lib import EmailMessage

from src.config.settings import ConfigManager
from src.constants import HEADER_TASK_ID, MIME_TEXT_HTML, MIME_TEXT_PLAIN
from src.processors.task_draft_writer import TaskDraftWriter

HEADERS = {HEADER_TASK_ID: "task-1"}
MAIN_ACCOUNT = {"name": "Main", "email_address": "me@example.com"}


@pytest.fixture()
def config() -> MagicMock:
    """Config whose first account is the draft target."""
    config = MagicMock(spec=ConfigManager)
    config.rtm_email = "rtm@example.com"
    config.get_first_account.return_value = MAIN_ACCOUNT
    config.get_drafts_folder.return_value = "Drafts"
    return config


@pytest.fixture()
def imap() -> Iterator[MagicMock]:
    """Patched IMAP client instance that connects and saves successfully."""
    with patch("src.processors.task_draft_writer.EnhancedImapClient") as imap_cls:
        instance = imap_cls.return_value
        instance.connect.return_value = True
        instance.client.save_draft.return_value = True
        yield instance


def _original(html: str = "") -> MagicMock:
    original = MagicMock(spec=EmailMessage)
    original.from_address = "client@example.com"
    original.date = "Mon, 5 Oct 2026"
    original.subject = "Hello"
    original.attachments = [MagicMock()]
    original.get_body.side_effect = lambda kind: html if kind == MIME_TEXT_HTML else "plain text"
    return original


class TestSaveRtmTodo:
    """The RTM todo mail lands in the main account's Drafts."""

    def test_saves_draft_addressed_to_rtm(self, config: MagicMock, imap: MagicMock) -> None:
        """Recipient, subject, sender and folder match what the send path would use."""
        assert TaskDraftWriter(config).save_rtm_todo("Buy milk !2", "#tag", "Fwd: Hello", "me@example.com", HEADERS)

        kwargs = imap.client.save_draft.call_args.kwargs
        assert kwargs["to_addresses"] == ["rtm@example.com"]
        assert kwargs["subject"] == "Buy milk !2 #tag"
        assert kwargs["from_email"] == "me@example.com"
        assert kwargs["draft_folder"] == "Drafts"
        assert kwargs["custom_headers"] == HEADERS
        assert "Todo: Buy milk !2" in kwargs["body"]
        imap.disconnect.assert_called_once()

    def test_missing_rtm_address_saves_nothing(self, config: MagicMock, imap: MagicMock) -> None:
        """Without an RTM address there is no recipient to draft for."""
        config.rtm_email = None

        assert not TaskDraftWriter(config).save_rtm_todo("Buy milk", "#tag", "", "", HEADERS)
        imap.client.save_draft.assert_not_called()

    def test_connect_failure_returns_false(self, config: MagicMock, imap: MagicMock) -> None:
        """A failed connection must report failure so the email is not marked done."""
        imap.connect.return_value = False

        assert not TaskDraftWriter(config).save_rtm_todo("Buy milk", "#tag", "", "", HEADERS)
        imap.client.save_draft.assert_not_called()


class TestSaveForward:
    """The assignee forward lands in the main account's Drafts."""

    def test_plain_original(self, config: MagicMock, imap: MagicMock) -> None:
        """Note, forward header, original text and attachments are all carried over."""
        original = _original()

        assert TaskDraftWriter(config).save_forward(
            original, "markus@example.com", "Buy milk !2", "bcc@example.com", HEADERS, "Assigned to you.",
        )

        kwargs = imap.client.save_draft.call_args.kwargs
        assert kwargs["to_addresses"] == ["markus@example.com"]
        assert kwargs["bcc_addresses"] == ["bcc@example.com"]
        assert kwargs["subject"] == "Buy milk !2"
        assert kwargs["content_type"] == MIME_TEXT_PLAIN
        assert kwargs["attachments"] == original.attachments
        assert kwargs["custom_headers"] == HEADERS
        for expected in ("Assigned to you.", "From: client@example.com", "Subject: Hello", "plain text"):
            assert expected in kwargs["body"]
        imap.disconnect.assert_called_once()

    def test_html_original_keeps_html(self, config: MagicMock, imap: MagicMock) -> None:
        """An HTML original stays HTML so formatting survives the draft."""
        original = _original(html="<b>rich</b>")

        assert TaskDraftWriter(config).save_forward(original, "markus@example.com", "Todo", "", HEADERS, "Note")

        kwargs = imap.client.save_draft.call_args.kwargs
        assert kwargs["content_type"] == MIME_TEXT_HTML
        assert "<b>rich</b>" in kwargs["body"]
        assert kwargs["bcc_addresses"] == []
