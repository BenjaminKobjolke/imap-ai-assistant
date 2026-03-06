"""Tests for EmailService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.config.settings import ConfigManager
from src.services.email_service import EmailService


@pytest.fixture()
def config() -> MagicMock:
    """Create a mock ConfigManager."""
    mock = MagicMock(spec=ConfigManager)
    mock.get_first_account.return_value = {"host": "imap.example.com", "username": "test"}
    mock.get_processor_account.return_value = {"host": "imap.example.com", "username": "proc"}
    mock.search_cache_path = "cache.db"
    return mock


@pytest.fixture()
def service(config: MagicMock) -> EmailService:
    """Create an EmailService with mock config."""
    return EmailService(config)


class TestEmailService:
    """Tests for EmailService."""

    def test_connect_main_account_returns_none_on_missing_config(
        self, config: MagicMock,
    ) -> None:
        """Verify _connect_main_account returns None when no account configured."""
        config.get_first_account.return_value = None
        svc = EmailService(config)
        result = svc._connect_main_account()
        assert result is None

    @patch("src.services.email_service.EnhancedImapClient")
    def test_connect_main_account_returns_none_on_connect_failure(
        self, mock_imap_cls: MagicMock, service: EmailService,
    ) -> None:
        """Verify _connect_main_account returns None when connect fails."""
        mock_client = MagicMock()
        mock_client.connect.return_value = False
        mock_imap_cls.return_value = mock_client
        result = service._connect_main_account()
        assert result is None

    @patch("src.services.email_service.EmailSearch")
    @patch("src.services.email_service.EnhancedImapClient")
    def test_search_emails_delegates(
        self,
        mock_imap_cls: MagicMock,
        mock_search: MagicMock,
        service: EmailService,
        config: MagicMock,
    ) -> None:
        """Verify search_emails delegates to EmailSearch.search."""
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_imap_cls.return_value = mock_client

        service.search_emails("test", body_term="body")

        mock_search.search.assert_called_once_with(
            mock_client, config, "test", "body", None, None, None, None,
        )
        mock_client.disconnect.assert_called_once()

    @patch("src.services.email_service.EnhancedImapClient")
    def test_inspect_folder_main_account(
        self,
        mock_imap_cls: MagicMock,
        service: EmailService,
    ) -> None:
        """Verify inspect_folder connects to main account by default."""
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.client.get_all_messages.return_value = []
        mock_imap_cls.return_value = mock_client

        service.inspect_folder("INBOX")

        mock_client.connect.assert_called_once()
        mock_client.disconnect.assert_called_once()

    @patch("src.services.email_service.EnhancedImapClient")
    def test_inspect_folder_processor_account(
        self,
        mock_imap_cls: MagicMock,
        service: EmailService,
        config: MagicMock,
    ) -> None:
        """Verify inspect_folder uses processor account when requested."""
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_client.client.get_all_messages.return_value = []
        mock_imap_cls.return_value = mock_client

        service.inspect_folder("INBOX", use_processor_account=True)

        # Should have used get_processor_account, not get_first_account
        config.get_processor_account.assert_called_once()
