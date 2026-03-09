"""Tests for MeetingService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.config.settings import ConfigManager
from src.services.meeting_service import MeetingService


@pytest.fixture()
def config() -> MagicMock:
    """Create a mock ConfigManager."""
    mock = MagicMock(spec=ConfigManager)
    mock.get_first_account.return_value = {"host": "imap.example.com", "username": "test"}
    mock.meetings_folder = "Meetings"
    mock.meetings_age_limit_hours = 24
    mock.meetings_archive_folder = "Archive"
    return mock


class TestMeetingServiceBase:
    """Tests for shared base class methods."""

    def test_connect_main_account_returns_none_on_missing_config(
        self, config: MagicMock,
    ) -> None:
        """Verify _connect_main_account returns None when no account configured."""
        config.get_first_account.return_value = None
        service = MeetingService(config)
        result = service._connect_main_account()
        assert result is None

    @patch("src.services.meeting_service.EnhancedImapClient")
    def test_connect_main_account_returns_none_on_connect_failure(
        self, mock_imap_cls: MagicMock, config: MagicMock,
    ) -> None:
        """Verify _connect_main_account returns None when connect fails."""
        mock_client = MagicMock()
        mock_client.connect.return_value = False
        mock_imap_cls.return_value = mock_client
        service = MeetingService(config)
        result = service._connect_main_account()
        assert result is None

    @patch("src.services.meeting_service.MeetingCleanup")
    @patch("src.services.meeting_service.EnhancedImapClient")
    def test_cleanup_meetings_delegates(
        self,
        mock_imap_cls: MagicMock,
        mock_cleanup: MagicMock,
        config: MagicMock,
    ) -> None:
        """Verify cleanup_meetings delegates to MeetingCleanup.cleanup_old_meetings."""
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_imap_cls.return_value = mock_client

        service = MeetingService(config)
        service.cleanup_meetings()

        mock_cleanup.cleanup_old_meetings.assert_called_once_with(mock_client, config)
        mock_client.disconnect.assert_called_once()

    @patch("src.services.meeting_service.MeetingCleanup")
    @patch("src.services.meeting_service.EnhancedImapClient")
    def test_meeting_detail_delegates(
        self,
        mock_imap_cls: MagicMock,
        mock_cleanup: MagicMock,
        config: MagicMock,
    ) -> None:
        """Verify meeting_detail delegates to MeetingCleanup.show_meeting_detail_by_id."""
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_imap_cls.return_value = mock_client

        service = MeetingService(config)
        service.meeting_detail("today", "gcal:evt1")

        mock_cleanup.show_meeting_detail_by_id.assert_called_once()
        call_args = mock_cleanup.show_meeting_detail_by_id.call_args
        assert call_args[0][0] == mock_client
        assert call_args[0][1] == config
        assert call_args[0][2] == "today"
        assert call_args[0][3] == "gcal:evt1"
        mock_client.disconnect.assert_called_once()


class TestMeetingServiceListings:
    """Tests for todays_meetings and meetings."""

    @patch("src.services.meeting_service.MeetingCleanup")
    @patch("src.services.meeting_service.EnhancedImapClient")
    def test_todays_meetings_calls_list_without_interactive(
        self,
        mock_imap_cls: MagicMock,
        mock_cleanup: MagicMock,
        config: MagicMock,
    ) -> None:
        """Verify todays_meetings calls list_todays_meetings without interactive param."""
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_imap_cls.return_value = mock_client

        service = MeetingService(config)
        service.todays_meetings()

        mock_cleanup.list_todays_meetings.assert_called_once()
        call_kwargs = mock_cleanup.list_todays_meetings.call_args
        assert "interactive" not in call_kwargs.kwargs

    @patch("src.services.meeting_service.MeetingCleanup")
    @patch("src.services.meeting_service.EnhancedImapClient")
    def test_meetings_calls_list_without_interactive(
        self,
        mock_imap_cls: MagicMock,
        mock_cleanup: MagicMock,
        config: MagicMock,
    ) -> None:
        """Verify meetings calls list_todays_meetings without interactive param."""
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_imap_cls.return_value = mock_client

        from datetime import date
        mock_cleanup._parse_date.return_value = date(2026, 3, 10)

        service = MeetingService(config)
        service.meetings("10.03.2026")

        mock_cleanup.list_todays_meetings.assert_called_once()
        call_kwargs = mock_cleanup.list_todays_meetings.call_args
        assert "interactive" not in call_kwargs.kwargs
        assert call_kwargs.kwargs.get("target_date") == date(2026, 3, 10)
