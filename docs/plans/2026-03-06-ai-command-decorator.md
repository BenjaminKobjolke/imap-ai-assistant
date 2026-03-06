# AI Command Decorator Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace manual 3-place command registration with a single `@ai_command` decorator per handler method.

**Architecture:** A decorator stores `CommandDefinition` metadata on handler methods. The registry scans the executor at startup to auto-discover and register all commands. Handler dispatch is built from the same scan.

**Tech Stack:** Python dataclasses, decorator pattern, `inspect`-free introspection via `dir()` + `getattr`.

---

### Task 1: Create `@ai_command` decorator and `Param` alias

**Files:**
- Create: `src/ai/ai_command.py`
- Test: `tests/test_ai_command.py`

**Step 1: Write the failing test**

```python
# tests/test_ai_command.py
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
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ai_command.py -v`
Expected: FAIL (module not found)

**Step 3: Write minimal implementation**

```python
# src/ai/ai_command.py
"""Decorator for auto-registering AI chat commands."""

from __future__ import annotations

from typing import Any, Callable

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
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_ai_command.py -v`
Expected: PASS (4 tests)

**Step 5: Commit**

`FEATURE (ai): add @ai_command decorator for auto-registering AI chat commands`

---

### Task 2: Add `register_from_executor` to `CommandRegistry`

**Files:**
- Modify: `src/ai/command_registry.py`
- Modify: `tests/test_command_registry.py`

**Step 1: Write the failing test**

Add to `tests/test_command_registry.py`:

```python
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

        registry = CommandRegistry(auto_register=False)
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

        call_log = []

        class FakeExecutor:
            @ai_command(name="log_cmd", description="Logs calls")
            def log_it(self, params):
                call_log.append(params)

        registry = CommandRegistry(auto_register=False)
        executor = FakeExecutor()
        handlers = registry.register_from_executor(executor)

        handlers["log_cmd"]({"key": "value"})
        assert call_log == [{"key": "value"}]
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_command_registry.py::TestRegisterFromExecutor -v`
Expected: FAIL (no `auto_register` param, no `register_from_executor` method)

**Step 3: Implement**

Modify `CommandRegistry.__init__` to accept `auto_register` flag:

```python
def __init__(self, *, auto_register: bool = True) -> None:
    self._commands: dict[str, CommandDefinition] = {}
    if auto_register:
        self._register_defaults()
```

Add `register_from_executor` method:

```python
def register_from_executor(self, executor: object) -> dict[str, Any]:
    """Scan executor for @ai_command decorated methods, register them.

    Returns a dict mapping command names to bound handler callables.
    """
    handlers: dict[str, Any] = {}
    for attr_name in dir(executor):
        if attr_name.startswith("_"):
            continue
        method = getattr(executor, attr_name, None)
        if method is None or not callable(method):
            continue
        cmd = getattr(method, "_ai_command", None)
        if cmd is None:
            continue
        self.register(cmd)
        handlers[cmd.name] = method
    return handlers
```

**Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_command_registry.py -v`
Expected: ALL PASS (including existing tests which still use `auto_register=True` default)

**Step 5: Commit**

`FEATURE (ai): add register_from_executor to CommandRegistry for auto-discovery`

---

### Task 3: Decorate `CommandExecutor` methods and remove manual wiring

**Files:**
- Modify: `src/ai/chat_handler.py`
- Modify: `tests/test_chat_handler.py`

**Step 1: Add decorators to all executor methods**

In `src/ai/chat_handler.py`, add import:
```python
from src.ai.ai_command import Param, ai_command
```

Replace `CommandExecutor` class:

```python
class CommandExecutor:
    """Bridges validated AI commands to EmailProcessor methods."""

    def __init__(self, processor: Any) -> None:
        self._processor = processor

    @ai_command(
        name="add_date",
        description="Create a Google Calendar event",
        params=[
            Param("title", "Title/name of the event", "string", required=True),
            Param("date", "Date for the event (DD.MM.YYYY, 'today', 'tomorrow')", "string"),
            Param("start_time", "Start time in HH:MM format (e.g. 14:00)", "string"),
            Param("end_time", "End time in HH:MM format (e.g. 15:00)", "string"),
            Param("calendar", "Calendar name or ID to create the event in", "string"),
        ],
    )
    def add_date(self, params: dict[str, Any]) -> None:
        """Translate AI parameters into the add_date CLI format."""
        raw_args: list[str] = [params["title"]]
        if params.get("date"):
            raw_args.append(str(params["date"]))
        if params.get("start_time"):
            start = str(params["start_time"])
            end = str(params.get("end_time", ""))
            if end:
                raw_args.append(f"{start}-{end}")
            else:
                raw_args.append(start)
        if params.get("calendar"):
            raw_args.append(f"@{params['calendar']}")
        self._processor.add_date(raw_args)

    @ai_command(
        name="inbox_zero",
        description="Process inbox emails interactively one by one to achieve inbox zero",
        params=[
            Param("unread_only", "Only process unread emails", "boolean"),
        ],
    )
    def inbox_zero(self, params: dict[str, Any]) -> None:
        """Execute inbox-zero with optional unread_only flag."""
        unread_only = bool(params.get("unread_only", False))
        self._processor.inbox_zero(unread_only=unread_only)

    @ai_command(
        name="search",
        description="Search emails by term with optional filters",
        params=[
            Param("search_term", "The search term or query", "string", required=True),
            Param("body_term", "Additional body text filter", "string"),
            Param("date", "Exact date filter (DD.MM.YYYY)", "string"),
            Param("date_after", "Only emails after this date (DD.MM.YYYY)", "string"),
            Param("date_before", "Only emails before this date (DD.MM.YYYY)", "string"),
            Param("path", "Specific IMAP folder to search in", "string"),
        ],
    )
    def search(self, params: dict[str, Any]) -> None:
        """Execute email search with optional filters."""
        self._processor.search_emails(
            search_term=params["search_term"],
            body_term=params.get("body_term"),
            date=params.get("date"),
            date_after=params.get("date_after"),
            date_before=params.get("date_before"),
            path=params.get("path"),
        )

    @ai_command(
        name="todays_meetings",
        description="List today's meetings with start and end times",
    )
    def todays_meetings(self, params: dict[str, Any]) -> None:
        """Execute today's meetings listing."""
        self._processor.todays_meetings()
```

**Step 2: Wire auto-discovery in `CommandExecutor.execute`**

Replace the manual `_handlers` dict and `execute` method:

```python
def __init__(self, processor: Any) -> None:
    self._processor = processor
    self._handlers: dict[str, Any] = {}

def bind_to_registry(self, registry: Any) -> None:
    """Let the registry discover commands and build handler dispatch."""
    self._handlers = registry.register_from_executor(self)

def execute(self, command_name: str, params: dict[str, Any]) -> None:
    """Execute a command by name with the given parameters."""
    handler = self._handlers.get(command_name)
    if handler is None:
        raise ValueError(f"Unknown command: {command_name}")
    handler(params)
```

**Step 3: Update `ChatHandler.__init__` and `email_processor.py`**

In `ChatHandler.__init__`, replace `registry` parameter setup — no change needed since registry is passed in.

In `email_processor.py` (`ai_chat` method around line 580), change:

```python
registry = CommandRegistry(auto_register=False)
executor = CommandExecutor(self)
executor.bind_to_registry(registry)
```

**Step 4: Update `CommandRegistry._register_defaults`**

Delete `_register_defaults` entirely (or keep it empty for backward compat — the `auto_register=False` in the call above skips it).

**Step 5: Update existing tests**

In `tests/test_chat_handler.py`, the `TestCommandExecutor` tests create `CommandExecutor` and call methods directly. Since the methods are now named differently (no `_execute_` prefix) and are public, update:

- `executor._execute_search(params)` → `executor.search(params)`
- `executor._execute_add_date(params)` → `executor.add_date(params)`
- etc.

In `tests/test_command_registry.py`, `TestCommandRegistry.test_default_commands_registered` currently expects 4 commands from `_register_defaults`. Update to use `auto_register=False` + `register_from_executor` with a real `CommandExecutor`, OR change to test the new flow.

Simplest: keep `_register_defaults` but have it do nothing (empty body), and test the decorator path instead.

**Step 6: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

**Step 7: Commit**

`REFACTOR (ai): replace manual command registration with @ai_command decorators`

---

### Task 4: Delete `_register_defaults` and update registry tests

**Files:**
- Modify: `src/ai/command_registry.py`
- Modify: `tests/test_command_registry.py`

**Step 1: Remove `_register_defaults` from `CommandRegistry`**

Delete the entire `_register_defaults` method. Change `__init__` default to `auto_register=False` since there are no defaults to register:

```python
def __init__(self) -> None:
    self._commands: dict[str, CommandDefinition] = {}
```

Remove the `auto_register` parameter entirely — it's no longer needed.

**Step 2: Update tests that relied on default registration**

In `tests/test_command_registry.py`, update `TestCommandRegistry`:

- `test_default_commands_registered` → test via `register_from_executor` with a real `CommandExecutor`
- Other tests that create `CommandRegistry()` and expect 4 commands → update or remove

```python
class TestCommandRegistryWithExecutor:
    """Tests for CommandRegistry populated via register_from_executor."""

    def _populated_registry(self) -> CommandRegistry:
        from src.ai.chat_handler import CommandExecutor
        from unittest.mock import MagicMock
        registry = CommandRegistry()
        executor = CommandExecutor(MagicMock())
        registry.register_from_executor(executor)
        return registry

    def test_all_four_commands_registered(self) -> None:
        registry = self._populated_registry()
        names = {cmd.name for cmd in registry.all_commands()}
        assert names == {"add_date", "inbox_zero", "search", "todays_meetings"}

    def test_search_has_required_search_term(self) -> None:
        registry = self._populated_registry()
        cmd = registry.get("search")
        assert cmd is not None
        term = next(p for p in cmd.parameters if p.name == "search_term")
        assert term.required is True
```

**Step 3: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

**Step 4: Run linter**

Run: `uv run ruff check src/ai/ tests/test_ai_command.py tests/test_command_registry.py tests/test_chat_handler.py`
Expected: No errors in changed files

**Step 5: Commit**

`CLEANUP (ai): remove _register_defaults, decorators are now sole source of truth`

---

## Verification

After all tasks:
1. `uv run pytest tests/ -v` — all pass
2. `uv run ruff check src/ main.py` — no new errors
3. `uv run python main.py --ai "search for emails from kobjolke"` — AI search still works
4. Confirm adding a new command only requires one decorated method on CommandExecutor
