# Making a Feature Available in AI Chat Mode

This guide explains how to expose a new feature to the `--ai` conversational chat mode.

## Overview

AI commands are defined by decorating a method on `CommandExecutor` in `src/ai/chat_handler.py` with `@ai_command`. The decorator is the **single source of truth** — it defines the command name, description, and parameters. No other registration is needed.

## Steps

### 1. Ensure the feature exists on `EmailProcessor`

The `CommandExecutor` delegates to `self._processor` (an `EmailProcessor` instance). Your feature must be callable as a method on `EmailProcessor`. The processor method can delegate to a dedicated service class (e.g. `MeetingService`) — it doesn't have to live directly on `EmailProcessor`.

```python
# src/processors/email_processor.py
class EmailProcessor:
    def my_new_feature(self, some_arg: str, optional_flag: bool = False) -> None:
        ...
```

### 2. Add a decorated method to `CommandExecutor`

Open `src/ai/chat_handler.py` and add a new method to the `CommandExecutor` class:

```python
from src.ai.ai_command import Param, ai_command

@ai_command(
    name="my_new_feature",
    description="Short description of what this command does",
    params=[
        Param("some_arg", "Description of this parameter", "string", required=True),
        Param("optional_flag", "Description of this flag", "boolean"),
    ],
)
def my_new_feature(self, params: dict[str, Any]) -> None:
    """Translate AI parameters into the processor call."""
    self._processor.my_new_feature(
        some_arg=params["some_arg"],
        optional_flag=bool(params.get("optional_flag", False)),
    )
```

That's it. The decorator handles all registration automatically.

### Non-interactive requirement

AI commands execute under silent output capture. The code path **must not** call `input()`, `scheduler_ask()`, or `scheduler_choose()`. If the underlying feature has an interactive mode, add an `interactive: bool = True` parameter and pass `interactive=False` from the `CommandExecutor` method:

```python
# In the processor / service method:
def my_feature(self, *, interactive: bool = True) -> None:
    ...  # skip input() prompts when interactive=False

# In CommandExecutor:
@ai_command(name="my_feature", description="...")
def my_feature(self, params: dict[str, Any]) -> None:
    self._processor.my_feature(interactive=False)
```

The auto-discovery guard test `test_ai_commands_are_non_interactive` in `test_chat_handler.py` will catch violations automatically — any new `@ai_command` that calls an interactive function will fail the test.

### 3. Add tests

Add test cases to `tests/test_chat_handler.py` in the `TestCommandExecutor` class:

```python
def test_execute_my_new_feature(
    self, executor: CommandExecutor, processor: MagicMock,
) -> None:
    """Verify my_new_feature passes parameters correctly."""
    executor.execute("my_new_feature", {"some_arg": "hello"})
    processor.my_new_feature.assert_called_once_with(
        some_arg="hello",
        optional_flag=False,
    )
```

### 4. Verify

```bash
uv run pytest tests/test_chat_handler.py tests/test_command_registry.py -v
uv run ruff check src/ai/chat_handler.py
```

## Param Reference

```python
Param(name, description, param_type, required=False, enum=None, default=None)
```

| Argument | Description |
|---|---|
| `name` | Parameter name (must match the key in `params` dict) |
| `description` | Human-readable description shown to the AI |
| `param_type` | `"string"`, `"boolean"`, or `"integer"` |
| `required` | If `True`, the AI must provide this parameter |
| `enum` | Optional list of allowed values, e.g. `["fast", "slow"]` |
| `default` | Optional default value |

## How It Works

1. `CommandExecutor.bind_to_registry(registry)` is called at startup
2. `CommandRegistry.register_from_executor()` scans the executor for methods decorated with `@ai_command`
3. Each decorated method is registered as both a command definition (for AI intent detection and parameter validation) and a handler (for execution)
4. The AI uses the command descriptions to detect user intent (Phase 1) and the parameter schemas to validate inputs via function calling (Phase 2)

## Files Involved

| File | Role |
|---|---|
| `src/ai/ai_command.py` | `@ai_command` decorator and `Param` alias |
| `src/ai/chat_handler.py` | `CommandExecutor` — add your decorated method here |
| `src/ai/command_registry.py` | `CommandRegistry` — auto-discovery logic |
| `src/processors/email_processor.py` | `EmailProcessor` — the actual feature implementation |
| `src/processors/meeting_service.py` | `MeetingService` — example of extracted service class |
