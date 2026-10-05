"""Prompt helpers on top of interactions-sdk, with optional auto-accept.

The interaction logic lives in the interactions-sdk package. The wrappers here
only add auto-accept, so unattended runs do not block on a prompt.
"""
from __future__ import annotations

import interactions_sdk as _sdk
from interactions_sdk import AbortError as SchedulerAbortError
from interactions_sdk import InteractionChoice as SchedulerChoice
from interactions_sdk import is_interactive, start_output_capture, stop_output_capture
from interactions_sdk import output as send_output

__all__ = [
    "SchedulerAbortError",
    "SchedulerChoice",
    "ask_or_accept",
    "is_interactive",
    "scheduler_ask",
    "scheduler_choose",
    "scheduler_confirm",
    "send_output",
    "set_auto_accept",
    "start_output_capture",
    "stop_output_capture",
]

# ponytail: SchedulerChoice menus are not auto-accepted and still ask;
# wrap InteractionChoice here if an unattended run ever reaches one.
_auto_accept = False


def set_auto_accept(enabled: bool) -> None:
    """Let prompts answer themselves with their default, for runs nobody watches."""
    global _auto_accept
    _auto_accept = enabled


def scheduler_confirm(message: str, *, default: bool | None = None, id: str | None = None) -> bool:
    """Ask yes/no; auto-accept takes the default so a scheduled run does not wait."""
    if _auto_accept and default is not None:
        send_output(f"{message} [auto: {'yes' if default else 'no'}]")
        return default
    return bool(_sdk.confirm(message, default=default, id=id))


def scheduler_ask(message: str, *, default: str | None = None, id: str | None = None) -> str:
    """Ask for text; auto-accept takes the default so a scheduled run does not wait."""
    if _auto_accept and default is not None:
        send_output(f"{message} [auto: {default}]")
        return default
    return str(_sdk.ask(message, default=default, id=id))


def scheduler_choose(
    message: str,
    options: list[str],
    *,
    default: int | None = None,
    id: str | None = None,
    hidden_options: dict[str, str] | None = None,
) -> int:
    """Ask to pick an option; auto-accept takes the default so a scheduled run does not wait."""
    if _auto_accept and default is not None:
        send_output(f"{message} [auto: {options[default]}]")
        return default
    return int(_sdk.choose(message, options, default=default, id=id, hidden_options=hidden_options))


def ask_or_accept(label: str, *, default: str) -> str:
    """Offer accept/edit for a value. Reimplemented here because the SDK version bypasses auto-accept."""
    action = scheduler_choose(f"{label} {default}", ["Accept", "Edit"], default=0)
    return scheduler_ask(label, default=default) if action == 1 else default
