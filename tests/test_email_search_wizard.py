"""Tests for EmailSearch wizard folder selection and mode-based routing."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.config.settings import ConfigManager
from src.constants import (
    FOLDER_INBOX,
    SEARCH_MODE_ALL,
    SEARCH_MODE_DEFAULT,
    SEARCH_MODE_FOLDER,
    SEARCH_MODE_INBOX,
    SEARCH_MODE_SENT,
)
from src.email.imap_client import EnhancedImapClient
from src.search.email_search import EmailSearch
from src.search.search_cache import SearchCache


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_client() -> MagicMock:
    """Create a mock EnhancedImapClient."""
    client = MagicMock(spec=EnhancedImapClient)
    inner = MagicMock()
    client.client = inner
    return client


def _mock_config() -> MagicMock:
    """Create a mock ConfigManager."""
    config = MagicMock(spec=ConfigManager)
    config.search_live_folders = [FOLDER_INBOX]
    config.get_sent_folder.return_value = "Sent"
    return config


def _mock_cache() -> MagicMock:
    """Create a mock SearchCache."""
    cache = MagicMock(spec=SearchCache)
    cache.search.return_value = []
    return cache


# ===================================================================
# _execute_wizard_search — mode routing
# ===================================================================


class TestExecuteWizardSearch:
    """Tests for EmailSearch._execute_wizard_search mode routing."""

    @patch.object(EmailSearch, "_search_live_folders", return_value=[])
    def test_default_mode_searches_cache_and_live(
        self, mock_live: MagicMock,
    ) -> None:
        """Default mode searches both cache and live folders."""
        client = _mock_client()
        config = _mock_config()
        cache = _mock_cache()
        cache.search.return_value = [{"date_iso": "2025-01-01", "subject": "cached"}]

        results = EmailSearch._execute_wizard_search(
            client, config, cache,
            mode=SEARCH_MODE_DEFAULT,
            specific_folder=None,
            term="test", field="all", body_term=None,
            date_exact=None, date_after=None, date_before=None,
        )

        cache.search.assert_called_once()
        mock_live.assert_called_once()
        assert len(results) == 1

    @patch.object(EmailSearch, "_search_all_imap_folders", return_value=[])
    def test_all_mode_searches_all_folders(
        self, mock_all: MagicMock,
    ) -> None:
        """All mode delegates to _search_all_imap_folders."""
        client = _mock_client()
        config = _mock_config()
        cache = _mock_cache()

        EmailSearch._execute_wizard_search(
            client, config, cache,
            mode=SEARCH_MODE_ALL,
            specific_folder=None,
            term="test", field="all", body_term=None,
            date_exact=None, date_after=None, date_before=None,
        )

        mock_all.assert_called_once()

    @patch.object(EmailSearch, "_search_specific_folder", return_value=[])
    def test_inbox_mode_searches_inbox(
        self, mock_specific: MagicMock,
    ) -> None:
        """Inbox mode searches INBOX folder specifically."""
        client = _mock_client()
        config = _mock_config()
        cache = _mock_cache()

        EmailSearch._execute_wizard_search(
            client, config, cache,
            mode=SEARCH_MODE_INBOX,
            specific_folder=None,
            term="test", field="all", body_term=None,
            date_exact=None, date_after=None, date_before=None,
        )

        mock_specific.assert_called_once()
        # First positional args: client, config, cache, folder
        args = mock_specific.call_args[0]
        assert args[3] == FOLDER_INBOX

    @patch.object(EmailSearch, "_search_specific_folder", return_value=[])
    def test_sent_mode_uses_config_sent_folder(
        self, mock_specific: MagicMock,
    ) -> None:
        """Sent mode uses the sent folder from config."""
        client = _mock_client()
        config = _mock_config()
        config.get_sent_folder.return_value = "MyAccount/Sent Items"
        cache = _mock_cache()

        EmailSearch._execute_wizard_search(
            client, config, cache,
            mode=SEARCH_MODE_SENT,
            specific_folder=None,
            term="test", field="all", body_term=None,
            date_exact=None, date_after=None, date_before=None,
        )

        mock_specific.assert_called_once()
        args = mock_specific.call_args[0]
        assert args[3] == "MyAccount/Sent Items"

    @patch.object(EmailSearch, "_search_specific_folder", return_value=[])
    def test_folder_mode_uses_specific_folder(
        self, mock_specific: MagicMock,
    ) -> None:
        """Folder mode uses the user-picked specific folder."""
        client = _mock_client()
        config = _mock_config()
        cache = _mock_cache()

        EmailSearch._execute_wizard_search(
            client, config, cache,
            mode=SEARCH_MODE_FOLDER,
            specific_folder="Company/HR",
            term="test", field="all", body_term=None,
            date_exact=None, date_after=None, date_before=None,
        )

        mock_specific.assert_called_once()
        args = mock_specific.call_args[0]
        assert args[3] == "Company/HR"


# ===================================================================
# _pick_search_folder
# ===================================================================


class TestPickSearchFolder:
    """Tests for EmailSearch._pick_search_folder."""

    @patch("src.search.email_search.folder_search_loop", return_value="Company/Sales")
    def test_returns_selected_folder(self, mock_loop: MagicMock) -> None:
        """When folder_search_loop returns a folder, it is passed through."""
        client = _mock_client()
        client.client.list_folders.return_value = ["Company/Sales", "INBOX"]

        result = EmailSearch._pick_search_folder(client)

        assert result == "Company/Sales"
        mock_loop.assert_called_once()

    @patch("src.search.email_search.folder_search_loop", return_value=None)
    def test_returns_none_on_cancel(self, mock_loop: MagicMock) -> None:
        """When folder_search_loop returns None, None is returned."""
        client = _mock_client()
        client.client.list_folders.return_value = ["INBOX"]

        result = EmailSearch._pick_search_folder(client)

        assert result is None

    @patch("src.search.email_search.send_output")
    def test_returns_none_on_list_error(self, mock_output: MagicMock) -> None:
        """When listing folders fails, None is returned with error message."""
        client = _mock_client()
        client.client.list_folders.side_effect = Exception("connection lost")

        result = EmailSearch._pick_search_folder(client)

        assert result is None

    @patch("src.search.email_search.send_output")
    def test_returns_none_when_no_folders(self, mock_output: MagicMock) -> None:
        """When no folders exist, None is returned."""
        client = _mock_client()
        client.client.list_folders.return_value = []

        result = EmailSearch._pick_search_folder(client)

        assert result is None


# ===================================================================
# _search_all_imap_folders
# ===================================================================


class TestSearchAllImapFolders:
    """Tests for EmailSearch._search_all_imap_folders."""

    @patch("src.search.email_search.send_output")
    @patch.object(EmailSearch, "_search_single_live_folder")
    def test_searches_every_folder_with_progress(
        self, mock_search: MagicMock, mock_output: MagicMock,
    ) -> None:
        """All folders are searched and progress is displayed."""
        client = _mock_client()
        client.client.list_folders.return_value = ["INBOX", "Sent", "Archive"]
        mock_search.return_value = []

        EmailSearch._search_all_imap_folders(
            client, "test", "all", None, None, None, None,
        )

        assert mock_search.call_count == 3
        # Progress output for each folder
        assert mock_output.call_count == 3

    @patch("src.search.email_search.send_output")
    def test_returns_empty_on_list_error(self, mock_output: MagicMock) -> None:
        """When listing folders fails, an empty list is returned."""
        client = _mock_client()
        client.client.list_folders.side_effect = Exception("offline")

        results = EmailSearch._search_all_imap_folders(
            client, "test", "all", None, None, None, None,
        )

        assert results == []
