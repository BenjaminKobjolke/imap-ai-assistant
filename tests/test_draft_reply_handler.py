"""Tests for DraftReplyHandler — delegation of draft reply flow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.ai.openai_client import OpenAIClient
from src.config.settings import ConfigManager
from src.email.draft_reply_handler import DraftReplyHandler
from src.email.imap_client import EnhancedImapClient
from src.search.search_cache import SearchCache


def _handler() -> DraftReplyHandler:
    """Create a DraftReplyHandler with mocked dependencies."""
    client = MagicMock(spec=EnhancedImapClient)
    config = MagicMock(spec=ConfigManager)
    openai_client = MagicMock(spec=OpenAIClient)
    cache = MagicMock(spec=SearchCache)
    return DraftReplyHandler(client, config, openai_client, cache)


class TestDraftReply:
    """Tests for DraftReplyHandler.draft_reply."""

    @patch("src.email.draft_reply_handler.DraftEmailBuilder")
    @patch("src.email.draft_reply_handler.DraftComposer")
    @patch("src.email.draft_reply_handler.GreetingBuilder")
    @patch("src.email.draft_reply_handler.SalutationManager")
    def test_full_flow_saves_draft(
        self,
        mock_sal_cls: MagicMock,
        mock_greet_cls: MagicMock,
        mock_composer_cls: MagicMock,
        mock_builder_cls: MagicMock,
    ) -> None:
        """Happy path: salutation resolved, draft composed, and saved."""
        handler = _handler()

        mock_sal_mgr = MagicMock()
        mock_sal_cls.return_value = mock_sal_mgr

        mock_greet_cls.build_greeting.return_value = "Hallo Herr Mueller"

        mock_composer = MagicMock()
        mock_composer.compose.return_value = "Thanks for your email."
        mock_composer_cls.return_value = mock_composer

        mock_builder = MagicMock()
        mock_builder_cls.return_value = mock_builder
        mock_builder_cls.make_reply_subject.return_value = "Re: Meeting"
        mock_builder_cls.load_footer_html.return_value = "<footer/>"

        handler.draft_reply(
            from_addr_raw='"John Doe" <john@example.com>',
            subject="Meeting",
            body="Let's meet tomorrow.",
        )

        mock_sal_mgr.resolve_salutation.assert_called_once_with("john@example.com")
        mock_composer.compose.assert_called_once()
        mock_builder.build_and_save.assert_called_once()

    @patch("src.email.draft_reply_handler.send_output")
    @patch("src.email.draft_reply_handler.DraftComposer")
    @patch("src.email.draft_reply_handler.GreetingBuilder")
    @patch("src.email.draft_reply_handler.SalutationManager")
    def test_cancelled_draft_does_not_save(
        self,
        mock_sal_cls: MagicMock,
        mock_greet_cls: MagicMock,
        mock_composer_cls: MagicMock,
        mock_output: MagicMock,
    ) -> None:
        """When composer returns None (cancelled), no draft is saved."""
        handler = _handler()

        mock_sal_cls.return_value = MagicMock()
        mock_greet_cls.build_greeting.return_value = ""

        mock_composer = MagicMock()
        mock_composer.compose.return_value = None
        mock_composer_cls.return_value = mock_composer

        handler.draft_reply(
            from_addr_raw="alice@example.com",
            subject="Hello",
            body="Hi there",
        )

        mock_output.assert_called_with("  Draft cancelled.")

    @patch("src.email.draft_reply_handler.DraftEmailBuilder")
    @patch("src.email.draft_reply_handler.DraftComposer")
    @patch("src.email.draft_reply_handler.GreetingBuilder")
    @patch("src.email.draft_reply_handler.SalutationManager")
    def test_from_addr_parsed_correctly(
        self,
        mock_sal_cls: MagicMock,
        mock_greet_cls: MagicMock,
        mock_composer_cls: MagicMock,
        mock_builder_cls: MagicMock,
    ) -> None:
        """The from_addr is correctly extracted from raw format."""
        handler = _handler()

        mock_sal_mgr = MagicMock()
        mock_sal_cls.return_value = mock_sal_mgr
        mock_greet_cls.build_greeting.return_value = ""

        mock_composer = MagicMock()
        mock_composer.compose.return_value = "Reply text"
        mock_composer_cls.return_value = mock_composer

        mock_builder = MagicMock()
        mock_builder_cls.return_value = mock_builder
        mock_builder_cls.make_reply_subject.return_value = "Re: Test"
        mock_builder_cls.load_footer_html.return_value = ""

        handler.draft_reply(
            from_addr_raw='"Jane Smith" <jane@corp.com>',
            subject="Test",
            body="Content",
        )

        mock_sal_mgr.resolve_salutation.assert_called_once_with("jane@corp.com")
