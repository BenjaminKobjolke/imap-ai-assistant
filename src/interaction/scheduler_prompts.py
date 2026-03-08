"""Backwards-compatible aliases for interactions-sdk.

All interaction logic now lives in the interactions-sdk package.
"""
from interactions_sdk import AbortError as SchedulerAbortError
from interactions_sdk import InteractionChoice as SchedulerChoice
from interactions_sdk import ask as scheduler_ask
from interactions_sdk import ask_or_accept, is_interactive, start_output_capture, stop_output_capture
from interactions_sdk import choose as scheduler_choose
from interactions_sdk import confirm as scheduler_confirm
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
    "start_output_capture",
    "stop_output_capture",
]
