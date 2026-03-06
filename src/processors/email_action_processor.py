"""Action processor for regular (non-invite) emails in inbox-zero."""

from __future__ import annotations

import logging

from src.ai.openai_client import OpenAIClient
from src.config.settings import ConfigManager
from src.constants import (
    ACTION_DRAFT_REPLY,
    CFG_TARGET_FOLDER,
    FOLDER_INBOX,
)
from src.email.draft_reply_handler import DraftReplyHandler
from src.email.email_body_viewer import EmailBodyViewer
from src.email.imap_client import EnhancedImapClient
from src.email.smtp_client import SmtpClient
from src.interaction.scheduler_prompts import send_output
from src.processors.action_result import ActionResult
from src.search.folder_picker import folder_search_loop
from src.search.search_cache import SearchCache
from src.services.todo_service import TodoService

logger = logging.getLogger(__name__)


class EmailActionProcessor:
    """Handles regular email actions: move, todo, draft reply.

    Extracted from ``InboxZero`` so the orchestrator only manages the loop
    while this class owns the business logic for each action.
    """

    def __init__(
        self,
        client: EnhancedImapClient,
        config: ConfigManager,
        smtp_client: SmtpClient,
        openai_client: OpenAIClient,
        cache: SearchCache,
    ) -> None:
        self._client = client
        self._config = config
        self._smtp_client = smtp_client
        self._openai_client = openai_client
        self._cache = cache
        self._todo_processor = TodoService(config)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_options(self, suggestion: str | None) -> list[tuple[str, str]]:
        """Return action choices for a regular email."""
        if suggestion:
            return [
                (f"Move to '{suggestion}'", "move_suggested"),
                ("Move to other folder", "move_other"),
                ("Add todo", "todo"),
                ("Draft a reply", ACTION_DRAFT_REPLY),
            ]
        return [
            ("Move to folder", "move_other"),
            ("Add todo", "todo"),
            ("Draft a reply", ACTION_DRAFT_REPLY),
        ]

    def execute_action(
        self,
        action: str,
        msg_id: object,
        email_msg: object,
        suggestion: str | None = None,
        *,
        dry_run: bool = False,
    ) -> ActionResult:
        """Execute the chosen action and return a result."""
        if action in ("move_suggested", "move_other"):
            target = suggestion if action == "move_suggested" else None
            return self._action_move(msg_id, target, dry_run=dry_run)

        if action == "todo":
            return self._action_todo(msg_id, email_msg, dry_run=dry_run)

        if action == ACTION_DRAFT_REPLY:
            self._action_draft_reply(email_msg)
            return ActionResult(success=True, action_type="drafted", continue_loop=True)

        return ActionResult(success=False, action_type="skipped")

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    def _action_move(
        self,
        msg_id: object,
        target: str | None,
        *,
        dry_run: bool = False,
    ) -> ActionResult:
        """Move email to a target folder."""
        if target is None:
            target = self._search_folder()
        if not target:
            send_output("  No folder selected — skipping.")
            return ActionResult(success=False, action_type="skipped")
        if target == "_abort_":
            return ActionResult(success=False, action_type="abort")

        if dry_run:
            send_output(f"  DRY RUN: would move to '{target}'")
            return ActionResult(success=True, action_type="moved")

        try:
            self._client.client.client.select_folder(FOLDER_INBOX)
            self._client.client.mark_as_read(str(msg_id))
            success = self._client.client.move_to_folder(msg_id, target)
            if success:
                send_output(f"  Moved to '{target}'")
            else:
                send_output(f"  Failed to move to '{target}'")
            return ActionResult(success=bool(success), action_type="moved" if success else "skipped")
        except Exception as e:
            logger.error("Failed to move email: %s", e)
            send_output(f"  Error moving email: {e}")
            return ActionResult(success=False, action_type="skipped")

    def _action_todo(
        self,
        msg_id: object,
        email_msg: object,
        *,
        dry_run: bool = False,
    ) -> ActionResult:
        """Create an RTM todo from the email, then move to target folder."""
        subject, first_line, body_excerpt = self._client.extract_email_content(email_msg)
        from_address = getattr(email_msg, "from_address", "") or ""

        success, _todo_text = self._todo_processor.create_and_send(
            self._openai_client,
            subject, first_line, body_excerpt, from_address,
            dry_run=dry_run,
        )
        if not success:
            return ActionResult(success=False, action_type="skipped")

        target_folder = self._config.get_processing_rules("self")[CFG_TARGET_FOLDER]
        if dry_run:
            send_output(f"  DRY RUN: would move to '{target_folder}'")
            return ActionResult(success=True, action_type="todoed")

        try:
            self._client.client.client.select_folder(FOLDER_INBOX)
            self._client.client.mark_as_read(str(msg_id))
            self._client.client.move_to_folder(msg_id, target_folder)
            send_output(f"  Moved to '{target_folder}'")
        except Exception as e:
            logger.warning("Failed to move email after todo: %s", e)

        return ActionResult(success=True, action_type="todoed")

    def _action_draft_reply(self, email_msg: object) -> None:
        """Draft a reply to the email using AI."""
        from_addr_raw = getattr(email_msg, "from_address", "") or ""
        subject = getattr(email_msg, "subject", "") or ""
        body = EmailBodyViewer.get_body_excerpt(email_msg, max_chars=2000)

        handler = DraftReplyHandler(self._client, self._config, self._openai_client, self._cache)
        handler.draft_reply(from_addr_raw, subject, body)

    # ------------------------------------------------------------------
    # Folder search helpers
    # ------------------------------------------------------------------

    def _search_folder(self) -> str | None:
        """Search for a destination folder by partial name.

        Returns the selected folder, ``"_abort_"`` if the user wants to
        abort the entire inbox-zero flow, or ``None`` to skip.
        """
        try:
            all_folders = sorted(self._client.client.list_folders())
        except Exception as e:
            logger.error("Could not list folders: %s", e)
            send_output(f"  Could not list folders: {e}")
            return None

        if not all_folders:
            send_output("  No folders found.")
            return None

        return folder_search_loop(all_folders, allow_abort=True)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_body_excerpt(email_msg: object, max_chars: int = 800) -> str:
        """Extract a plain-text excerpt from the email body."""
        return EmailBodyViewer.get_body_excerpt(email_msg, max_chars=max_chars)
