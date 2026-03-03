"""Interactive inbox-zero processor — process INBOX emails one by one."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from email.utils import parseaddr

from src.ai.openai_client import OpenAIClient
from src.config.settings import ConfigManager
from src.email.imap_client import EnhancedImapClient
from src.email.smtp_client import SmtpClient
from src.interaction.scheduler_prompts import scheduler_choose, send_output
from src.processors.rtm_todo import RtmTodoCreator
from src.search.search_cache import SearchCache

logger = logging.getLogger(__name__)


@dataclass
class InboxZeroCounters:
    """Tracks actions taken during inbox-zero processing."""

    total: int = 0
    moved: int = 0
    todoed: int = 0
    skipped: int = 0
    trashed: int = 0


class InboxZero:
    """Processes INBOX emails interactively to achieve inbox zero."""

    @staticmethod
    def process_inbox(
        client: EnhancedImapClient,
        config: ConfigManager,
        smtp_client: SmtpClient,
        openai_client: OpenAIClient,
        *,
        dry_run: bool = False,
    ) -> None:
        """Walk through each INBOX email and let the user decide what to do."""
        send_output("Loading INBOX...")

        messages = client.client.get_all_messages(folder="INBOX", include_attachments=False)
        if not messages:
            send_output("INBOX is empty — nothing to do.")
            return

        # Most recent first
        messages = list(reversed(messages))

        cache = SearchCache(config.search_cache_path)
        counters = InboxZeroCounters(total=len(messages))

        send_output(f"Found {counters.total} email(s) in INBOX.\n")

        try:
            for i, (msg_id, email_msg) in enumerate(messages, 1):
                InboxZero._display_email(email_msg, i, counters.total)

                from_addr = InboxZero._extract_from_address(email_msg)
                suggestion = cache.suggest_folder_for_sender(from_addr)

                action = InboxZero._prompt_action(suggestion)

                if action == "abort":
                    send_output("Aborting inbox-zero.")
                    break

                if action == "skip":
                    counters.skipped += 1
                    send_output("  Skipped.\n")
                    continue

                if action == "move":
                    success = InboxZero._action_move(
                        client, config, msg_id, suggestion, dry_run=dry_run,
                    )
                    if success:
                        counters.moved += 1

                elif action == "todo":
                    success = InboxZero._action_todo(
                        client, config, smtp_client, openai_client,
                        msg_id, email_msg, dry_run=dry_run,
                    )
                    if success:
                        counters.todoed += 1

                elif action == "trash":
                    success = InboxZero._action_trash(client, config, msg_id, dry_run=dry_run)
                    if success:
                        counters.trashed += 1

                send_output("")

        finally:
            cache.close()

        InboxZero._display_summary(counters)

    # ------------------------------------------------------------------
    # Display helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _display_email(email_msg: object, index: int, total: int) -> None:
        """Show a compact summary of the email."""
        subject = getattr(email_msg, "subject", "(no subject)") or "(no subject)"
        from_addr = getattr(email_msg, "from_address", "(unknown)") or "(unknown)"
        date = getattr(email_msg, "date", "") or ""

        line = "\u2501" * 50
        send_output(line)
        send_output(f"  Email {index}/{total}")
        send_output(f"  From:    {from_addr}")
        send_output(f"  Subject: {subject}")
        if date:
            send_output(f"  Date:    {date}")
        send_output(line)

    @staticmethod
    def _display_summary(counters: InboxZeroCounters) -> None:
        """Show final summary of actions taken."""
        send_output(
            f"\nInbox zero summary: {counters.total} email(s) | "
            f"{counters.moved} moved | {counters.todoed} todoed | "
            f"{counters.skipped} skipped | {counters.trashed} trashed"
        )

    # ------------------------------------------------------------------
    # User prompt
    # ------------------------------------------------------------------

    @staticmethod
    def _prompt_action(suggestion: str | None) -> str:
        """Present the action menu. Returns action key."""
        move_label = f"Move to '{suggestion}'" if suggestion else "Move to folder"

        options = [move_label, "Add todo", "Skip", "Trash", "Abort"]
        mapping = ["move", "todo", "skip", "trash", "abort"]

        choice = scheduler_choose("Action:", options, default=0)
        return mapping[choice]

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    @staticmethod
    def _action_move(
        client: EnhancedImapClient,
        config: ConfigManager,
        msg_id: object,
        suggestion: str | None,
        *,
        dry_run: bool = False,
    ) -> bool:
        """Move email to a target folder."""
        target = InboxZero._pick_folder(client, suggestion)
        if not target:
            send_output("  No folder selected — skipping.")
            return False

        if dry_run:
            send_output(f"  DRY RUN: would move to '{target}'")
            return True

        try:
            client.client.client.select_folder("INBOX")
            success = client.client.move_to_folder(msg_id, target)
            if success:
                send_output(f"  Moved to '{target}'")
            else:
                send_output(f"  Failed to move to '{target}'")
            return bool(success)
        except Exception as e:
            logger.error("Failed to move email: %s", e)
            send_output(f"  Error moving email: {e}")
            return False

    @staticmethod
    def _action_todo(
        client: EnhancedImapClient,
        config: ConfigManager,
        smtp_client: SmtpClient,
        openai_client: OpenAIClient,
        msg_id: object,
        email_msg: object,
        *,
        dry_run: bool = False,
    ) -> bool:
        """Create an RTM todo from the email, then move to target folder."""
        subject, first_line, body_excerpt = client.extract_email_content(email_msg)
        from_address = getattr(email_msg, "from_address", "") or ""

        success, _todo_text = RtmTodoCreator.create_and_send(
            openai_client, smtp_client, config,
            subject, first_line, body_excerpt, from_address,
            dry_run=dry_run,
        )
        if not success:
            return False

        # Move to the "my own tasks" target folder
        target_folder = config.get_processing_rules("self")["target_folder"]
        if dry_run:
            send_output(f"  DRY RUN: would move to '{target_folder}'")
            return True

        try:
            client.client.client.select_folder("INBOX")
            client.client.move_to_folder(msg_id, target_folder)
            send_output(f"  Moved to '{target_folder}'")
        except Exception as e:
            logger.warning("Failed to move email after todo: %s", e)

        return True

    @staticmethod
    def _action_trash(
        client: EnhancedImapClient,
        config: ConfigManager,
        msg_id: object,
        *,
        dry_run: bool = False,
    ) -> bool:
        """Move email to the trash folder."""
        trash = config.trash_folder

        if dry_run:
            send_output(f"  DRY RUN: would move to '{trash}'")
            return True

        try:
            client.client.client.select_folder("INBOX")
            success = client.client.move_to_folder(msg_id, trash)
            if success:
                send_output(f"  Moved to '{trash}'")
            else:
                send_output(f"  Failed to move to '{trash}'")
            return bool(success)
        except Exception as e:
            logger.error("Failed to trash email: %s", e)
            send_output(f"  Error trashing email: {e}")
            return False

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pick_folder(
        client: EnhancedImapClient,
        suggestion: str | None,
    ) -> str | None:
        """Let the user pick a destination folder."""
        if suggestion:
            options = [f"'{suggestion}' (suggested)", "Pick another folder"]
            choice = scheduler_choose("Move to:", options, default=0)
            if choice == 0:
                return suggestion

        # List available folders and let the user pick
        try:
            folders = client.client.list_folders()
        except Exception as e:
            logger.error("Could not list folders: %s", e)
            send_output(f"  Could not list folders: {e}")
            return None

        if not folders:
            send_output("  No folders found.")
            return None

        folders = sorted(folders)
        choice = scheduler_choose("Select folder:", folders, default=0)
        return folders[choice]

    @staticmethod
    def _extract_from_address(email_msg: object) -> str:
        """Extract the bare email address from the from_address field."""
        raw = getattr(email_msg, "from_address", "") or ""
        _, addr = parseaddr(raw)
        return addr
