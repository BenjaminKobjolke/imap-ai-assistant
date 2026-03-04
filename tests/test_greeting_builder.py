"""Tests for GreetingBuilder."""

from __future__ import annotations

from datetime import datetime

from src.processors.greeting_builder import GreetingBuilder, SalutationInfo


def _info(salutation: str = "Herr Mueller", *, is_formal: bool = True, skip: bool = False) -> SalutationInfo:
    """Create a test SalutationInfo."""
    return SalutationInfo(email_address="test@example.com", salutation=salutation, is_formal=is_formal, skip_greeting=skip)


def test_morning_greeting_formal() -> None:
    """Before 10:00 uses 'Guten Morgen'."""
    result = GreetingBuilder.build_greeting(_info(), now=datetime(2026, 1, 1, 8, 0))
    assert result == "Guten Morgen Herr Mueller"


def test_default_greeting_formal() -> None:
    """At or after 10:00 uses 'Hallo'."""
    result = GreetingBuilder.build_greeting(_info(), now=datetime(2026, 1, 1, 10, 0))
    assert result == "Hallo Herr Mueller"


def test_afternoon_greeting_informal() -> None:
    """Informal greeting still uses time-based prefix."""
    result = GreetingBuilder.build_greeting(
        _info("Benjamin", is_formal=False), now=datetime(2026, 1, 1, 14, 0),
    )
    assert result == "Hallo Benjamin"


def test_skip_greeting_returns_empty() -> None:
    """When skip_greeting is True, returns empty string."""
    result = GreetingBuilder.build_greeting(_info(skip=True), now=datetime(2026, 1, 1, 9, 0))
    assert result == ""


def test_empty_salutation_greeting_only_prefix() -> None:
    """When salutation is empty, returns just the prefix."""
    result = GreetingBuilder.build_greeting(_info(""), now=datetime(2026, 1, 1, 11, 0))
    assert result == "Hallo"


def test_morning_boundary_at_10() -> None:
    """Exactly at 10:00 should use default greeting, not morning."""
    result = GreetingBuilder.build_greeting(_info(), now=datetime(2026, 1, 1, 10, 0))
    assert result == "Hallo Herr Mueller"


def test_morning_boundary_at_9_59() -> None:
    """At 09:59 should still use morning greeting."""
    result = GreetingBuilder.build_greeting(_info(), now=datetime(2026, 1, 1, 9, 59))
    assert result == "Guten Morgen Herr Mueller"
