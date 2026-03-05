"""Tests for multi-word AND-search in SearchCache."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

from src.search.search_cache import SearchCache, _build_term_conditions


# ===================================================================
# _build_term_conditions unit tests
# ===================================================================


class TestBuildTermConditions:
    """Tests for the _build_term_conditions helper."""

    def test_single_word_all(self) -> None:
        """Single word with field='all' produces one condition across 5 columns."""
        conds, params = _build_term_conditions("hello", "all")

        assert len(conds) == 1
        assert "from_address LIKE ?" in conds[0]
        assert "subject LIKE ?" in conds[0]
        assert params == ["%hello%"] * 5

    def test_multi_word_all(self) -> None:
        """Multi-word with field='all' produces one condition per word, all AND-able."""
        conds, params = _build_term_conditions("yes kbk 0.1", "all")

        assert len(conds) == 3
        # Each condition has 5 params (one per column)
        assert len(params) == 15
        assert params[0] == "%yes%"
        assert params[5] == "%kbk%"
        assert params[10] == "%0.1%"

    def test_single_word_from(self) -> None:
        """Single word with field='from' uses from_address and from_name."""
        conds, params = _build_term_conditions("alice", "from")

        assert len(conds) == 1
        assert "from_address LIKE ?" in conds[0]
        assert "from_name LIKE ?" in conds[0]
        assert "subject" not in conds[0]
        assert params == ["%alice%", "%alice%"]

    def test_multi_word_subject(self) -> None:
        """Multi-word with field='subject' produces one condition per word."""
        conds, params = _build_term_conditions("project update", "subject")

        assert len(conds) == 2
        assert params == ["%project%", "%update%"]

    def test_empty_string_returns_empty(self) -> None:
        """Empty string produces no conditions."""
        conds, params = _build_term_conditions("", "all")

        assert conds == []
        assert params == []

    def test_whitespace_only_returns_empty(self) -> None:
        """Whitespace-only string produces no conditions."""
        conds, params = _build_term_conditions("   ", "all")

        assert conds == []
        assert params == []


# ===================================================================
# Integration: SearchCache.search() with multi-word terms
# ===================================================================


class TestSearchCacheMultiWord:
    """Integration tests: multi-word search against an in-memory SQLite cache."""

    def _make_cache(self) -> SearchCache:
        """Create an in-memory SearchCache with test data."""
        cache = SearchCache(Path(":memory:"))
        conn = cache._conn

        conn.execute(
            "INSERT INTO email_cache "
            "(message_id, folder, from_address, from_name, to_address, to_name, "
            " subject, date_str, date_iso, body_preview, cached_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "1", "INBOX",
                "s.laroche@yes-werbeagentur.de", "S. Laroche",
                "me@example.com", "Me",
                "Fwd: KBK Videothek App 0.1.20 (0.1.20) for iOS",
                "Wed, 05 Mar 2026", "2026-03-05",
                "Build is ready for testing",
                "2026-03-05T12:00:00",
            ),
        )
        conn.execute(
            "INSERT INTO email_cache "
            "(message_id, folder, from_address, from_name, to_address, to_name, "
            " subject, date_str, date_iso, body_preview, cached_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "2", "INBOX",
                "alice@example.com", "Alice",
                "me@example.com", "Me",
                "Meeting tomorrow",
                "Tue, 04 Mar 2026", "2026-03-04",
                "Let us meet at 10am",
                "2026-03-04T12:00:00",
            ),
        )
        conn.commit()
        return cache

    def test_cross_field_match(self) -> None:
        """'yes kbk 0.1' matches when words span from-address and subject."""
        cache = self._make_cache()
        try:
            results = cache.search(term="yes kbk 0.1", field="all")

            assert len(results) == 1
            assert results[0]["message_id"] == "1"
        finally:
            cache.close()

    def test_single_word_still_works(self) -> None:
        """Single-word search still matches as before."""
        cache = self._make_cache()
        try:
            results = cache.search(term="alice", field="all")

            assert len(results) == 1
            assert results[0]["message_id"] == "2"
        finally:
            cache.close()

    def test_no_match_when_word_missing(self) -> None:
        """All words must match — missing word means no result."""
        cache = self._make_cache()
        try:
            results = cache.search(term="yes kbk android", field="all")

            assert len(results) == 0
        finally:
            cache.close()

    def test_field_specific_multi_word(self) -> None:
        """Multi-word with field='from' only checks from columns."""
        cache = self._make_cache()
        try:
            results = cache.search(term="yes laroche", field="from")

            assert len(results) == 1
            assert results[0]["message_id"] == "1"
        finally:
            cache.close()

    def test_field_specific_no_cross_field_match(self) -> None:
        """field='subject' won't match words that only appear in from."""
        cache = self._make_cache()
        try:
            # "yes" is only in the from address, not in the subject
            results = cache.search(term="yes kbk", field="subject")

            assert len(results) == 0
        finally:
            cache.close()
