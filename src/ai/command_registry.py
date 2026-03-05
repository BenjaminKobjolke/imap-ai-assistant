"""Registry of commands available to the AI chat mode."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CommandParameter:
    """Definition of a single parameter for an AI command."""

    name: str
    description: str
    param_type: str  # "string", "boolean", "integer"
    required: bool = False
    enum: list[str] | None = None
    default: Any = None


@dataclass
class CommandDefinition:
    """Full definition of a command the AI can invoke."""

    name: str
    description: str
    parameters: list[CommandParameter] = field(default_factory=list)

    def to_openai_tool(self) -> dict[str, Any]:
        """Convert to OpenAI function-calling tool schema."""
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param in self.parameters:
            prop: dict[str, Any] = {
                "type": param.param_type,
                "description": param.description,
            }
            if param.enum:
                prop["enum"] = param.enum
            properties[param.name] = prop
            if param.required:
                required.append(param.name)

        schema: dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": schema,
            },
        }

    def to_description_block(self) -> str:
        """Human-readable summary for the intent-detection system prompt."""
        params_desc = []
        for p in self.parameters:
            req = "required" if p.required else "optional"
            params_desc.append(f"  - {p.name} ({req}): {p.description}")
        params_text = "\n".join(params_desc) if params_desc else "  (no parameters)"
        return f"Command: {self.name}\n{self.description}\nParameters:\n{params_text}"


class CommandRegistry:
    """Registry of all commands available to the AI chat mode."""

    def __init__(self) -> None:
        self._commands: dict[str, CommandDefinition] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register the initial four commands."""
        self.register(CommandDefinition(
            name="add_date",
            description="Create a Google Calendar event",
            parameters=[
                CommandParameter(
                    "title", "Title/name of the event", "string", required=True,
                ),
                CommandParameter(
                    "date",
                    "Date for the event (DD.MM.YYYY, 'today', 'tomorrow')",
                    "string",
                ),
                CommandParameter(
                    "start_time", "Start time in HH:MM format (e.g. 14:00)", "string",
                ),
                CommandParameter(
                    "end_time", "End time in HH:MM format (e.g. 15:00)", "string",
                ),
                CommandParameter(
                    "calendar", "Calendar name or ID to create the event in", "string",
                ),
            ],
        ))
        self.register(CommandDefinition(
            name="inbox_zero",
            description="Process inbox emails interactively one by one to achieve inbox zero",
            parameters=[
                CommandParameter(
                    "unread_only", "Only process unread emails", "boolean",
                ),
            ],
        ))
        self.register(CommandDefinition(
            name="search",
            description="Search emails by term with optional filters",
            parameters=[
                CommandParameter(
                    "search_term", "The search term or query", "string", required=True,
                ),
                CommandParameter(
                    "body_term", "Additional body text filter", "string",
                ),
                CommandParameter(
                    "date", "Exact date filter (DD.MM.YYYY)", "string",
                ),
                CommandParameter(
                    "date_after", "Only emails after this date (DD.MM.YYYY)", "string",
                ),
                CommandParameter(
                    "date_before", "Only emails before this date (DD.MM.YYYY)", "string",
                ),
                CommandParameter(
                    "path", "Specific IMAP folder to search in", "string",
                ),
            ],
        ))
        self.register(CommandDefinition(
            name="todays_meetings",
            description="List today's meetings with start and end times",
            parameters=[],
        ))

    def register(self, command: CommandDefinition) -> None:
        """Register a command definition."""
        self._commands[command.name] = command

    def get(self, name: str) -> CommandDefinition | None:
        """Get a command by name."""
        return self._commands.get(name)

    def all_commands(self) -> list[CommandDefinition]:
        """Return all registered commands."""
        return list(self._commands.values())

    def all_tools(self) -> list[dict[str, Any]]:
        """Return all commands as OpenAI tool definitions."""
        return [cmd.to_openai_tool() for cmd in self._commands.values()]

    def all_descriptions(self) -> str:
        """Return all commands as a human-readable block for the intent prompt."""
        return "\n\n".join(
            cmd.to_description_block() for cmd in self._commands.values()
        )
