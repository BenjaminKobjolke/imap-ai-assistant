"""Tests for MeetingService, MeetingServiceInteractive, and MeetingServiceAI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.config.settings import ConfigManager
from src.services.meeting_service import (
    MeetingService,
    MeetingServiceAI,
    MeetingServiceInteractive,
)


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

    def test_todays_meetings_raises_not_implemented(self, config: MagicMock) -> None:
        """Verify base class todays_meetings raises NotImplementedError."""
        service = MeetingService(config)
        with pytest.raises(NotImplementedError):
            service.todays_meetings()

    def test_meetings_raises_not_implemented(self, config: MagicMock) -> None:
        """Verify base class meetings raises NotImplementedError."""
        service = MeetingService(config)
        with pytest.raises(NotImplementedError):
            service.meetings("today")

    def test_connect_main_account_returns_none_on_missing_config(
        self, config: MagicMock,
    ) -> None:
        """Verify _connect_main_account returns None when no account configured."""
        config.get_first_account.return_value = None
        service = MeetingServiceInteractive(config)
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
        service = MeetingServiceInteractive(config)
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

        service = MeetingServiceInteractive(config)
        service.cleanup_meetings()

        mock_cleanup.cleanup_old_meetings.assert_called_once_with(mock_client, config)
        mock_client.disconnect.assert_called_once()

    @patch("src.services.meeting_service.MeetingCleanup")
    @patch("src.services.meeting_service.EnhancedImapClient")
    def test_todays_meeting_detail_delegates(
        self,
        mock_imap_cls: MagicMock,
        mock_cleanup: MagicMock,
        config: MagicMock,
    ) -> None:
        """Verify todays_meeting_detail delegates to MeetingCleanup.show_meeting_detail."""
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_imap_cls.return_value = mock_client

        service = MeetingServiceInteractive(config)
        service.todays_meeting_detail(3)

        mock_cleanup.show_meeting_detail.assert_called_once_with(mock_client, config, 3)
        mock_client.disconnect.assert_called_once()


class TestMeetingServiceInteractive:
    """Tests for MeetingServiceInteractive."""

    @patch("src.services.meeting_service.MeetingCleanup")
    @patch("src.services.meeting_service.EnhancedImapClient")
    def test_todays_meetings_passes_interactive_true(
        self,
        mock_imap_cls: MagicMock,
        mock_cleanup: MagicMock,
        config: MagicMock,
    ) -> None:
        """Verify todays_meetings passes interactive=True."""
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_imap_cls.return_value = mock_client

        service = MeetingServiceInteractive(config)
        service.todays_meetings()

        call_kwargs = mock_cleanup.list_todays_meetings.call_args
        assert call_kwargs.kwargs.get("interactive") is True

    @patch("src.services.meeting_service.MeetingCleanup")
    @patch("src.services.meeting_service.EnhancedImapClient")
    def test_meetings_passes_interactive_true(
        self,
        mock_imap_cls: MagicMock,
        mock_cleanup: MagicMock,
        config: MagicMock,
    ) -> None:
        """Verify meetings passes interactive=True."""
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_imap_cls.return_value = mock_client

        from datetime import date
        mock_cleanup._parse_date.return_value = date(2026, 3, 10)

        service = MeetingServiceInteractive(config)
        service.meetings("10.03.2026")

        call_kwargs = mock_cleanup.list_todays_meetings.call_args
        assert call_kwargs.kwargs.get("interactive") is True
        assert call_kwargs.kwargs.get("target_date") == date(2026, 3, 10)


class TestMeetingServiceAI:
    """Tests for MeetingServiceAI."""

    @patch("src.services.meeting_service.MeetingCleanup")
    @patch("src.services.meeting_service.EnhancedImapClient")
    def test_todays_meetings_passes_interactive_false(
        self,
        mock_imap_cls: MagicMock,
        mock_cleanup: MagicMock,
        config: MagicMock,
    ) -> None:
        """Verify todays_meetings passes interactive=False."""
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_imap_cls.return_value = mock_client

        service = MeetingServiceAI(config)
        service.todays_meetings()

        call_kwargs = mock_cleanup.list_todays_meetings.call_args
        assert call_kwargs.kwargs.get("interactive") is False

    @patch("src.services.meeting_service.MeetingCleanup")
    @patch("src.services.meeting_service.EnhancedImapClient")
    def test_meetings_passes_interactive_false(
        self,
        mock_imap_cls: MagicMock,
        mock_cleanup: MagicMock,
        config: MagicMock,
    ) -> None:
        """Verify meetings passes interactive=False."""
        mock_client = MagicMock()
        mock_client.connect.return_value = True
        mock_imap_cls.return_value = mock_client

        from datetime import date
        mock_cleanup._parse_date.return_value = date(2026, 3, 10)

        service = MeetingServiceAI(config)
        service.meetings("10.03.2026")

        call_kwargs = mock_cleanup.list_todays_meetings.call_args
        assert call_kwargs.kwargs.get("interactive") is False
        assert call_kwargs.kwargs.get("target_date") == date(2026, 3, 10)
