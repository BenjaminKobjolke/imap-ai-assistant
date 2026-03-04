"""Interactive inbox-zero processor — process INBOX emails one by one."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.ai.openai_client import OpenAIClient
from src.config.settings import ConfigManager
from src.constants import (
    ACTION_SHOW_BODY,
    FOLDER_INBOX,
    MIME_TEXT_HTML,
    MIME_TEXT_PLAIN,
)
from src.email.imap_client import EnhancedImapClient
from src.email.smtp_client import SmtpClient
from src.interaction.scheduler_prompts import SchedulerChoice, send_output
from src.processors.email_action_processor import EmailActionProcessor
from src.processors.invite_processor import InviteProcessor
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
    calendar_added: int = 0
    calendar_deleted: int = 0


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
        invite_processor: InviteProcessor | None = None,
    ) -> None:
        """Walk through each INBOX email and let the user decide what to do."""
        send_output("Loading INBOX...")

        if unread_only:
            messages = client.client.get_unread_messages()
        else:
            messages = client.client.get_all_messages(
                folder=FOLDER_INBOX, include_attachments=True,
            )

        if not messages:
            send_output("INBOX is empty — nothing to do.")
            return

        cache = SearchCache(config.search_cache_path)
        action_processor = EmailActionProcessor(
            client, config, smtp_client, openai_client, cache,
        )
        counters = InboxZeroCounters(total=len(messages))

        label = "unread email(s)" if unread_only else "email(s)"
        send_output(f"Found {counters.total} {label} in INBOX.\n")

        if invite_processor is not None:
            invite_processor.ensure_calendar_selected()

        try:
            try:
                for i, (msg_id, email_msg) in enumerate(messages, 1):
                    # Detect whether this is a meeting invite
                    invite = None
                    if invite_processor is not None:
                        invite = invite_processor.detect_invite(msg_id, email_msg)

                    if invite is not None:
                        assert invite_processor is not None
                        invite_processor.display_invite(invite, i, counters.total)
                        options = invite_processor.get_invite_options(invite)
                    else:
                        InboxZero._display_email(email_msg, i, counters.total)
                        from_addr = InboxZero._extract_from_address(email_msg)
                        suggestion = cache.suggest_folder_for_sender(from_addr)
                        options = action_processor.get_options(suggestion)

                    # Append generic options
                    options.extend([
                        ("Skip", "skip"),
                        ("Trash", "trash"),
                        ("Show body", ACTION_SHOW_BODY),
                    ])

                    # Action loop (show body and draft reply loop back)
                    while True:
                        action = SchedulerChoice("Action:", options, abort=True).choose()

                        if action == ACTION_SHOW_BODY:
                            InboxZero._show_body_paginated(email_msg)
                            continue

                        if action == "abort":
                            send_output("Aborting inbox-zero.")
                            raise _AbortInboxZeroError

                        if action == "skip":
                            counters.skipped += 1
                            send_output("  Skipped.\n")
                            break

                        if action == "trash":
                            if InboxZero._action_trash(client, config, msg_id, dry_run=dry_run):
                                counters.trashed += 1
                            break

                        # Delegate to appropriate processor
                        if invite is not None and invite_processor is not None:
                            result = invite_processor.execute_invite_action(
                                action, invite, dry_run=dry_run,
                            )
                        else:
                            result = action_processor.execute_action(
                                action, msg_id, email_msg, suggestion,
                                dry_run=dry_run,
                            )

                        if result.continue_loop:
                            continue

                        if result.action_type == "abort":
                            raise _AbortInboxZeroError

                        # Update counters
                        InboxZero._update_counters(counters, result.action_type)
                        break

                    send_output("")

            except _AbortInboxZeroError:
                send_output("Aborting inbox-zero.")

        finally:
            cache.close()

        InboxZero._display_summary(counters)

    # ------------------------------------------------------------------
    # Counter helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _update_counters(counters: InboxZeroCounters, action_type: str) -> None:
        """Increment the appropriate counter based on action result."""
        if action_type == "moved":
            counters.moved += 1
        elif action_type == "todoed":
            counters.todoed += 1
        elif action_type == "calendar_added":
            counters.calendar_added += 1
        elif action_type == "calendar_deleted":
            counters.calendar_deleted += 1
        elif action_type == "archived":
            counters.moved += 1

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
        parts = [
            f"{counters.total} email(s)",
            f"{counters.moved} moved",
            f"{counters.todoed} todoed",
            f"{counters.skipped} skipped",
            f"{counters.trashed} trashed",
        ]
        if counters.calendar_added:
            parts.append(f"{counters.calendar_added} calendar-added")
        if counters.calendar_deleted:
            parts.append(f"{counters.calendar_deleted} calendar-deleted")

        send_output(f"\nInbox zero summary: {' | '.join(parts)}")

    # ------------------------------------------------------------------
    # Generic actions
    # ------------------------------------------------------------------

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
    def _extract_from_address(email_msg: object) -> str:
        """Extract the bare email address from the from_address field."""
        from email.utils import parseaddr

        raw = getattr(email_msg, "from_address", "") or ""
        _, addr = parseaddr(raw)
        return addr

    @staticmethod
    def _show_body_paginated(email_msg: object, lines_per_page: int = 5) -> None:
        """Show the email body a few lines at a time with a 'More' option."""
        full_body = InboxZero._get_body_excerpt(email_msg, max_chars=5000)
        lines = full_body.splitlines()

        shown = 0
        while shown < len(lines):
            chunk = "\n".join(lines[shown : shown + lines_per_page])
            send_output(f"\n{chunk}")
            shown += lines_per_page

            if shown < len(lines):
                action = SchedulerChoice(
                    "",
                    [
                        ("More", "more"),
                        ("Done", "done"),
                    ],
                ).choose()
                if action != "more":
                    break

        send_output("")

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


class _AbortInboxZeroError(Exception):
    """Raised from any prompt to abort the entire inbox-zero flow."""
