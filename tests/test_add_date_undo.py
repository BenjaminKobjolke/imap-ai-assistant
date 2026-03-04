"""Tests for add-date undo feature."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from src.calendar.google_calendar_client import GoogleCalendarClient
from src.processors.calendar_setup import CalendarSetup


class TestDeleteEventById:
    """Tests for GoogleCalendarClient.delete_event_by_id."""

    def test_delete_calls_api(self) -> None:
        """delete_event_by_id calls the correct Google API method."""
        client = GoogleCalendarClient()
        mock_service = MagicMock()
        client.service = mock_service
        client.calendar_id = "cal123"

        result = client.delete_event_by_id("evt_abc")

        mock_service.events().delete.assert_called_once_with(
            calendarId="cal123", eventId="evt_abc",
        )
        assert result is True

    def test_delete_returns_false_when_no_service(self) -> None:
        """delete_event_by_id returns False when service is not initialized."""
        client = GoogleCalendarClient()
        client.service = None

        result = client.delete_event_by_id("evt_abc")

        assert result is False

    def test_delete_returns_false_on_api_error(self) -> None:
        """delete_event_by_id returns False when the API raises an exception."""
        client = GoogleCalendarClient()
        mock_service = MagicMock()
        mock_service.events().delete().execute.side_effect = RuntimeError("API error")
        client.service = mock_service

        result = client.delete_event_by_id("evt_abc")

        assert result is False


class TestAddDateUndo:
    """Tests for the undo prompt after add_date event creation."""

    def _setup(self) -> tuple[CalendarSetup, MagicMock]:
        """Create a CalendarSetup with mocked config."""
        mock_config = MagicMock()
        mock_config.add_date_calendar_id = "cal123"
        mock_config.add_date_calendar_name = "My Calendar"
        return CalendarSetup(mock_config), mock_config

    @patch("src.processors.calendar_setup.SchedulerChoice")
    @patch("src.calendar.google_calendar_client.GoogleCalendarClient.from_config")
    def test_undo_deletes_event(
        self,
        mock_from_config: MagicMock,
        mock_choice_cls: MagicMock,
    ) -> None:
        """Choosing 'undo' calls delete_event_by_id and prints deletion message."""
        setup, _ = self._setup()

        mock_gcal = MagicMock(spec=GoogleCalendarClient)
        mock_gcal.create_event.return_value = "evt_abc"
        mock_gcal.delete_event_by_id.return_value = True
        mock_from_config.return_value = mock_gcal

        mock_choice_cls.return_value.choose.return_value = "undo"

        with patch("builtins.print") as mock_print:
            setup.add_date(["Meeting", "05.03.2026", "9-10"])

        mock_gcal.delete_event_by_id.assert_called_once_with("evt_abc")
        mock_print.assert_any_call("Event deleted.")

    @patch("src.processors.calendar_setup.SchedulerChoice")
    @patch("src.calendar.google_calendar_client.GoogleCalendarClient.from_config")
    def test_keep_does_not_delete(
        self,
        mock_from_config: MagicMock,
        mock_choice_cls: MagicMock,
    ) -> None:
        """Choosing 'keep' does not call delete_event_by_id."""
        setup, _ = self._setup()

        mock_gcal = MagicMock(spec=GoogleCalendarClient)
        mock_gcal.create_event.return_value = "evt_abc"
        mock_from_config.return_value = mock_gcal

        mock_choice_cls.return_value.choose.return_value = "keep"

        setup.add_date(["Meeting", "05.03.2026", "9-10"])

        mock_gcal.delete_event_by_id.assert_not_called()

    @patch("src.processors.calendar_setup.SchedulerChoice")
    @patch("src.calendar.google_calendar_client.GoogleCalendarClient.from_config")
    def test_undo_failure_prints_error(
        self,
        mock_from_config: MagicMock,
        mock_choice_cls: MagicMock,
    ) -> None:
        """When delete fails, prints failure message."""
        setup, _ = self._setup()

        mock_gcal = MagicMock(spec=GoogleCalendarClient)
        mock_gcal.create_event.return_value = "evt_abc"
        mock_gcal.delete_event_by_id.return_value = False
        mock_from_config.return_value = mock_gcal

        mock_choice_cls.return_value.choose.return_value = "undo"

        with patch("builtins.print") as mock_print:
            setup.add_date(["Meeting", "05.03.2026", "9-10"])

        mock_print.assert_any_call("Failed to delete event.")
