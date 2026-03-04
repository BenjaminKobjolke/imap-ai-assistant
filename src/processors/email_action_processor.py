"""Action processor for regular (non-invite) emails in inbox-zero."""

from __future__ import annotations

import logging
from email.utils import parseaddr

from src.ai.openai_client import OpenAIClient
from src.config.settings import ConfigManager
from src.constants import (
    ACTION_DRAFT_REPLY,
    CFG_TARGET_FOLDER,
    FOLDER_INBOX,
    MIME_TEXT_HTML,
    MIME_TEXT_PLAIN,
)
from src.email.imap_client import EnhancedImapClient
from src.email.smtp_client import SmtpClient
from src.interaction.scheduler_prompts import SchedulerChoice, scheduler_ask, send_output
from src.processors.action_result import ActionResult
from src.processors.draft_composer import DraftComposer, DraftContext
from src.processors.draft_email_builder import DraftEmailBuilder, DraftEmailContent
from src.processors.greeting_builder import GreetingBuilder
from src.processors.rtm_todo import RtmTodoCreator
from src.processors.salutation_manager import SalutationManager
from src.search.search_cache import SearchCache

logger = logging.getLogger(__name__)

_MAX_FOLDER_MATCHES = 5


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

        success, _todo_text = RtmTodoCreator.create_and_send(
            self._openai_client, self._smtp_client, self._config,
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
        _, from_addr = parseaddr(from_addr_raw)
        from_name = from_addr_raw.replace(f"<{from_addr}>", "").strip().strip('"')
        subject = getattr(email_msg, "subject", "") or ""
        body = self._get_body_excerpt(email_msg, max_chars=2000)

        sal_mgr = SalutationManager(self._cache, self._config, self._openai_client, self._client)
        salutation_info = sal_mgr.resolve_salutation(from_addr)

        greeting = GreetingBuilder.build_greeting(salutation_info)

        context = DraftContext(
            original_subject=subject,
            original_body=body,
            original_from_address=from_addr,
            original_from_name=from_name,
            greeting=greeting,
        )
        composer = DraftComposer(self._openai_client)
        final_body = composer.compose(context)

        if not final_body:
            send_output("  Draft cancelled.")
            return

        builder = DraftEmailBuilder(self._config, self._client)
        content = DraftEmailContent(
            to_address=from_addr,
            subject=DraftEmailBuilder.make_reply_subject(subject),
            greeting=greeting,
            body_text=final_body,
            footer_html=DraftEmailBuilder.load_footer_html(),
            original_from=from_addr_raw,
            original_subject=subject,
            original_body=body,
        )
        builder.build_and_save(content)

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

        return self._folder_search_loop(all_folders)

    def _folder_search_loop(self, all_folders: list[str]) -> str | None:
        """Prompt for a partial folder name, filter, and let the user pick."""
        while True:
            query = scheduler_ask(
                "Type part of the folder name (or 'cancel' / 'abort'):", default="",
            )
            query = query.strip()
            if not query or query.lower() == "cancel":
                return None
            if query.lower() == "abort":
                return "_abort_"

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

            result = self._pick_from_matches(matches)
            if result is not None:
                return result

    @staticmethod
    def _pick_from_matches(matches: list[str]) -> str | None:
        """Show matched folders and let the user pick one or search again."""
        choices = [(m, m) for m in matches] + [("Search again", "search_again")]
        result = SchedulerChoice("Select folder:", choices, abort=True).choose()
        if result == "abort":
            return "_abort_"
        if result == "search_again":
            return None
        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

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
