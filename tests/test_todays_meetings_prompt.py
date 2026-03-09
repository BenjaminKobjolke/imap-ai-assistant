"""Tests for list_todays_meetings output (non-interactive)."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from src.processors.meeting_cleanup import MeetingCleanup


def _make_meeting(index: int, subject: str) -> dict:
    """Create a minimal meeting dict for testing."""
    return {
        "index": index,
        "subject": subject,
        "start": datetime(2026, 3, 4, 9, 0, tzinfo=UTC),
        "end": datetime(2026, 3, 4, 10, 0, tzinfo=UTC),
        "email_message": MagicMock(),
        "ics_text": "",
        "parsed": {"organizer": "Test", "location": "Room 1"},
    }


class TestListTodaysMeetings:
    """Tests for list_todays_meetings."""

    @patch("src.processors.meeting_cleanup.list_meetings")
    @patch.object(MeetingCleanup, "get_todays_meetings")
    def test_calls_list_meetings_with_empty_result(
        self,
        mock_get: MagicMock,
        mock_list: MagicMock,
    ) -> None:
        """Should call list_meetings even when meetings list is empty."""
        mock_get.return_value = []
        client = MagicMock()
        config = MagicMock()

        MeetingCleanup.list_todays_meetings(client, config)

        mock_list.assert_called_once()

    @patch("src.processors.meeting_cleanup.list_meetings")
    @patch.object(MeetingCleanup, "get_todays_meetings")
    def test_calls_list_meetings_with_results(
        self,
        mock_get: MagicMock,
        mock_list: MagicMock,
    ) -> None:
        """Should pass meetings to list_meetings for display."""
        from datetime import date

        meetings = [_make_meeting(1, "Standup"), _make_meeting(2, "Retro")]
        mock_get.return_value = meetings
        client = MagicMock()
        config = MagicMock()

        MeetingCleanup.list_todays_meetings(client, config)

        mock_list.assert_called_once_with(meetings, date.today())

    @patch("src.processors.meeting_cleanup.list_meetings")
    @patch.object(MeetingCleanup, "get_todays_meetings")
    def test_no_interactive_prompt(
        self,
        mock_get: MagicMock,
        mock_list: MagicMock,
    ) -> None:
        """list_todays_meetings should not accept interactive parameter."""
        meetings = [_make_meeting(1, "Standup")]
        mock_get.return_value = meetings
        client = MagicMock()
        config = MagicMock()

        # Should not raise TypeError — no interactive param expected
        MeetingCleanup.list_todays_meetings(client, config)

        mock_list.assert_called_once()
