"""Interactive IMAP folder and email browser with pagination."""

from __future__ import annotations

import logging

from src.ai.openai_client import OpenAIClient
from src.config.settings import ConfigManager
from src.email.draft_reply_handler import DraftReplyHandler
from src.email.email_body_viewer import EmailBodyViewer
from src.email.imap_client import EnhancedImapClient
from src.interaction.scheduler_prompts import SchedulerChoice, send_output
from src.search.search_cache import SearchCache

logger = logging.getLogger(__name__)

PAGE_SIZE = 5


def _children_at_level(folders: list[str], parent: str | None) -> list[str]:
    """Return immediate children of *parent* in the folder hierarchy.

    Root level (``parent=None``): folders with no ``/`` separator.
    Sub-level: folders starting with ``parent/`` that have exactly one more segment.
    """
    if parent is None:
        return [f for f in folders if "/" not in f]

    prefix = f"{parent}/"
    return [
        f for f in folders
        if f.startswith(prefix) and "/" not in f[len(prefix):]
    ]


def _display_name(folder: str) -> str:
    """Return the last path segment of a folder name."""
    return folder.rsplit("/", 1)[-1]


class FolderBrowser:
    """Interactive IMAP folder and email browser."""

    def __init__(
        self,
        client: EnhancedImapClient,
        config: ConfigManager,
        openai_client: OpenAIClient,
    ) -> None:
        self._client = client
        self._config = config
        self._openai = openai_client
        self._folders: list[str] = []

    def browse(self) -> None:
        """Entry point — start browsing from root level."""
        try:
            self._folders = sorted(self._client.client.list_folders())
        except Exception as e:
            logger.error("Could not list folders: %s", e)
            send_output(f"Could not list folders: {e}")
            return

        if not self._folders:
            send_output("No folders found.")
            return

        send_output(f"Found {len(self._folders)} folder(s).\n")
        self._browse_level(parent=None)

    def _browse_level(self, parent: str | None) -> None:
        """Show folders at this level with pagination."""
        children = _children_at_level(self._folders, parent)
        if not children:
            if parent is not None:
                self._browse_emails(parent)
            return

        page = 0
        while True:
            start = page * PAGE_SIZE
            page_items = children[start : start + PAGE_SIZE]
            if not page_items:
                page = max(0, page - 1)
                continue

            level_label = _display_name(parent) if parent else "Root"
            send_output(f"\n📁 {level_label} - folders ({start + 1}-{start + len(page_items)} of {len(children)}):")
            choices: list[tuple[str, str]] = []
            for folder in page_items:
                choices.append((_display_name(folder), folder))

            if start + PAGE_SIZE < len(children):
                choices.append(("Next →", "__next__"))
            if page > 0:
                choices.append(("← Previous", "__prev__"))
            choices.append(("Back", "__back__"))

            action = SchedulerChoice("Select a folder:", choices).choose()

            if action == "__next__":
                page += 1
            elif action == "__prev__":
                page -= 1
            elif action in ("__back__", "abort"):
                return
            else:
                self._browse_folder(action)

    def _browse_folder(self, folder: str) -> None:
        """Enter a folder: if subfolders exist show them, else show emails."""
        children = _children_at_level(self._folders, folder)
        if children:
            self._browse_level(folder)
        else:
            self._browse_emails(folder)

    def _browse_emails(self, folder: str) -> None:
        """Show emails in folder with pagination."""
        send_output(f"\nLoading emails from '{_display_name(folder)}'...")
        try:
            messages = self._client.client.get_all_messages(
                folder=folder, include_attachments=False,
            )
        except Exception as e:
            logger.error("Error loading emails from %s: %s", folder, e)
            send_output(f"Error loading emails: {e}")
            return

        if not messages:
            send_output("  No emails in this folder.")
            return

        send_output(f"  {len(messages)} email(s) found.\n")

        page = 0
        while True:
            start = page * PAGE_SIZE
            page_items = messages[start : start + PAGE_SIZE]
            if not page_items:
                page = max(0, page - 1)
                continue

            send_output(f"\n📧 {_display_name(folder)} - emails ({start + 1}-{start + len(page_items)} of {len(messages)}):")
            choices: list[tuple[str, str]] = []
            for idx, (_msg_id, email_msg) in enumerate(page_items):
                from_addr = getattr(email_msg, "from_address", "") or ""
                subject = getattr(email_msg, "subject", "") or "(no subject)"
                date = getattr(email_msg, "date", "") or ""
                label = f"{from_addr} | {subject} | {date}"
                choices.append((label, f"email_{start + idx}"))

            if start + PAGE_SIZE < len(messages):
                choices.append(("Next →", "__next__"))
            if page > 0:
                choices.append(("← Previous", "__prev__"))
            choices.append(("Back", "__back__"))

            action = SchedulerChoice("Select an email:", choices).choose()

            if action == "__next__":
                page += 1
            elif action == "__prev__":
                page -= 1
            elif action in ("__back__", "abort"):
                return
            elif action.startswith("email_"):
                email_idx = int(action.removeprefix("email_"))
                msg_id, email_msg = messages[email_idx]
                self._email_actions(folder, msg_id, email_msg)

    def _email_actions(self, folder: str, msg_id: object, email_msg: object) -> None:
        """Show body or draft reply for a selected email."""
        while True:
            action = SchedulerChoice(
                "What would you like to do?",
                [
                    ("Show body", "show_body"),
                    ("Draft reply", "draft_reply"),
                    ("Back", "back"),
                ],
            ).choose()

            if action == "show_body":
                EmailBodyViewer.show_body(self._client, folder, str(msg_id))
            elif action == "draft_reply":
                from_addr_raw = getattr(email_msg, "from_address", "") or ""
                subject = getattr(email_msg, "subject", "") or ""
                body = EmailBodyViewer.get_body_excerpt(email_msg, max_chars=2000)

                cache = SearchCache(self._config.search_cache_path)
                handler = DraftReplyHandler(
                    self._client, self._config, self._openai, cache,
                )
                handler.draft_reply(from_addr_raw, subject, body)
            elif action in ("back", "abort"):
                return
