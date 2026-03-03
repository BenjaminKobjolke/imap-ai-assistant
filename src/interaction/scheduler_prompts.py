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


def _is_interactive() -> bool:
    """Return True when running under the task scheduler with SDK available."""
    if not _SDK_AVAILABLE:
        import os
        if os.environ.get("TASK_SCHEDULER") == "1":
            logger.warning("TASK_SCHEDULER=1 is set but task-scheduler-sdk is not installed — falling back to console")
        return False
    return bool(is_run_by_task_scheduler())


def scheduler_confirm(message: str, *, default: bool) -> bool:
    """Confirm yes/no. Delegates to SDK or falls back to console input."""
    if _is_interactive():
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
    if _is_interactive():
        result = ask(message, default=default)
        if result is None:
            raise SchedulerAbortError("User did not answer ask prompt")
        return str(result)

    raw = input(f"{message} [{default}]: ").strip()
    return raw if raw else default


def scheduler_choose(message: str, options: list[str], *, default: int) -> int:
    """Choose from *options*. Delegates to SDK or falls back to console input."""
    if _is_interactive():
        result = choose(message, options, default=default)
        if result is None:
            raise SchedulerAbortError("User did not answer choose prompt")
        return int(result)

    print(message)
    for i, opt in enumerate(options):
        marker = " *" if i == default else ""
        print(f"  [{i}] {opt}{marker}")

    while True:
        raw = input(f"Choice [{default}]: ").strip()
        if not raw:
            return default
        try:
            val = int(raw)
            if 0 <= val < len(options):
                return val
        except ValueError:
            pass
        print(f"  Please enter 0-{len(options) - 1}")


def send_output(text: str) -> None:
    """Send a display message to the user.

    When interactive, delegates to the SDK output() for protocol-level display.
    Otherwise falls back to print() for normal console output.
    """
    if _is_interactive():
        output(text)
    else:
        print(text)
