"""Tests for SalutationManager."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.ai.openai_client import OpenAIClient
from src.config.settings import ConfigManager
from src.processors.salutation_manager import SalutationManager
from src.search.search_cache import SearchCache


@pytest.fixture()
def cache(tmp_path: Path) -> SearchCache:
    """Create a temporary SearchCache."""
    return SearchCache(tmp_path / "test.db")


@pytest.fixture()
def config() -> MagicMock:
    """Create a mock ConfigManager."""
    mock = MagicMock(spec=ConfigManager)
    mock.get_first_account.return_value = {"email_address": "me@example.com"}
    mock.get_sent_folder.return_value = "Sent"
    return mock


@pytest.fixture()
def openai_client() -> MagicMock:
    """Create a mock OpenAIClient."""
    return MagicMock(spec=OpenAIClient)


@pytest.fixture()
def imap_client() -> MagicMock:
    """Create a mock EnhancedImapClient."""
    mock = MagicMock()
    mock.client.get_all_messages.return_value = []
    return mock


@pytest.fixture()
def manager(
    cache: SearchCache,
    config: MagicMock,
    openai_client: MagicMock,
    imap_client: MagicMock,
) -> SalutationManager:
    """Create a SalutationManager with mocked dependencies."""
    return SalutationManager(cache, config, openai_client, imap_client)


class TestDbLookup:
    """Tests for DB cache lookup."""

    def test_returns_cached_salutation(self, manager: SalutationManager, cache: SearchCache) -> None:
        """When salutation exists in DB, return it without AI call."""
        cache.save_salutation("user@example.com", "Herr Mueller", is_formal=True)

        result = manager.resolve_salutation("user@example.com")

        assert result.salutation == "Herr Mueller"
        assert result.is_formal is True
        assert result.skip_greeting is False

    def test_returns_cached_skip_greeting(self, manager: SalutationManager, cache: SearchCache) -> None:
        """When DB has skip_greeting=True, return it."""
        cache.save_salutation("user@example.com", "", skip_greeting=True)

        result = manager.resolve_salutation("user@example.com")

        assert result.skip_greeting is True
        assert result.salutation == ""


class TestAiDetection:
    """Tests for AI-based salutation detection from sent emails."""

    @patch("src.processors.salutation_manager.scheduler_confirm", return_value=True)
    @patch("src.processors.salutation_manager.send_output")
    def test_ai_detection_accepted(
        self,
        _mock_output: MagicMock,
        _mock_confirm: MagicMock,
        manager: SalutationManager,
        openai_client: MagicMock,
        cache: SearchCache,
    ) -> None:
        """When AI detects salutation and user confirms, save and return it."""
        # Simulate sent email found
        manager._search_sent_emails = MagicMock(return_value=("Hallo Benjamin, ...", 1))  # type: ignore[method-assign]
        openai_client.detect_salutation.return_value = {"salutation": "Benjamin", "formal": False}

        result = manager.resolve_salutation("ben@example.com")

        assert result.salutation == "Benjamin"
        assert result.is_formal is False
        # Should be saved in DB
        cached = cache.get_salutation("ben@example.com")
        assert cached is not None
        assert cached["salutation"] == "Benjamin"


class TestManualInput:
    """Tests for manual salutation entry."""

    @patch("src.processors.salutation_manager.scheduler_ask", return_value="Frau Schmidt")
    @patch("src.processors.salutation_manager.SchedulerChoice")
    @patch("src.processors.salutation_manager.send_output")
    def test_manual_entry(
        self,
        _mock_output: MagicMock,
        mock_choice_cls: MagicMock,
        _mock_ask: MagicMock,
        manager: SalutationManager,
        cache: SearchCache,
    ) -> None:
        """When no sent emails and no AI, ask user manually."""
        # First choice: "manual", second choice: "formal"
        mock_choice_cls.return_value.choose.side_effect = ["manual", "formal"]

        result = manager._ask_manual("new@example.com")

        assert result.salutation == "Frau Schmidt"
        assert result.is_formal is True
        cached = cache.get_salutation("new@example.com")
        assert cached is not None

    @patch("src.processors.salutation_manager.SchedulerChoice")
    @patch("src.processors.salutation_manager.send_output")
    def test_skip_greeting(
        self,
        _mock_output: MagicMock,
        mock_choice_cls: MagicMock,
        manager: SalutationManager,
        cache: SearchCache,
    ) -> None:
        """When user chooses 'skip', return skip_greeting=True."""
        mock_choice_cls.return_value.choose.return_value = "skip"

        result = manager._ask_manual("skip@example.com")

        assert result.skip_greeting is True
        cached = cache.get_salutation("skip@example.com")
        assert cached is not None
        assert cached["skip_greeting"] is True
