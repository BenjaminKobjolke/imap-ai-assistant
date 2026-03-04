"""Shared result type returned by action processors."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ActionResult:
    """Result of an action executed by a processor.

    Callers use ``action_type`` to update counters and ``continue_loop``
    to decide whether to re-show the action menu (e.g. after drafting a reply).
    """

    success: bool
    action_type: str
    continue_loop: bool = False
