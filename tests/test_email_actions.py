"""Tests for the shared email action menu loop."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.config.settings import ConfigManager
from src.email.email_actions import email_action_loop
from src.email.imap_client import EnhancedImapClient


class TestEmailActionLoop:
    """Tests for email_action_loop."""

    @patch("src.email.email_actions.SchedulerChoice")
    @patch("src.email.email_actions.EmailBodyViewer")
    def test_show_body_action(self, mock_viewer: MagicMock, mock_choice_cls: MagicMock) -> None:
        """Selecting 'show_body' calls EmailBodyViewer and loops."""
        client = MagicMock(spec=EnhancedImapClient)
        config = MagicMock(spec=ConfigManager)

        # First call: show_body, second call: back
        mock_choice_cls.return_value.choose.side_effect = ["show_body", "back"]

        result = email_action_loop(client, config, "INBOX", "42")

        mock_viewer.show_body.assert_called_once_with(client, "INBOX", "42")
        assert result is None

    @patch("src.email.email_actions.SchedulerChoice")
    @patch("src.email.email_actions.EmailAttachmentViewer")
    def test_show_attachments_action(self, mock_att_viewer: MagicMock, mock_choice_cls: MagicMock) -> None:
        """Selecting 'show_attachments' calls EmailAttachmentViewer and loops."""
        client = MagicMock(spec=EnhancedImapClient)
        config = MagicMock(spec=ConfigManager)

        mock_choice_cls.return_value.choose.side_effect = ["show_attachments", "back"]

        result = email_action_loop(client, config, "INBOX", "42")

        mock_att_viewer.show_attachments.assert_called_once_with(client, config, "INBOX", "42")
        assert result is None

    @patch("src.email.email_actions.SchedulerChoice")
    def test_back_returns_none(self, mock_choice_cls: MagicMock) -> None:
        """Selecting 'back' returns None immediately."""
        client = MagicMock(spec=EnhancedImapClient)
        config = MagicMock(spec=ConfigManager)

        mock_choice_cls.return_value.choose.return_value = "back"

        result = email_action_loop(client, config, "INBOX", "42")

        assert result is None

    @patch("src.email.email_actions.SchedulerChoice")
    def test_extra_action_returned(self, mock_choice_cls: MagicMock) -> None:
        """Extra actions are returned unhandled for the caller."""
        client = MagicMock(spec=EnhancedImapClient)
        config = MagicMock(spec=ConfigManager)

        mock_choice_cls.return_value.choose.return_value = "copy"

        result = email_action_loop(
            client, config, "INBOX", "42",
            extra_actions=[("Copy to search-results", "copy")],
        )

        assert result == "copy"

    @patch("src.email.email_actions.SchedulerChoice")
    def test_extra_actions_included_in_choices(self, mock_choice_cls: MagicMock) -> None:
        """Extra actions appear in the choice list before Back."""
        client = MagicMock(spec=EnhancedImapClient)
        config = MagicMock(spec=ConfigManager)

        mock_choice_cls.return_value.choose.return_value = "back"

        email_action_loop(
            client, config, "INBOX", "42",
            extra_actions=[("Draft reply", "draft_reply")],
        )

        # Verify the choices passed to SchedulerChoice
        init_call = mock_choice_cls.call_args
        choices = init_call[0][1]  # second positional arg
        labels = [label for label, _ in choices]
        assert "Draft reply" in labels
        assert labels[-1] == "Back"

    @patch("src.email.email_actions.SchedulerChoice")
    def test_abort_returns_none(self, mock_choice_cls: MagicMock) -> None:
        """Abort action returns None like back."""
        client = MagicMock(spec=EnhancedImapClient)
        config = MagicMock(spec=ConfigManager)

        mock_choice_cls.return_value.choose.return_value = "abort"

        result = email_action_loop(client, config, "INBOX", "42")

        assert result is None
