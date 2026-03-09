"""Tests for _parse_add_date_args HH:MM time parsing."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from src.services.calendar_service import CalendarServiceInteractive


def _make_setup() -> CalendarServiceInteractive:
    """Create a CalendarServiceInteractive with a minimal mock config."""
    return CalendarServiceInteractive(MagicMock())


class TestParseAddDateArgs:
    """Unit tests for CalendarService._parse_add_date_args."""

    def test_bare_hour(self) -> None:
        """Bare hour '14' → start=14:00, end=15:00."""
        setup = _make_setup()
        result = setup._parse_add_date_args(["T", "14"])
        assert result is not None
        title, _, start_h, start_m, end_h, end_m, _, _ = result
        assert title == "T"
        assert (start_h, start_m) == (14, 0)
        assert (end_h, end_m) == (15, 0)

    def test_hour_range(self) -> None:
        """Hour range '14-16' → start=14:00, end=16:00."""
        setup = _make_setup()
        result = setup._parse_add_date_args(["T", "14-16"])
        assert result is not None
        _, _, start_h, start_m, end_h, end_m, _, _ = result
        assert (start_h, start_m) == (14, 0)
        assert (end_h, end_m) == (16, 0)

    def test_hhmm_single(self) -> None:
        """Single HH:MM '14:30' → start=14:30, end=15:30."""
        setup = _make_setup()
        result = setup._parse_add_date_args(["T", "14:30"])
        assert result is not None
        _, _, start_h, start_m, end_h, end_m, _, _ = result
        assert (start_h, start_m) == (14, 30)
        assert (end_h, end_m) == (15, 30)

    def test_hhmm_range(self) -> None:
        """HH:MM range '09:00-19:00' → start=09:00, end=19:00."""
        setup = _make_setup()
        result = setup._parse_add_date_args(["T", "09:00-19:00"])
        assert result is not None
        _, _, start_h, start_m, end_h, end_m, _, _ = result
        assert (start_h, start_m) == (9, 0)
        assert (end_h, end_m) == (19, 0)

    def test_mixed_hour_hhmm(self) -> None:
        """Mixed format '9-17:30' → start=09:00, end=17:30."""
        setup = _make_setup()
        result = setup._parse_add_date_args(["T", "9-17:30"])
        assert result is not None
        _, _, start_h, start_m, end_h, end_m, _, _ = result
        assert (start_h, start_m) == (9, 0)
        assert (end_h, end_m) == (17, 30)

    @patch("src.services.calendar_service.datetime")
    def test_no_time_defaults(self, mock_dt: MagicMock) -> None:
        """No time argument defaults to current hour with 0 minutes."""
        mock_now = MagicMock()
        mock_now.hour = 10
        mock_dt.now.return_value = mock_now
        setup = _make_setup()
        result = setup._parse_add_date_args(["T"])
        assert result is not None
        _, _, start_h, start_m, end_h, end_m, _, _ = result
        assert (start_h, start_m) == (10, 0)
        assert (end_h, end_m) == (11, 0)

    def test_today_keyword(self) -> None:
        """Keyword 'today' resolves to today's date."""
        setup = _make_setup()
        result = setup._parse_add_date_args(["T", "today", "09:00-19:00"])
        assert result is not None
        _, event_date, start_h, start_m, end_h, end_m, _, _ = result
        assert event_date == date.today()
        assert (start_h, start_m) == (9, 0)
        assert (end_h, end_m) == (19, 0)

    def test_tomorrow_keyword(self) -> None:
        """Keyword 'tomorrow' resolves to tomorrow's date."""
        from datetime import timedelta

        setup = _make_setup()
        result = setup._parse_add_date_args(["T", "tomorrow"])
        assert result is not None
        _, event_date, _, _, _, _, _, _ = result
        assert event_date == date.today() + timedelta(days=1)

    def test_unrecognised_returns_none(self) -> None:
        """Unrecognised token returns None."""
        setup = _make_setup()
        result = setup._parse_add_date_args(["T", "abc"])
        assert result is None

    def test_full_args(self) -> None:
        """Full args: title, date, HH:MM range, @calendar."""
        setup = _make_setup()
        result = setup._parse_add_date_args(["Meeting", "05.03.2026", "09:00-17:00", "@Termine"])
        assert result is not None
        title, event_date, start_h, start_m, end_h, end_m, cal_q, all_day = result
        assert title == "Meeting"
        assert event_date == date(2026, 3, 5)
        assert (start_h, start_m) == (9, 0)
        assert (end_h, end_m) == (17, 0)
        assert cal_q == "Termine"
        assert all_day is False

    def test_allday_token(self) -> None:
        """Token 'allday' sets all_day flag and skips default time."""
        setup = _make_setup()
        result = setup._parse_add_date_args(["Conference", "27.06.2026", "allday"])
        assert result is not None
        title, event_date, start_h, start_m, end_h, end_m, cal_q, all_day = result
        assert title == "Conference"
        assert event_date == date(2026, 6, 27)
        assert all_day is True
        assert start_h is None
        assert end_h is None
