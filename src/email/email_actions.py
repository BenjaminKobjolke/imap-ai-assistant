"""Shared email action menu used by search and browse flows."""

from __future__ import annotations

from src.config.settings import ConfigManager
from src.email.email_attachment_viewer import EmailAttachmentViewer
from src.email.email_body_viewer import EmailBodyViewer
from src.email.imap_client import EnhancedImapClient
from src.interaction.scheduler_prompts import SchedulerChoice


def email_action_loop(
    client: EnhancedImapClient,
    config: ConfigManager,
    folder: str,
    msg_id: str,
    extra_actions: list[tuple[str, str]] | None = None,
) -> str | None:
    """Shared action menu for a selected email.

    Handles common actions (show body, show attachments, back) internally.
    Returns the key of an unhandled extra action for the caller, or None on back/abort.
    """
    while True:
        choices: list[tuple[str, str]] = [
            ("Show body", "show_body"),
            ("Show attachments", "show_attachments"),
        ]
        if extra_actions:
            choices.extend(extra_actions)
        choices.append(("Back", "back"))

        action = SchedulerChoice("Action:", choices).choose()

        if action == "show_body":
            EmailBodyViewer.show_body(client, folder, msg_id)
        elif action == "show_attachments":
            EmailAttachmentViewer.show_attachments(client, config, folder, msg_id)
        elif action in ("back", "abort"):
            return None
        else:
            return action
