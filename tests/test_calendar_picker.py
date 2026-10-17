"""Tests for the shared interactive calendar picker."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

from src.config.settings import ConfigManager
from src.services.calendar_service import CalendarService


def _service() -> tuple[CalendarService, MagicMock]:
    """Build a calendar service with a spec-checked configuration mock."""
    config = MagicMock(spec=ConfigManager)
    config.accepts_meetings_calendar_id = "current"
    config.add_date_calendar_id = "current"
    return CalendarService(config), config


def test_meeting_calendar_enter_keeps_current_without_saving() -> None:
    """Keeping the current selection must not rewrite the configuration."""
    service, config = _service()
    with patch("builtins.input", return_value=""), patch("builtins.print"):
        result = service._setup_meeting_calendar(
            [{"id": "current", "summary": "Current"}], {"current": "Current"}
        )

    assert result == "current"
    config.save_setting.assert_not_called()


def test_add_date_calendar_saves_selected_id_and_name() -> None:
    """A valid selection must persist its id and display name at the add-date key."""
    service, config = _service()
    calendars = [{"id": "work", "summary": "Work"}]
    with patch("builtins.input", return_value="1"), patch("builtins.print"):
        result = service._setup_add_date_calendar(calendars, {"work": "Work"})

    assert result == "work"
    config.save_setting.assert_called_once_with(
        ["meetings", "google_calendar", "add_date_calendar"],
        {"name": "Work", "id": "work"},
    )


def test_meeting_calendar_invalid_choice_prompts_again() -> None:
    """Invalid input must leave the picker active until a valid number is chosen."""
    service, config = _service()
    calendars = [{"id": "work", "summary": "Work"}]
    with patch("builtins.input", side_effect=["invalid", "1"]) as prompt, patch(
        "builtins.print"
    ):
        result = service._setup_meeting_calendar(calendars, {"work": "Work"})

    assert result == "work"
    assert prompt.call_count == 2
    config.save_setting.assert_called_once_with(
        ["meetings", "google_calendar", "accepts_meetings_calendar"],
        {"name": "Work", "id": "work"},
    )


def test_calendar_setup_callers_share_picker_with_their_own_settings() -> None:
    """Both calendar setup steps must delegate to one picker with their own context."""
    service, config = _service()
    calendars = [{"id": "current", "summary": "Current"}]
    names = {"current": "Current"}
    with patch.object(CalendarService, "_pick_single_calendar", return_value="selected") as picker:
        assert service._setup_meeting_calendar(calendars, names) == "selected"
        assert service._setup_add_date_calendar(calendars, names) == "selected"

    assert picker.call_args_list == [
        call(
            calendars,
            names,
            "current",
            "Meeting Calendar",
            ["meetings", "google_calendar", "accepts_meetings_calendar"],
        ),
        call(
            calendars,
            names,
            "current",
            "Add-Date Calendar (default for --add-date)",
            ["meetings", "google_calendar", "add_date_calendar"],
        ),
    ]
    config.save_setting.assert_not_called()
