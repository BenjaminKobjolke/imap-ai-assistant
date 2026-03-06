"""Tests for MeetingService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.config.settings import ConfigManager
from src.processors.meeting_service import MeetingService


@pytest.fixture()
def config() -> MagicMock:
    """Create a mock ConfigManager."""
    mock = MagicMock(spec=ConfigManager)
    mock.get_first_account.return_value = {"host": "imap.example.com", "username": "test"}
    mock.meetings_folder = "Meetings"
    mock.meetings_age_limit_hours = 24
    mock.meetings_archive_folder = "Archive"
    return mock


@pytest.fixture()
def service(config: MagicMock) -> MeetingService:
    """Create a MeetingService with a mock config."""
    return MeetingService(config)


class TestMeetingService:
    """Tests for MeetingService."""

    @patch("src.processors.meeting_service.MeetingCleanup")
    @patch("src.processors.meeting_service.EnhancedImapClient")
    def test_todays_meetings_interactive_false(
        self,
        mock_imap_cls: MagicMock,
        mock_cleanup: MagicMock,
        service: MeetingService,
    ) -> None:
        """Verify todays_meetings passes interactive=False to list_todays_meetings."""
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_imap_cls.return_value = mock_client

        service.todays_meetings(interactive=False)

        mock_cleanup.list_todays_meetings.assert_called_once()
        call_kwargs = mock_cleanup.list_todays_meetings.call_args
        assert call_kwargs.kwargs.get("interactive") is False

    @patch("src.processors.meeting_service.MeetingCleanup")
    @patch("src.processors.meeting_service.EnhancedImapClient")
    def test_todays_meetings_defaults_to_interactive_true(
        self,
        mock_imap_cls: MagicMock,
        mock_cleanup: MagicMock,
        service: MeetingService,
    ) -> None:
        """Verify todays_meetings defaults to interactive=True."""
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_imap_cls.return_value = mock_client

        service.todays_meetings()

        call_kwargs = mock_cleanup.list_todays_meetings.call_args
        assert call_kwargs.kwargs.get("interactive") is True

    @patch("src.processors.meeting_service.MeetingCleanup")
    @patch("src.processors.meeting_service.EnhancedImapClient")
    def test_meetings_passes_date_and_interactive(
        self,
        mock_imap_cls: MagicMock,
        mock_cleanup: MagicMock,
        service: MeetingService,
    ) -> None:
        """Verify meetings passes date_str and interactive flag correctly."""
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_imap_cls.return_value = mock_client

        from datetime import date
        mock_cleanup._parse_date.return_value = date(2026, 3, 10)

        service.meetings("10.03.2026", interactive=False)

        mock_cleanup.list_todays_meetings.assert_called_once()
        call_kwargs = mock_cleanup.list_todays_meetings.call_args
        assert call_kwargs.kwargs.get("interactive") is False
        assert call_kwargs.kwargs.get("target_date") == date(2026, 3, 10)

    def test_connect_main_account_returns_none_on_missing_config(
        self, service: MeetingService, config: MagicMock,
    ) -> None:
        """Verify _connect_main_account returns None when no account configured."""
        config.get_first_account.return_value = None
        result = service._connect_main_account()
        assert result is None

    @patch("src.processors.meeting_service.EnhancedImapClient")
    def test_connect_main_account_returns_none_on_connect_failure(
        self, mock_imap_cls: MagicMock, service: MeetingService,
    ) -> None:
        """Verify _connect_main_account returns None when connect fails."""
        mock_client = MagicMock()
        mock_client.connect.return_value = False
        mock_imap_cls.return_value = mock_client
        result = service._connect_main_account()
        assert result is None

    @patch("src.processors.meeting_service.MeetingCleanup")
    @patch("src.processors.meeting_service.EnhancedImapClient")
    def test_cleanup_meetings_delegates(
        self,
        mock_imap_cls: MagicMock,
        mock_cleanup: MagicMock,
        service: MeetingService,
        config: MagicMock,
    ) -> None:
        """Verify cleanup_meetings delegates to MeetingCleanup.cleanup_old_meetings."""
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_imap_cls.return_value = mock_client

        service.cleanup_meetings()

        mock_cleanup.cleanup_old_meetings.assert_called_once_with(mock_client, config)
        mock_client.disconnect.assert_called_once()

    @patch("src.processors.meeting_service.MeetingCleanup")
    @patch("src.processors.meeting_service.EnhancedImapClient")
    def test_todays_meeting_detail_delegates(
        self,
        mock_imap_cls: MagicMock,
        mock_cleanup: MagicMock,
        service: MeetingService,
        config: MagicMock,
    ) -> None:
        """Verify todays_meeting_detail delegates to MeetingCleanup.show_meeting_detail."""
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_imap_cls.return_value = mock_client

        service.todays_meeting_detail(3)

        mock_cleanup.show_meeting_detail.assert_called_once_with(mock_client, config, 3)
        mock_client.disconnect.assert_called_once()
