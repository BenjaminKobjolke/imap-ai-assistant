"""Tests for multi-word IMAP criteria generation."""

from __future__ import annotations

from src.search.email_search import _build_imap_criteria


class TestBuildImapCriteriaMultiWord:
    """Tests for _build_imap_criteria with multi-word terms."""

    def test_single_word_all(self) -> None:
        """Single word with field='all' produces TEXT + word."""
        criteria = _build_imap_criteria("hello", "all", None, None, None, None)

        assert criteria == ["TEXT", "hello"]

    def test_multi_word_all(self) -> None:
        """Multi-word with field='all' produces TEXT per word (implicit AND)."""
        criteria = _build_imap_criteria("yes kbk 0.1", "all", None, None, None, None)

        assert criteria == ["TEXT", "yes", "TEXT", "kbk", "TEXT", "0.1"]

    def test_multi_word_from(self) -> None:
        """Multi-word with field='from' produces FROM per word."""
        criteria = _build_imap_criteria("yes laroche", "from", None, None, None, None)

        assert criteria == ["FROM", "yes", "FROM", "laroche"]

    def test_multi_word_subject(self) -> None:
        """Multi-word with field='subject' produces SUBJECT per word."""
        criteria = _build_imap_criteria("kbk app", "subject", None, None, None, None)

        assert criteria == ["SUBJECT", "kbk", "SUBJECT", "app"]

    def test_multi_word_with_body(self) -> None:
        """Multi-word term combined with body_term produces all criteria."""
        criteria = _build_imap_criteria("yes kbk", "all", "ready", None, None, None)

        assert criteria == ["TEXT", "yes", "TEXT", "kbk", "BODY", "ready"]

    def test_no_term_with_body(self) -> None:
        """No term but body_term still produces BODY criterion."""
        criteria = _build_imap_criteria(None, "all", "budget", None, None, None)

        assert criteria == ["BODY", "budget"]

    def test_empty_term_returns_all(self) -> None:
        """Empty term with no other criteria returns ALL."""
        criteria = _build_imap_criteria("", "all", None, None, None, None)

        assert criteria == ["ALL"]
