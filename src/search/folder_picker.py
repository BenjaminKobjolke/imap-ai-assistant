"""Reusable folder search / pick logic for interactive IMAP folder selection."""

from __future__ import annotations

from src.interaction.scheduler_prompts import SchedulerChoice, scheduler_ask, send_output

_MAX_FOLDER_MATCHES = 5
_ABORT_SENTINEL = "_abort_"


def folder_search_loop(
    all_folders: list[str],
    *,
    allow_abort: bool = False,
) -> str | None:
    """Prompt for a partial folder name, filter, and let the user pick.

    Returns the selected folder name, ``"_abort_"`` when *allow_abort* is
    ``True`` and the user types 'abort', or ``None`` to cancel.
    """
    while True:
        prompt = "Type part of the folder name (or 'cancel'"
        if allow_abort:
            prompt += " / 'abort'"
        prompt += "):"

        query = scheduler_ask(prompt, default="").strip()
        if not query or query.lower() == "cancel":
            return None
        if allow_abort and query.lower() == "abort":
            return _ABORT_SENTINEL

        matches = [f for f in all_folders if query.lower() in f.lower()]

        if not matches:
            send_output(f"  No folders matching '{query}'. Try again.")
            continue

        if len(matches) > _MAX_FOLDER_MATCHES:
            send_output(
                f"  {len(matches)} matches — showing first {_MAX_FOLDER_MATCHES}. "
                "Refine your search for better results.",
            )
            matches = matches[:_MAX_FOLDER_MATCHES]

        result = pick_from_matches(matches, allow_abort=allow_abort)
        if result is not None:
            return result


def pick_from_matches(
    matches: list[str],
    *,
    allow_abort: bool = False,
) -> str | None:
    """Show matched folders and let the user pick one or search again.

    Returns the chosen folder, ``"_abort_"`` when *allow_abort* is ``True``
    and the user selects abort, or ``None`` to search again.
    """
    choices = [(m, m) for m in matches] + [("Search again", "search_again")]
    result = SchedulerChoice("Select folder:", choices, abort=allow_abort).choose()
    if result == "abort":
        return _ABORT_SENTINEL
    if result == "search_again":
        return None
    return result
