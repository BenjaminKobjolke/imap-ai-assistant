"""Thin wrapper around task-scheduler-sdk for interactive prompts.

When the app runs under the task scheduler (TASK_SCHEDULER=1), these functions
delegate to the SDK's confirm/ask/choose prompts. Otherwise they return
defaults silently so existing automated behaviour is unchanged.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    from task_scheduler_sdk import ask, choose, confirm, is_run_by_task_scheduler, output
    _SDK_AVAILABLE = True
except ImportError:
    _SDK_AVAILABLE = False


def _is_interactive() -> bool:
    """Return True when running under the task scheduler with SDK available."""
    if not _SDK_AVAILABLE:
        import os
        if os.environ.get("TASK_SCHEDULER") == "1":
            logger.warning("TASK_SCHEDULER=1 is set but task-scheduler-sdk is not installed — falling back to defaults")
        return False
    return bool(is_run_by_task_scheduler())


def scheduler_confirm(message: str, *, default: bool) -> bool:
    """Confirm yes/no or return *default* when not interactive."""
    if not _is_interactive():
        return default
    return bool(confirm(message, default=default))


def scheduler_ask(message: str, *, default: str) -> str:
    """Ask for free-form text or return *default* when not interactive."""
    if not _is_interactive():
        return default
    return str(ask(message, default=default))


def scheduler_choose(message: str, options: list[str], *, default: int) -> int:
    """Choose from *options* or return *default* index when not interactive."""
    if not _is_interactive():
        return default
    return int(choose(message, options, default=default))


def send_output(text: str) -> None:
    """Send a display message to the user.

    When interactive, delegates to the SDK output() for protocol-level display.
    Otherwise falls back to print() for normal console output.
    """
    if _is_interactive():
        output(text)
    else:
        print(text)
