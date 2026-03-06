"""Tests for Google Calendar integration in get_todays_meetings."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from src.processors.meeting_cleanup import (
    MeetingCleanup,
    _gcal_event_to_meeting_dict,
    _is_duplicate,
)


def _make_gcal_event(
    summary: str,
    start_hour: int = 9,
    end_hour: int = 10,
    *,
    all_day: bool = False,
    event_id: str = "evt1",
) -> dict:
    """Create a minimal Google Calendar API event dict."""
    dt_date = date(2026, 3, 6)
    if all_day:
        return {
            "id": event_id,
            "summary": summary,
            "start": {"date": str(dt_date)},
            "end": {"date": str(dt_date + timedelta(days=1))},
        }

    tz = timezone(timedelta(hours=1))
    start = datetime(dt_date.year, dt_date.month, dt_date.day, start_hour, tzinfo=tz)
    end = datetime(dt_date.year, dt_date.month, dt_date.day, end_hour, tzinfo=tz)
    return {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
        "organizer": {"displayName": "Tester", "email": "test@example.com"},
        "location": "Room A",
    }


def _make_imap_meeting(subject: str, start_hour: int = 9, end_hour: int = 10) -> dict:
    """Create a minimal IMAP meeting dict."""
    tz = timezone(timedelta(hours=1))
    start = datetime(2026, 3, 6, start_hour, tzinfo=tz)
    end = datetime(2026, 3, 6, end_hour, tzinfo=tz)
    return {
        "start": start,
        "end": end,
        "subject": subject,
        "email_message": MagicMock(),
        "ics_text": "VEVENT",
        "parsed": {"dtstart": start, "dtend": end, "rrule": None, "organizer": "O", "location": "L"},
        "source": "imap",
    }


class TestGcalEventToMeetingDict:
    """Tests for _gcal_event_to_meeting_dict."""

    def test_timed_event_converts(self) -> None:
        event = _make_gcal_event("Standup")
        result = _gcal_event_to_meeting_dict(event, "My Cal")

        assert result is not None
        assert result["subject"] == "Standup"
        assert result["source"] == "gcal"
        assert result["calendar_name"] == "My Cal"
        assert result["email_message"] is None
        assert result["ics_text"] is None
        assert result["parsed"]["organizer"] == "Tester"
        assert result["parsed"]["location"] == "Room A"

    def test_all_day_event_skipped(self) -> None:
        event = _make_gcal_event("Holiday", all_day=True)
        result = _gcal_event_to_meeting_dict(event, "Cal")
        assert result is None

    def test_no_title_gets_placeholder(self) -> None:
        event = _make_gcal_event("Standup")
        del event["summary"]
        result = _gcal_event_to_meeting_dict(event, "Cal")
        assert result is not None
        assert result["subject"] == "(no title)"


class TestIsDuplicate:
    """Tests for _is_duplicate."""

    def test_same_subject_same_time(self) -> None:
        imap = _make_imap_meeting("Standup")
        gcal_event = _make_gcal_event("Standup")
        gcal = _gcal_event_to_meeting_dict(gcal_event, "Cal")
        assert _is_duplicate(imap, gcal)

    def test_different_time_not_duplicate(self) -> None:
        imap = _make_imap_meeting("Standup", start_hour=9)
        gcal_event = _make_gcal_event("Standup", start_hour=14)
        gcal = _gcal_event_to_meeting_dict(gcal_event, "Cal")
        assert not _is_duplicate(imap, gcal)

    def test_different_subject_not_duplicate(self) -> None:
        imap = _make_imap_meeting("Standup")
        gcal_event = _make_gcal_event("Retro")
        gcal = _gcal_event_to_meeting_dict(gcal_event, "Cal")
        assert not _is_duplicate(imap, gcal)

    def test_partial_subject_match(self) -> None:
        """GCal subject containing IMAP subject should match."""
        imap = _make_imap_meeting("Standup")
        gcal_event = _make_gcal_event("Standup (weekly)")
        gcal = _gcal_event_to_meeting_dict(gcal_event, "Cal")
        assert _is_duplicate(imap, gcal)

    def test_within_5_min_window(self) -> None:
        """Events within 5 minutes should still match."""
        tz = timezone(timedelta(hours=1))
        imap = _make_imap_meeting("Standup", start_hour=9)
        gcal_m = {
            "start": datetime(2026, 3, 6, 9, 4, tzinfo=tz),
            "subject": "Standup",
        }
        assert _is_duplicate(imap, gcal_m)


class TestMergeGcalEvents:
    """Tests for get_todays_meetings with gcal_client."""

    @patch.object(MeetingCleanup, "_get_ics_data", return_value=None)
    def test_gcal_only_meetings_appear(self, _mock_ics: MagicMock) -> None:
        """GCal meetings should appear when IMAP has no meetings."""
        client = MagicMock()
        client.client.get_all_messages.return_value = []

        config = MagicMock()
        config.meetings_folder = "Meetings"
        config.free_check_calendar_ids = []

        gcal_client = MagicMock()
        gcal_client.calendar_id = "primary"
        gcal_client.list_calendars.return_value = [{"id": "primary", "summary": "My Cal"}]
        gcal_client.list_events_in_range.return_value = [
            _make_gcal_event("GCal Standup", event_id="g1"),
        ]

        result = MeetingCleanup.get_todays_meetings(
            client, config, target_date=date(2026, 3, 6), gcal_client=gcal_client,
        )

        assert len(result) == 1
        assert result[0]["subject"] == "GCal Standup"
        assert result[0]["source"] == "gcal"
        assert result[0]["index"] == 1

    @patch.object(MeetingCleanup, "_get_ics_data", return_value=None)
    def test_no_gcal_client_returns_imap_only(self, _mock_ics: MagicMock) -> None:
        """Without gcal_client, only IMAP meetings are returned."""
        client = MagicMock()
        client.client.get_all_messages.return_value = []

        config = MagicMock()
        config.meetings_folder = "Meetings"

        result = MeetingCleanup.get_todays_meetings(
            client, config, target_date=date(2026, 3, 6), gcal_client=None,
        )
        assert result == []

    @patch.object(MeetingCleanup, "_get_ics_data", return_value=None)
    def test_deduplication_marks_both(self, _mock_ics: MagicMock) -> None:
        """A meeting existing in both IMAP and GCal should be marked 'both'."""
        client = MagicMock()
        client.client.get_all_messages.return_value = []

        config = MagicMock()
        config.meetings_folder = "Meetings"
        config.free_check_calendar_ids = []

        # Pre-populate IMAP meetings via patching
        imap_meeting = _make_imap_meeting("Standup")
        gcal_client = MagicMock()
        gcal_client.calendar_id = "primary"
        gcal_client.list_calendars.return_value = [{"id": "primary", "summary": "My Cal"}]
        gcal_client.list_events_in_range.return_value = [
            _make_gcal_event("Standup", event_id="g1"),
        ]

        with patch.object(
            MeetingCleanup,
            "_merge_gcal_events",
            wraps=MeetingCleanup._merge_gcal_events,
        ):
            # Directly test _merge_gcal_events
            merged = MeetingCleanup._merge_gcal_events(
                [imap_meeting], gcal_client, config, date(2026, 3, 6),
            )

        assert len(merged) == 1
        assert merged[0]["source"] == "both"

    @patch.object(MeetingCleanup, "_get_ics_data", return_value=None)
    def test_gcal_failure_falls_back(self, _mock_ics: MagicMock) -> None:
        """If gcal_client raises, IMAP meetings still returned."""
        client = MagicMock()
        client.client.get_all_messages.return_value = []

        config = MagicMock()
        config.meetings_folder = "Meetings"

        gcal_client = MagicMock()
        gcal_client.calendar_id = "primary"
        gcal_client.list_calendars.side_effect = RuntimeError("Auth failed")

        result = MeetingCleanup.get_todays_meetings(
            client, config, target_date=date(2026, 3, 6), gcal_client=gcal_client,
        )
        assert result == []

    @patch.object(MeetingCleanup, "_get_ics_data", return_value=None)
    def test_dedup_across_calendars(self, _mock_ics: MagicMock) -> None:
        """Same event in multiple GCal calendars should only appear once."""
        client = MagicMock()
        client.client.get_all_messages.return_value = []

        config = MagicMock()
        config.meetings_folder = "Meetings"
        config.free_check_calendar_ids = ["other-cal"]

        gcal_client = MagicMock()
        gcal_client.calendar_id = "primary"
        gcal_client.list_calendars.return_value = [
            {"id": "primary", "summary": "Main"},
            {"id": "other-cal", "summary": "Other"},
        ]
        # Same event ID in both calendars
        event = _make_gcal_event("Team Sync", event_id="shared-evt")
        gcal_client.list_events_in_range.return_value = [event]

        result = MeetingCleanup.get_todays_meetings(
            client, config, target_date=date(2026, 3, 6), gcal_client=gcal_client,
        )

        # Should appear only once despite being returned by both calendars
        assert len(result) == 1
        assert result[0]["subject"] == "Team Sync"
