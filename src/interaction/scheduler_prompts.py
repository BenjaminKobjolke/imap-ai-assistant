"""Thin wrapper around task-scheduler-sdk for interactive prompts.

When the app runs under the task scheduler (TASK_SCHEDULER=1), these functions
delegate to the SDK's confirm/ask/choose prompts. If the user does not answer
in scheduler mode, a SchedulerAbortError is raised to abort the operation.

When running from the CLI (no scheduler), falls back to console input.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from task_scheduler_sdk import ask, choose, confirm, is_run_by_task_scheduler, output
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False


class SchedulerAbortError(Exception):
    """Raised when the user does not answer a scheduler prompt."""


def is_interactive() -> bool:
    """Return True when running under the task scheduler with SDK available."""
    if not _SDK_AVAILABLE:
        import os
        if os.environ.get("TASK_SCHEDULER") == "1":
            logger.warning("TASK_SCHEDULER=1 is set but task-scheduler-sdk is not installed — falling back to console")
        return False
    return bool(is_run_by_task_scheduler())


def scheduler_confirm(message: str, *, default: bool) -> bool:
    """Confirm yes/no. Delegates to SDK or falls back to console input."""
    if is_interactive():
        result = confirm(message, default=default)
        if result is None:
            raise SchedulerAbortError("User did not answer confirm prompt")
        return bool(result)

    hint = "Y/n" if default else "y/N"
    raw = input(f"{message} [{hint}]: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


def scheduler_ask(message: str, *, default: str) -> str:
    """Ask for free-form text. Delegates to SDK or falls back to console input."""
    if is_interactive():
        result = ask(message, default=default)
        if result is None:
            raise SchedulerAbortError("User did not answer ask prompt")
        return str(result)

    raw = input(f"{message} [{default}]: ").strip()
    return raw if raw else default


def scheduler_choose(
    message: str,
    options: list[str],
    *,
    default: int,
    hidden_options: dict[str, str] | None = None,
) -> int:
    """Choose from *options*. Delegates to SDK or falls back to console input.

    *hidden_options* maps shortcut keys to labels. They are accepted as input
    but not displayed in the numbered list. When a hidden shortcut is selected,
    the return value is ``len(options) + position`` in the hidden_options dict.
    """
    if is_interactive():
        result = choose(message, options, default=default, hidden_options=hidden_options)
        if result is None:
            raise SchedulerAbortError("User did not answer choose prompt")
        return int(result)

    print(message)
    for i, opt in enumerate(options):
        marker = " *" if i == default else ""
        print(f"  [{i}] {opt}{marker}")

    hidden_keys: list[str] = []
    if hidden_options:
        hidden_keys = list(hidden_options.keys())
        hints = ", ".join(f"{k}={label}" for k, label in hidden_options.items())
        print(f"  ({hints})")

    while True:
        raw = input(f"Choice [{default}]: ").strip()
        if not raw:
            return default
        if raw in hidden_keys:
            return len(options) + hidden_keys.index(raw)
        try:
            val = int(raw)
            if 0 <= val < len(options):
                return val
        except ValueError:
            pass
        print(f"  Please enter 0-{len(options) - 1}")


class SchedulerChoice:
    """Maps display labels to action keys for scheduler_choose."""

    _ABORT_KEY = "a"
    _ABORT_LABEL = "Abort"
    _ABORT_ACTION = "abort"

    def __init__(
        self,
        prompt: str,
        choices: list[tuple[str, str]],
        *,
        default: int = 0,
        abort: bool = False,
    ) -> None:
        self._prompt = prompt
        self._choices = choices
        self._default = default
        self._abort = abort

    def choose(self) -> str:
        """Show the menu and return the selected key."""
        labels = [label for label, _ in self._choices]
        hidden = {self._ABORT_KEY: self._ABORT_LABEL} if self._abort else None
        index = scheduler_choose(self._prompt, labels, default=self._default, hidden_options=hidden)
        if index < len(self._choices):
            return self._choices[index][1]
        return self._ABORT_ACTION


def ask_or_accept(label: str, *, default: str) -> str:
    """Show accept/edit choice, only prompt for text if user picks edit."""
    action = scheduler_choose(
        f"{label} {default}",
        ["Accept", "Edit"],
        default=0,
    )
    if action == 1:  # Edit
        return scheduler_ask(label, default=default)
    return default


_capture_buffer: list[str] | None = None


def start_output_capture() -> None:
    """Begin capturing send_output calls into a buffer."""
    global _capture_buffer
    _capture_buffer = []


def stop_output_capture() -> str:
    """Stop capturing and return all captured text joined by newlines."""
    global _capture_buffer
    result = "\n".join(_capture_buffer) if _capture_buffer else ""
    _capture_buffer = None
    return result


def send_output(text: str) -> None:
    """Send a display message to the user.

    When interactive, delegates to the SDK output() for protocol-level display.
    Otherwise falls back to print() for normal console output.
    Unicode safety is built in so callers do not need safe_print().
    """
    if _capture_buffer is not None:
        _capture_buffer.append(text)
    if is_interactive():
        output(text)
    else:
        try:
            print(text)
        except UnicodeEncodeError:
            print(text.encode("ascii", errors="replace").decode("ascii"))
