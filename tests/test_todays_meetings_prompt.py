"""Tests for interactive meeting selection after --todays-meetings list."""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, call, patch

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


class TestListTodaysMeetingsPrompt:
    """Tests for the interactive prompt in list_todays_meetings."""

    @patch("src.processors.meeting_cleanup._show_detail_fn")
    @patch("src.processors.meeting_cleanup.SchedulerChoice")
    @patch("src.processors.meeting_cleanup.list_meetings")
    @patch.object(MeetingCleanup, "get_todays_meetings")
    def test_no_prompt_when_no_meetings(
        self,
        mock_get: MagicMock,
        mock_list: MagicMock,
        mock_choice_cls: MagicMock,
        mock_detail: MagicMock,
    ) -> None:
        """Should not show prompt when meetings list is empty."""
        mock_get.return_value = []
        client = MagicMock()
        config = MagicMock()

        MeetingCleanup.list_todays_meetings(client, config)

        mock_list.assert_called_once()
        mock_choice_cls.assert_not_called()
        mock_detail.assert_not_called()

    @patch("src.processors.meeting_cleanup._show_detail_fn")
    @patch("src.processors.meeting_cleanup.SchedulerChoice")
    @patch("src.processors.meeting_cleanup.list_meetings")
    @patch.object(MeetingCleanup, "get_todays_meetings")
    def test_quit_exits_without_showing_detail(
        self,
        mock_get: MagicMock,
        mock_list: MagicMock,
        mock_choice_cls: MagicMock,
        mock_detail: MagicMock,
    ) -> None:
        """Selecting 'quit' should exit loop without calling show_detail."""
        meetings = [_make_meeting(1, "Standup")]
        mock_get.return_value = meetings

        mock_instance = MagicMock()
        mock_instance.choose.return_value = "quit"
        mock_choice_cls.return_value = mock_instance

        client = MagicMock()
        config = MagicMock()

        MeetingCleanup.list_todays_meetings(client, config)

        mock_choice_cls.assert_called_once()
        mock_detail.assert_not_called()

    @patch("src.processors.meeting_cleanup._show_detail_fn")
    @patch("src.processors.meeting_cleanup.SchedulerChoice")
    @patch("src.processors.meeting_cleanup.list_meetings")
    @patch.object(MeetingCleanup, "get_todays_meetings")
    def test_selecting_meeting_shows_detail(
        self,
        mock_get: MagicMock,
        mock_list: MagicMock,
        mock_choice_cls: MagicMock,
        mock_detail: MagicMock,
    ) -> None:
        """Selecting a meeting index should call show_detail with that meeting."""
        meetings = [_make_meeting(1, "Standup"), _make_meeting(2, "Retro")]
        mock_get.return_value = meetings

        mock_instance = MagicMock()
        mock_instance.choose.side_effect = ["2", "quit"]
        mock_choice_cls.return_value = mock_instance

        client = MagicMock()
        config = MagicMock()

        MeetingCleanup.list_todays_meetings(client, config)

        mock_detail.assert_called_once_with(meetings[1])

    @patch("src.processors.meeting_cleanup._show_detail_fn")
    @patch("src.processors.meeting_cleanup.SchedulerChoice")
    @patch("src.processors.meeting_cleanup.list_meetings")
    @patch.object(MeetingCleanup, "get_todays_meetings")
    def test_loop_allows_multiple_selections(
        self,
        mock_get: MagicMock,
        mock_list: MagicMock,
        mock_choice_cls: MagicMock,
        mock_detail: MagicMock,
    ) -> None:
        """User can inspect multiple meetings before quitting."""
        meetings = [_make_meeting(1, "Standup"), _make_meeting(2, "Retro")]
        mock_get.return_value = meetings

        mock_instance = MagicMock()
        mock_instance.choose.side_effect = ["1", "2", "quit"]
        mock_choice_cls.return_value = mock_instance

        client = MagicMock()
        config = MagicMock()

        MeetingCleanup.list_todays_meetings(client, config)

        assert mock_detail.call_count == 2
        mock_detail.assert_has_calls([
            call(meetings[0]),
            call(meetings[1]),
        ])

    @patch("src.processors.meeting_cleanup._show_detail_fn")
    @patch("src.processors.meeting_cleanup.SchedulerChoice")
    @patch("src.processors.meeting_cleanup.list_meetings")
    @patch.object(MeetingCleanup, "get_todays_meetings")
    def test_prompt_includes_all_meetings_and_quit(
        self,
        mock_get: MagicMock,
        mock_list: MagicMock,
        mock_choice_cls: MagicMock,
        mock_detail: MagicMock,
    ) -> None:
        """SchedulerChoice should receive all meetings plus a Quit option."""
        meetings = [_make_meeting(1, "Standup"), _make_meeting(2, "Retro")]
        mock_get.return_value = meetings

        mock_instance = MagicMock()
        mock_instance.choose.return_value = "quit"
        mock_choice_cls.return_value = mock_instance

        client = MagicMock()
        config = MagicMock()

        MeetingCleanup.list_todays_meetings(client, config)

        args, _kwargs = mock_choice_cls.call_args
        prompt = args[0]
        choices = args[1]

        assert prompt == ""
        assert len(choices) == 3  # 2 meetings + Quit
        assert choices[0] == ("1. Standup", "1")
        assert choices[1] == ("2. Retro", "2")
        assert choices[2] == ("Quit", "quit")
