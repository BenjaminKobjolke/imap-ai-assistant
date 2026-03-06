# Design: Decorator-based AI command auto-registration

## Problem

Adding a new AI-accessible command requires changes in 3 separate places:
1. `CommandRegistry._register_defaults()` -- schema definition
2. `CommandExecutor.__init__` -- handler mapping dict
3. `CommandExecutor._execute_*()` -- handler method

Features added to search/browse are easily forgotten in AI mode.

## Solution

A `@ai_command` decorator that co-locates the command schema with its handler method.
The registry auto-discovers decorated methods at startup.

### New file: `src/ai/ai_command.py`

Provides:
- `Param` -- alias for `CommandParameter` (shorter for decorator use)
- `ai_command(name, description, params)` -- decorator that stores a `CommandDefinition` as `method._ai_command`

### Changes to `CommandExecutor` (`src/ai/chat_handler.py`)

- Each `_execute_*` method gets an `@ai_command(...)` decorator
- The manual `_handlers` dict in `__init__` is removed
- A `get_registered_commands()` method scans `self` for `_ai_command` decorated methods

### Changes to `CommandRegistry` (`src/ai/command_registry.py`)

- `_register_defaults()` is deleted
- New method: `register_from_executor(executor)` introspects the executor, finds all `_ai_command`-decorated methods, registers them, and builds the handler dispatch

### Changes to `ChatHandler` (`src/ai/chat_handler.py`)

- `__init__` calls `registry.register_from_executor(executor)` after creating both

### What stays the same

- `CommandDefinition`, `CommandParameter` data classes
- `to_openai_tool()`, `to_description_block()` methods
- The two-phase AI prompt flow
- All existing commands (search, add_date, inbox_zero, todays_meetings)

## Example

```python
@ai_command(
    name="search",
    description="Search emails by term with optional filters",
    params=[
        Param("search_term", "The search term or query", "string", required=True),
        Param("body_term", "Additional body text filter", "string"),
    ],
)
def search(self, params: dict) -> None:
    self._processor.search_emails(search_term=params["search_term"], ...)
```

Adding a new AI command = writing one decorated method on CommandExecutor.
