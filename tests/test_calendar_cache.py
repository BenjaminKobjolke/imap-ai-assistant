"""Tests for CalendarCache in SearchCache."""

from __future__ import annotations

from pathlib import Path

from src.search.search_cache import SearchCache


class TestCalendarCache:
    """Tests for save_calendars / get_calendars."""

    def test_save_and_get_calendars(self) -> None:
        """Round-trip: save calendars then read them back."""
        cache = SearchCache(Path(":memory:"))
        try:
            calendars = [
                {"name": "Work", "id": "work@group.calendar.google.com"},
                {"name": "Personal", "id": "personal@gmail.com"},
            ]
            cache.save_calendars(calendars)
            result = cache.get_calendars()

            assert len(result) == 2
            ids = {c["id"] for c in result}
            assert "work@group.calendar.google.com" in ids
            assert "personal@gmail.com" in ids
        finally:
            cache.close()

    def test_save_calendars_replaces_all(self) -> None:
        """Saving new calendars completely replaces the previous set."""
        cache = SearchCache(Path(":memory:"))
        try:
            cache.save_calendars([
                {"name": "Old", "id": "old@calendar"},
            ])
            cache.save_calendars([
                {"name": "New", "id": "new@calendar"},
            ])
            result = cache.get_calendars()

            assert len(result) == 1
            assert result[0]["id"] == "new@calendar"
            assert result[0]["name"] == "New"
        finally:
            cache.close()

    def test_get_calendars_empty(self) -> None:
        """Empty database returns an empty list."""
        cache = SearchCache(Path(":memory:"))
        try:
            result = cache.get_calendars()
            assert result == []
        finally:
            cache.close()

    def test_save_calendars_skips_entries_without_id(self) -> None:
        """Entries with empty or missing 'id' are filtered out."""
        cache = SearchCache(Path(":memory:"))
        try:
            cache.save_calendars([
                {"name": "Good", "id": "good@calendar"},
                {"name": "Bad", "id": ""},
                {"name": "Missing"},
            ])
            result = cache.get_calendars()

            assert len(result) == 1
            assert result[0]["id"] == "good@calendar"
        finally:
            cache.close()
