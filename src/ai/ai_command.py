"""Decorator for auto-registering AI chat commands."""

from __future__ import annotations

from collections.abc import Callable

from src.ai.command_registry import CommandDefinition, CommandParameter

Param = CommandParameter


def ai_command(
    name: str,
    description: str,
    params: list[CommandParameter] | None = None,
) -> Callable:
    """Decorator that attaches a CommandDefinition to a handler method."""
    cmd = CommandDefinition(
        name=name,
        description=description,
        parameters=params or [],
    )

    def decorator(fn: Callable) -> Callable:
        fn._ai_command = cmd  # type: ignore[attr-defined]
        return fn

    return decorator
