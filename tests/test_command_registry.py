"""Tests for CommandRegistry and related dataclasses."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.ai.chat_handler import CommandExecutor
from src.ai.command_registry import CommandDefinition, CommandParameter, CommandRegistry
from src.processors.email_processor import EmailProcessor


class TestCommandParameter:
    """Tests for CommandParameter dataclass."""

    def test_basic_attributes(self) -> None:
        """Verify basic parameter attributes are set correctly."""
        param = CommandParameter(
            name="title",
            description="Event title",
            param_type="string",
            required=True,
        )
        assert param.name == "title"
        assert param.description == "Event title"
        assert param.param_type == "string"
        assert param.required is True
        assert param.enum is None
        assert param.default is None


class TestCommandDefinition:
    """Tests for CommandDefinition dataclass."""

    def test_to_openai_tool_with_required_params(self) -> None:
        """Verify OpenAI tool schema includes required parameters."""
        cmd = CommandDefinition(
            name="add_date",
            description="Create event",
            parameters=[
                CommandParameter("title", "Event title", "string", required=True),
                CommandParameter("date", "Event date", "string", required=False),
            ],
        )
        tool = cmd.to_openai_tool()

        assert tool["type"] == "function"
        assert tool["function"]["name"] == "add_date"
        assert tool["function"]["description"] == "Create event"
        assert "title" in tool["function"]["parameters"]["properties"]
        assert "date" in tool["function"]["parameters"]["properties"]
        assert tool["function"]["parameters"]["required"] == ["title"]

    def test_to_openai_tool_no_required_params(self) -> None:
        """Verify OpenAI tool schema omits 'required' when none are required."""
        cmd = CommandDefinition(
            name="todays_meetings",
            description="List meetings",
            parameters=[],
        )
        tool = cmd.to_openai_tool()

        assert tool["function"]["name"] == "todays_meetings"
        assert "required" not in tool["function"]["parameters"]

    def test_to_openai_tool_with_enum(self) -> None:
        """Verify enum values are included in the tool schema."""
        cmd = CommandDefinition(
            name="test",
            description="Test command",
            parameters=[
                CommandParameter(
                    "mode", "Mode", "string",
                    enum=["fast", "slow"],
                ),
            ],
        )
        tool = cmd.to_openai_tool()
        mode_prop = tool["function"]["parameters"]["properties"]["mode"]
        assert mode_prop["enum"] == ["fast", "slow"]

    def test_to_description_block(self) -> None:
        """Verify human-readable description block format."""
        cmd = CommandDefinition(
            name="search",
            description="Search emails",
            parameters=[
                CommandParameter("search_term", "Query", "string", required=True),
                CommandParameter("date", "Date filter", "string"),
            ],
        )
        block = cmd.to_description_block()

        assert "Command: search" in block
        assert "Search emails" in block
        assert "search_term (required)" in block
        assert "date (optional)" in block

    def test_to_description_block_no_params(self) -> None:
        """Verify description block for parameterless commands."""
        cmd = CommandDefinition(
            name="todays_meetings",
            description="List meetings",
            parameters=[],
        )
        block = cmd.to_description_block()
        assert "(no parameters)" in block


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def populated_registry() -> CommandRegistry:
    """Create a registry populated via CommandExecutor's @ai_command decorators."""
    registry = CommandRegistry()
    processor = MagicMock(spec=EmailProcessor)
    executor = CommandExecutor(processor)
    executor.bind_to_registry(registry)
    return registry


class TestCommandRegistry:
    """Tests for CommandRegistry populated via CommandExecutor."""

    def test_all_commands_registered(self, populated_registry: CommandRegistry) -> None:
        """Verify all eleven commands are discovered from CommandExecutor."""
        names = {cmd.name for cmd in populated_registry.all_commands()}
        assert names == {
            "add_date", "add_todo", "exit", "inbox_zero", "search",
            "todays_meetings", "meetings", "meeting_detail",
            "list_workflows", "run_workflow", "update_search_cache",
        }

    def test_get_existing_command(self, populated_registry: CommandRegistry) -> None:
        """Verify get() returns the correct command."""
        cmd = populated_registry.get("add_date")
        assert cmd is not None
        assert cmd.name == "add_date"

    def test_get_nonexistent_command(self, populated_registry: CommandRegistry) -> None:
        """Verify get() returns None for unknown commands."""
        assert populated_registry.get("nonexistent") is None

    def test_register_custom_command(self, populated_registry: CommandRegistry) -> None:
        """Verify custom commands can be registered alongside discovered ones."""
        custom = CommandDefinition(name="custom", description="Custom command")
        populated_registry.register(custom)
        assert populated_registry.get("custom") is not None

    def test_all_tools_returns_valid_schemas(self, populated_registry: CommandRegistry) -> None:
        """Verify all_tools() returns properly structured tool definitions."""
        tools = populated_registry.all_tools()
        assert len(tools) == 11
        for tool in tools:
            assert tool["type"] == "function"
            assert "name" in tool["function"]
            assert "parameters" in tool["function"]

    def test_all_descriptions_contains_all_commands(self, populated_registry: CommandRegistry) -> None:
        """Verify all_descriptions() includes all command names."""
        desc = populated_registry.all_descriptions()
        assert "add_date" in desc
        assert "inbox_zero" in desc
        assert "search" in desc
        assert "todays_meetings" in desc

    def test_add_date_has_required_title(self, populated_registry: CommandRegistry) -> None:
        """Verify add_date command has title as a required parameter."""
        cmd = populated_registry.get("add_date")
        assert cmd is not None
        title_param = next(p for p in cmd.parameters if p.name == "title")
        assert title_param.required is True

    def test_search_has_required_search_term(self, populated_registry: CommandRegistry) -> None:
        """Verify search command has search_term as a required parameter."""
        cmd = populated_registry.get("search")
        assert cmd is not None
        term_param = next(p for p in cmd.parameters if p.name == "search_term")
        assert term_param.required is True


class TestRegisterFromExecutor:
    """Tests for register_from_executor auto-discovery."""

    def test_discovers_decorated_methods(self) -> None:
        """Finds @ai_command methods and registers them."""
        from src.ai.ai_command import Param, ai_command

        class FakeExecutor:
            @ai_command(
                name="cmd_a",
                description="Command A",
                params=[Param("x", "param x", "string", required=True)],
            )
            def handle_a(self, params):
                pass

            @ai_command(name="cmd_b", description="Command B")
            def handle_b(self, params):
                pass

            def not_a_command(self):
                pass

        registry = CommandRegistry()
        executor = FakeExecutor()
        handlers = registry.register_from_executor(executor)

        assert registry.get("cmd_a") is not None
        assert registry.get("cmd_b") is not None
        assert registry.get("not_a_command") is None
        assert "cmd_a" in handlers
        assert "cmd_b" in handlers
        assert callable(handlers["cmd_a"])

    def test_handler_is_bound_to_executor(self) -> None:
        """Returned handler calls the method on the executor instance."""
        from src.ai.ai_command import ai_command

        call_log: list = []

        class FakeExecutor:
            @ai_command(name="log_cmd", description="Logs calls")
            def log_it(self, params):
                call_log.append(params)

        registry = CommandRegistry()
        executor = FakeExecutor()
        handlers = registry.register_from_executor(executor)

        handlers["log_cmd"]({"key": "value"})
        assert call_log == [{"key": "value"}]
