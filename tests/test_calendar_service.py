"""Tests for CalendarService, CalendarServiceInteractive, and CalendarServiceAI."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.config.settings import ConfigManager
from src.services.calendar_service import (
    CalendarService,
    CalendarServiceAI,
    CalendarServiceInteractive,
)


@pytest.fixture()
def config() -> MagicMock:
    """Create a mock ConfigManager."""
    mock = MagicMock(spec=ConfigManager)
    mock.add_date_calendar_id = "cal123"
    mock.add_date_calendar_name = "My Calendar"
    return mock


class TestCalendarServiceBase:
    """Tests for shared base class methods."""

    def test_add_date_raises_not_implemented(self, config: MagicMock) -> None:
        """Verify base class add_date raises NotImplementedError."""
        service = CalendarService(config)
        with pytest.raises(NotImplementedError):
            service.add_date(["Test"])

    def test_resolve_calendar_query_raises_not_implemented(self, config: MagicMock) -> None:
        """Verify base class _resolve_calendar_query raises NotImplementedError."""
        service = CalendarService(config)
        with pytest.raises(NotImplementedError):
            service._resolve_calendar_query(MagicMock(), "query")


class TestCalendarServiceAI:
    """Tests for CalendarServiceAI."""

    @patch("src.calendar.google_calendar_client.GoogleCalendarClient.from_config")
    def test_add_date_skips_undo_prompt(
        self,
        mock_from_config: MagicMock,
        config: MagicMock,
    ) -> None:
        """Verify AI variant creates event without undo prompt."""
        service = CalendarServiceAI(config)

        mock_gcal = MagicMock()
        mock_gcal.create_event.return_value = "evt_abc"
        mock_from_config.return_value = mock_gcal

        with patch("builtins.print") as mock_print:
            service.add_date(["Meeting", "05.03.2026", "9-10"])

        mock_gcal.create_event.assert_called_once()
        mock_gcal.delete_event_by_id.assert_not_called()
        mock_print.assert_any_call("Created: Meeting on 05.03.2026 09:00-10:00 (My Calendar)")

    def test_resolve_calendar_query_auto_picks_first(self, config: MagicMock) -> None:
        """Verify AI variant auto-picks the first matching calendar."""
        service = CalendarServiceAI(config)
        mock_gcal = MagicMock()
        mock_gcal.list_calendars.return_value = [
            {"summary": "Work Calendar", "id": "work123"},
            {"summary": "Work Meetings", "id": "work456"},
        ]

        with patch("builtins.print"):
            result = service._resolve_calendar_query(mock_gcal, "work")

        assert result == "work123"

    def test_resolve_calendar_query_no_match(self, config: MagicMock) -> None:
        """Verify AI variant returns None when no calendar matches."""
        service = CalendarServiceAI(config)
        mock_gcal = MagicMock()
        mock_gcal.list_calendars.return_value = [
            {"summary": "Personal", "id": "personal123"},
        ]

        with patch("builtins.print"):
            result = service._resolve_calendar_query(mock_gcal, "work")

        assert result is None


class TestCalendarServiceInteractive:
    """Tests for CalendarServiceInteractive."""

    @patch("src.services.calendar_service.SchedulerChoice")
    @patch("src.calendar.google_calendar_client.GoogleCalendarClient.from_config")
    def test_add_date_includes_undo_prompt(
        self,
        mock_from_config: MagicMock,
        mock_choice_cls: MagicMock,
        config: MagicMock,
    ) -> None:
        """Verify Interactive variant shows undo prompt after creating event."""
        service = CalendarServiceInteractive(config)

        mock_gcal = MagicMock()
        mock_gcal.create_event.return_value = "evt_abc"
        mock_from_config.return_value = mock_gcal

        mock_choice_cls.return_value.choose.return_value = "keep"

        service.add_date(["Meeting", "05.03.2026", "9-10"])

        mock_choice_cls.assert_called_once()
        mock_gcal.create_event.assert_called_once()

    @patch("builtins.input", return_value="1")
    def test_resolve_calendar_query_interactive_picker(
        self,
        mock_input: MagicMock,
        config: MagicMock,
    ) -> None:
        """Verify Interactive variant uses input for multiple matches."""
        service = CalendarServiceInteractive(config)
        mock_gcal = MagicMock()
        mock_gcal.list_calendars.return_value = [
            {"summary": "Work Calendar", "id": "work123"},
            {"summary": "Work Meetings", "id": "work456"},
        ]

        with patch("builtins.print"):
            result = service._resolve_calendar_query(mock_gcal, "work")

        assert result == "work123"
        mock_input.assert_called_once()
