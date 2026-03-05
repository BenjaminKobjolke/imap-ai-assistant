"""Tests for CommandRegistry and related dataclasses."""

from __future__ import annotations

from src.ai.command_registry import CommandDefinition, CommandParameter, CommandRegistry


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


class TestCommandRegistry:
    """Tests for CommandRegistry."""

    def test_default_commands_registered(self) -> None:
        """Verify all four default commands are registered."""
        registry = CommandRegistry()
        commands = registry.all_commands()
        names = {cmd.name for cmd in commands}
        assert names == {"add_date", "inbox_zero", "search", "todays_meetings"}

    def test_get_existing_command(self) -> None:
        """Verify get() returns the correct command."""
        registry = CommandRegistry()
        cmd = registry.get("add_date")
        assert cmd is not None
        assert cmd.name == "add_date"

    def test_get_nonexistent_command(self) -> None:
        """Verify get() returns None for unknown commands."""
        registry = CommandRegistry()
        assert registry.get("nonexistent") is None

    def test_register_custom_command(self) -> None:
        """Verify custom commands can be registered."""
        registry = CommandRegistry()
        custom = CommandDefinition(name="custom", description="Custom command")
        registry.register(custom)
        assert registry.get("custom") is not None

    def test_all_tools_returns_valid_schemas(self) -> None:
        """Verify all_tools() returns properly structured tool definitions."""
        registry = CommandRegistry()
        tools = registry.all_tools()
        assert len(tools) == 4
        for tool in tools:
            assert tool["type"] == "function"
            assert "name" in tool["function"]
            assert "parameters" in tool["function"]

    def test_all_descriptions_contains_all_commands(self) -> None:
        """Verify all_descriptions() includes all command names."""
        registry = CommandRegistry()
        desc = registry.all_descriptions()
        assert "add_date" in desc
        assert "inbox_zero" in desc
        assert "search" in desc
        assert "todays_meetings" in desc

    def test_add_date_has_required_title(self) -> None:
        """Verify add_date command has title as a required parameter."""
        registry = CommandRegistry()
        cmd = registry.get("add_date")
        assert cmd is not None
        title_param = next(p for p in cmd.parameters if p.name == "title")
        assert title_param.required is True

    def test_search_has_required_search_term(self) -> None:
        """Verify search command has search_term as a required parameter."""
        registry = CommandRegistry()
        cmd = registry.get("search")
        assert cmd is not None
        term_param = next(p for p in cmd.parameters if p.name == "search_term")
        assert term_param.required is True
