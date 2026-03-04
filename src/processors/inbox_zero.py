"""Interactive inbox-zero processor — process INBOX emails one by one."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from email.utils import parseaddr

from src.ai.openai_client import OpenAIClient
from src.config.settings import ConfigManager
from src.constants import CFG_TARGET_FOLDER, FOLDER_INBOX, MIME_TEXT_HTML, MIME_TEXT_PLAIN
from src.email.imap_client import EnhancedImapClient
from src.email.smtp_client import SmtpClient
from src.interaction.scheduler_prompts import SchedulerChoice, scheduler_ask, send_output
from src.processors.rtm_todo import RtmTodoCreator
from src.search.search_cache import SearchCache

logger = logging.getLogger(__name__)

_MAX_FOLDER_MATCHES = 5


class _AbortInboxZeroError(Exception):
    """Raised from any prompt to abort the entire inbox-zero flow."""


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
        unread_only: bool = False,
    ) -> None:
        """Walk through each INBOX email and let the user decide what to do."""
        send_output("Loading INBOX...")

        if unread_only:
            messages = client.client.get_unread_messages()
        else:
            messages = client.client.get_all_messages(folder=FOLDER_INBOX, include_attachments=False)

        if not messages:
            send_output("INBOX is empty — nothing to do.")
            return

        cache = SearchCache(config.search_cache_path)
        counters = InboxZeroCounters(total=len(messages))

        label = "unread email(s)" if unread_only else "email(s)"
        send_output(f"Found {counters.total} {label} in INBOX.\n")

        try:
            try:
                for i, (msg_id, email_msg) in enumerate(messages, 1):
                    InboxZero._display_email(email_msg, i, counters.total)

                    from_addr = InboxZero._extract_from_address(email_msg)
                    suggestion = cache.suggest_folder_for_sender(from_addr)

                    while True:
                        action = InboxZero._prompt_action(suggestion)

                        if action == "show_body":
                            excerpt = InboxZero._get_body_excerpt(email_msg)
                            send_output(f"\n{excerpt}\n")
                            continue
                        break

                    if action == "abort":
                        send_output("Aborting inbox-zero.")
                        break

                    if action == "skip":
                        counters.skipped += 1
                        send_output("  Skipped.\n")
                        continue

                    if action in ("move_suggested", "move_other"):
                        target = suggestion if action == "move_suggested" else None
                        success = InboxZero._action_move(
                            client, config, msg_id, target, dry_run=dry_run,
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

            except _AbortInboxZeroError:
                send_output("Aborting inbox-zero.")

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
        if suggestion:
            choices = [
                (f"Move to '{suggestion}'", "move_suggested"),
                ("Move to other folder", "move_other"),
                ("Add todo", "todo"),
                ("Skip", "skip"),
                ("Trash", "trash"),
                ("Show body", "show_body"),
            ]
        else:
            choices = [
                ("Move to folder", "move_other"),
                ("Add todo", "todo"),
                ("Skip", "skip"),
                ("Trash", "trash"),
                ("Show body", "show_body"),
            ]

        return SchedulerChoice("Action:", choices, abort=True).choose()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    @staticmethod
    def _action_move(
        client: EnhancedImapClient,
        config: ConfigManager,
        msg_id: object,
        target: str | None,
        *,
        dry_run: bool = False,
    ) -> bool:
        """Move email to a target folder."""
        if target is None:
            target = InboxZero._search_folder(client)
        if not target:
            send_output("  No folder selected — skipping.")
            return False

        if dry_run:
            send_output(f"  DRY RUN: would move to '{target}'")
            return True

        try:
            client.client.client.select_folder(FOLDER_INBOX)
            client.client.mark_as_read(str(msg_id))
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
        target_folder = config.get_processing_rules("self")[CFG_TARGET_FOLDER]
        if dry_run:
            send_output(f"  DRY RUN: would move to '{target_folder}'")
            return True

        try:
            client.client.client.select_folder(FOLDER_INBOX)
            client.client.mark_as_read(str(msg_id))
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
            client.client.client.select_folder(FOLDER_INBOX)
            client.client.mark_as_read(str(msg_id))
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
    def _search_folder(client: EnhancedImapClient) -> str | None:
        """Search for a destination folder by partial name."""
        try:
            all_folders = sorted(client.client.list_folders())
        except Exception as e:
            logger.error("Could not list folders: %s", e)
            send_output(f"  Could not list folders: {e}")
            return None

        if not all_folders:
            send_output("  No folders found.")
            return None

        return InboxZero._folder_search_loop(all_folders)

    @staticmethod
    def _folder_search_loop(all_folders: list[str]) -> str | None:
        """Prompt for a partial folder name, filter, and let the user pick."""
        while True:
            query = scheduler_ask(
                "Type part of the folder name (or 'cancel' / 'abort'):", default="",
            )
            query = query.strip()
            if not query or query.lower() == "cancel":
                return None
            if query.lower() == "abort":
                raise _AbortInboxZeroError

            matches = [
                f for f in all_folders if query.lower() in f.lower()
            ]

            if not matches:
                send_output(f"  No folders matching '{query}'. Try again.")
                continue

            if len(matches) > _MAX_FOLDER_MATCHES:
                send_output(
                    f"  {len(matches)} matches — showing first {_MAX_FOLDER_MATCHES}. "
                    "Refine your search for better results.",
                )
                matches = matches[:_MAX_FOLDER_MATCHES]

            result = InboxZero._pick_from_matches(matches)
            if result is not None:
                return result
            # user chose "Search again" — loop continues

    @staticmethod
    def _pick_from_matches(matches: list[str]) -> str | None:
        """Show matched folders and let the user pick one or search again."""
        choices = [(m, m) for m in matches] + [("Search again", "search_again")]
        result = SchedulerChoice("Select folder:", choices, abort=True).choose()
        if result == "abort":
            raise _AbortInboxZeroError
        if result == "search_again":
            return None
        return result

    @staticmethod
    def _extract_from_address(email_msg: object) -> str:
        """Extract the bare email address from the from_address field."""
        raw = getattr(email_msg, "from_address", "") or ""
        _, addr = parseaddr(raw)
        return addr

    @staticmethod
    def _get_body_excerpt(email_msg: object, max_chars: int = 800) -> str:
        """Extract a plain-text excerpt from the email body."""
        body = None
        if hasattr(email_msg, "get_body"):
            body = email_msg.get_body(MIME_TEXT_PLAIN)
            if not body:
                import re

                html = email_msg.get_body(MIME_TEXT_HTML)
                if html:
                    body = re.sub(r"<[^>]+>", "", html).strip()
        if not body:
            return "(no body content)"
        return str(body)[:max_chars]
