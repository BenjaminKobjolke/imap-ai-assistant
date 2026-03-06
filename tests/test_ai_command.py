"""Tests for the @ai_command decorator."""

from __future__ import annotations

from src.ai.ai_command import Param, ai_command
from src.ai.command_registry import CommandDefinition, CommandParameter


class TestAiCommandDecorator:
    """Tests for @ai_command decorator."""

    def test_attaches_command_definition(self) -> None:
        """Decorator stores CommandDefinition as _ai_command attr."""

        @ai_command(
            name="test_cmd",
            description="A test command",
            params=[Param("title", "The title", "string", required=True)],
        )
        def handler(self, params):
            pass

        assert hasattr(handler, "_ai_command")
        cmd = handler._ai_command
        assert isinstance(cmd, CommandDefinition)
        assert cmd.name == "test_cmd"
        assert cmd.description == "A test command"
        assert len(cmd.parameters) == 1
        assert cmd.parameters[0].name == "title"
        assert cmd.parameters[0].required is True

    def test_no_params(self) -> None:
        """Decorator works with empty params list."""

        @ai_command(name="simple", description="Simple command")
        def handler(self, params):
            pass

        assert handler._ai_command.name == "simple"
        assert handler._ai_command.parameters == []

    def test_param_is_command_parameter(self) -> None:
        """Param is an alias for CommandParameter."""
        p = Param("x", "desc", "string")
        assert isinstance(p, CommandParameter)

    def test_decorated_function_still_callable(self) -> None:
        """Decorator does not change the function behavior."""

        @ai_command(name="noop", description="noop")
        def handler(self, params):
            return "ok"

        assert handler(None, {}) == "ok"
