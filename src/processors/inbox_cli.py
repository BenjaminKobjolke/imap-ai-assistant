"""Non-interactive inbox CLI operations for subprocess-based plugin usage."""

from __future__ import annotations

import html
import logging
import re

from src.config.settings import ConfigManager
from src.constants import (
    CFG_ADDITIONAL_SUBJECT_TAG,
    CFG_TARGET_FOLDER,
    FOLDER_INBOX,
    MIME_TEXT_HTML,
    MIME_TEXT_PLAIN,
)
from src.email.imap_client import EnhancedImapClient
from src.interaction.scheduler_prompts import send_output

logger = logging.getLogger(__name__)


class InboxCli:
    """Non-interactive inbox operations invoked via CLI flags."""

    def __init__(self, config: ConfigManager) -> None:
        self._config = config

    def _connect(self) -> EnhancedImapClient | None:
        """Connect to the main IMAP account. Returns client or None on failure."""
        account_config = self._config.get_first_account()
        if not account_config:
            send_output("Error: no main account configuration found")
            return None
        client = EnhancedImapClient(account_config)
        if not client.connect():
            send_output("Error: failed to connect to IMAP server")
            return None
        return client

    def _get_messages(
        self, client: EnhancedImapClient, *, unread_only: bool = False,
    ) -> list[tuple[object, object]]:
        """Fetch INBOX messages. Returns list of (msg_id, email_msg)."""
        if unread_only:
            return client.client.get_unread_messages()
        return client.client.get_all_messages(folder=FOLDER_INBOX)

    def _find_by_id(
        self, messages: list[tuple[object, object]], email_id: str,
    ) -> tuple[object, object]:
        """Find an email by its IMAP UID. Raises ValueError if not found."""
        for msg_id, email_msg in messages:
            if str(msg_id) == email_id:
                return msg_id, email_msg
        msg = f"Email with id {email_id} not found"
        raise ValueError(msg)

    def list_inbox(self, *, unread_only: bool = False) -> None:
        """List INBOX emails: [id:ID] [INDEX] FROM | SUBJECT | DATE."""
        client = self._connect()
        if not client:
            return
        try:
            messages = self._get_messages(client, unread_only=unread_only)
            if not messages:
                send_output("INBOX is empty.")
                return

            label = "unread " if unread_only else ""
            send_output(f"Found {len(messages)} {label}email(s) in INBOX:\n")
            for i, (msg_id, email_msg) in enumerate(messages, 1):
                from_addr = getattr(email_msg, "from_address", "(unknown)") or "(unknown)"
                subject = getattr(email_msg, "subject", "(no subject)") or "(no subject)"
                date = getattr(email_msg, "date", "") or ""
                send_output(f"[id:{msg_id}] [{i}] {from_addr} | {subject} | {date}")
        finally:
            client.disconnect()

    def show_email(self, email_id: str) -> None:
        """Show full email details by ID (from, subject, date, body)."""
        client = self._connect()
        if not client:
            return
        try:
            messages = self._get_messages(client)
            if not messages:
                send_output("INBOX is empty.")
                return

            try:
                _msg_id, email_msg = self._find_by_id(messages, email_id)
            except ValueError as e:
                send_output(f"Error: {e}")
                return

            from_addr = getattr(email_msg, "from_address", "(unknown)") or "(unknown)"
            subject = getattr(email_msg, "subject", "(no subject)") or "(no subject)"
            date = getattr(email_msg, "date", "") or ""

            send_output(f"From:    {from_addr}")
            send_output(f"Subject: {subject}")
            send_output(f"Date:    {date}")
            send_output("-" * 50)

            body = self._get_body(email_msg)
            send_output(body)
        finally:
            client.disconnect()

    def move_email(self, email_id: str, folder: str) -> None:
        """Move email by ID to folder. Marks as read."""
        client = self._connect()
        if not client:
            return
        try:
            messages = self._get_messages(client)
            if not messages:
                send_output("INBOX is empty.")
                return

            try:
                msg_id, _email_msg = self._find_by_id(messages, email_id)
            except ValueError as e:
                send_output(f"Error: {e}")
                return

            client.client.client.select_folder(FOLDER_INBOX)
            client.client.mark_as_read(str(msg_id))
            success = client.client.move_to_folder(msg_id, folder)
            if success:
                send_output(f"Moved email {email_id} to '{folder}'")
            else:
                send_output(f"Failed to move email {email_id} to '{folder}'")
        finally:
            client.disconnect()

    def trash_email(self, email_id: str) -> None:
        """Move email by ID to trash folder. Marks as read."""
        trash = self._config.trash_folder
        self.move_email(email_id, trash)

    def list_folders(self) -> None:
        """Print all available IMAP folders, sorted."""
        client = self._connect()
        if not client:
            return
        try:
            folders = sorted(client.client.list_folders())
            if not folders:
                send_output("No folders found.")
                return
            send_output(f"Available folders ({len(folders)}):\n")
            for folder in folders:
                send_output(f"  {folder}")
        finally:
            client.disconnect()

    def todo_from_email(self, email_id: str) -> None:
        """Create RTM todo from email content, move to target_folder."""
        client = self._connect()
        if not client:
            return
        try:
            messages = self._get_messages(client)
            if not messages:
                send_output("INBOX is empty.")
                return

            try:
                msg_id, email_msg = self._find_by_id(messages, email_id)
            except ValueError as e:
                send_output(f"Error: {e}")
                return

            subject, first_line, body_excerpt = client.extract_email_content(email_msg)
            from_address = getattr(email_msg, "from_address", "") or ""

            # Create and send todo
            from src.ai.openai_client import OpenAIClient
            from src.services.todo_service import TodoService

            api_key = self._config.openai_api_key
            model = self._config.openai_model
            max_tokens = self._config.openai_max_completion_tokens
            temperature = self._config.openai_temperature
            other_people = self._config.get_other_people_names()

            if not api_key:
                send_output("Error: no OpenAI API key configured")
                return

            openai_client = OpenAIClient(api_key, model, max_tokens, temperature, other_people)
            todo_svc = TodoService(self._config)
            result = TodoService.generate_todo(
                openai_client, subject, first_line, body_excerpt,
                todo_svc.resolve_rule_prompt(from_address, subject),
            )
            if not result:
                send_output("Failed to generate todo from email.")
                return

            rules = self._config.get_processing_rules("self")
            subject_tag = rules[CFG_ADDITIONAL_SUBJECT_TAG]

            extra = todo_svc.resolve_extra_tags(from_address, subject)
            if extra:
                subject_tag = f"{subject_tag} {extra}"

            todo_text = result.rtm_text
            success, _ = todo_svc.send_todo(
                todo_text, subject_tag, subject, from_address,
            )
            if not success:
                send_output("Failed to send todo to RTM.")
                return

            send_output(f"Todo created: {todo_text} {subject_tag}")

            # Move to target folder
            target_folder = rules[CFG_TARGET_FOLDER]
            client.client.client.select_folder(FOLDER_INBOX)
            client.client.mark_as_read(str(msg_id))
            client.client.move_to_folder(msg_id, target_folder)
            send_output(f"Moved email {email_id} to '{target_folder}'")
        finally:
            client.disconnect()

    def send_todo_from_email(self, email_id: str, title: str, priority: int, due_date: str) -> None:
        """Send a confirmed todo from email content and move to target_folder.

        Unlike todo_from_email, this skips AI generation and uses the provided values.
        """
        client = self._connect()
        if not client:
            return
        try:
            messages = self._get_messages(client)
            if not messages:
                send_output("INBOX is empty.")
                return

            try:
                msg_id, email_msg = self._find_by_id(messages, email_id)
            except ValueError as e:
                send_output(f"Error: {e}")
                return

            subject = getattr(email_msg, "subject", "") or ""
            from_address = getattr(email_msg, "from_address", "") or ""

            from src.services.todo_service import TodoService

            todo_svc = TodoService(self._config)
            rules = self._config.get_processing_rules("self")
            subject_tag = rules[CFG_ADDITIONAL_SUBJECT_TAG]

            extra = todo_svc.resolve_extra_tags(from_address, subject)
            if extra:
                subject_tag = f"{subject_tag} {extra}"

            todo_text = f"{title} !{priority} ^{due_date}"
            success, _ = todo_svc.send_todo(
                todo_text, subject_tag, subject, from_address,
            )
            if not success:
                send_output("Failed to send todo to RTM.")
                return

            send_output(f"Todo created: {todo_text} {subject_tag}")

            # Move to target folder
            target_folder = rules[CFG_TARGET_FOLDER]
            client.client.client.select_folder(FOLDER_INBOX)
            client.client.mark_as_read(str(msg_id))
            client.client.move_to_folder(msg_id, target_folder)
            send_output(f"Moved email {email_id} to '{target_folder}'")
        finally:
            client.disconnect()

    def prepare_reply(self, email_id: str) -> None:
        """Output email content + cached salutation for drafting a reply."""
        client = self._connect()
        if not client:
            return
        try:
            messages = self._get_messages(client)
            if not messages:
                send_output("INBOX is empty.")
                return

            try:
                _msg_id, email_msg = self._find_by_id(messages, email_id)
            except ValueError as e:
                send_output(f"Error: {e}")
                return

            from_addr = getattr(email_msg, "from_address", "(unknown)") or "(unknown)"
            subject = getattr(email_msg, "subject", "(no subject)") or "(no subject)"
            date = getattr(email_msg, "date", "") or ""

            # Look up cached salutation
            salutation_text = "unknown"
            try:
                from src.search.search_cache import SearchCache

                cache = SearchCache(self._config.search_cache_path)
                sal = cache.get_salutation(from_addr)
                if sal:
                    formality = "formal" if sal["is_formal"] else "informal"
                    salutation_text = f"{sal['salutation']} ({formality})"
            except Exception:
                pass

            send_output(f"From: {from_addr}")
            send_output(f"Subject: {subject}")
            send_output(f"Date: {date}")
            send_output(f"Salutation: {salutation_text}")
            send_output("--- Body ---")

            body = self._get_body(email_msg, max_chars=3000)
            send_output(body)

            # When salutation is unknown, include sent email excerpts for context
            if salutation_text == "unknown":
                excerpts = self._search_sent_excerpts(client, from_addr)
                if excerpts:
                    send_output(f"--- Sent Emails to {from_addr} ---")
                    for i, excerpt in enumerate(excerpts, 1):
                        send_output(f"[{i}] {excerpt}")
        finally:
            client.disconnect()

    def save_draft_reply(self, email_id: str, body_text: str) -> None:
        """Save a reply draft to the IMAP Drafts folder."""
        client = self._connect()
        if not client:
            return
        try:
            messages = self._get_messages(client)
            if not messages:
                send_output("INBOX is empty.")
                return

            try:
                _msg_id, email_msg = self._find_by_id(messages, email_id)
            except ValueError as e:
                send_output(f"Error: {e}")
                return

            from_addr = getattr(email_msg, "from_address", "(unknown)") or "(unknown)"
            subject = getattr(email_msg, "subject", "(no subject)") or "(no subject)"
            original_body = self._get_body(email_msg)

            from src.processors.draft_email_builder import (
                DraftEmailBuilder,
                DraftEmailContent,
            )

            reply_subject = DraftEmailBuilder.make_reply_subject(subject)
            footer_html = DraftEmailBuilder.load_footer_html()

            content = DraftEmailContent(
                to_address=from_addr,
                subject=reply_subject,
                greeting="",
                body_text=body_text,
                footer_html=footer_html,
                original_from=from_addr,
                original_subject=subject,
                original_body=original_body,
            )

            builder = DraftEmailBuilder(self._config, client)
            success = builder.build_and_save(content)
            if success:
                send_output(f"Draft saved to 'Drafts': {reply_subject}")
            else:
                send_output("Failed to save draft.")
        finally:
            client.disconnect()

    def _search_sent_excerpts(
        self, client: EnhancedImapClient, to_address: str,
    ) -> list[str]:
        """Search sent folder for recent emails to *to_address*.

        Returns up to 10 body excerpts (100 chars each).
        """
        max_excerpts = 10
        max_chars = 100
        try:
            account = self._config.get_first_account()
            if not account:
                return []

            sent_folder = self._config.get_sent_folder(account)
            messages = client.client.get_all_messages(
                folder=sent_folder, include_attachments=False,
            )

            excerpts: list[str] = []
            for _msg_id, email_msg in messages:
                to_addr = getattr(email_msg, "to", None) or getattr(email_msg, "to_address", None)
                if not to_addr or to_address.lower() not in to_addr.lower():
                    continue

                try:
                    _subject, _first_line, body = client.extract_email_content(email_msg)
                    if body:
                        clean = re.sub(r"<[^>]+>", "", body)
                        clean = html.unescape(clean)
                        clean = " ".join(clean.split())
                        excerpts.append(clean[:max_chars])
                except Exception:
                    continue

                if len(excerpts) >= max_excerpts:
                    break

            return excerpts
        except Exception:
            return []

    def save_salutation(self, email_address: str, salutation: str, is_formal: bool) -> None:
        """Save a salutation to the cache for future lookups."""
        from src.search.search_cache import SearchCache

        cache = SearchCache(self._config.search_cache_path)
        cache.save_salutation(email_address, salutation, is_formal=is_formal)
        formality = "formal" if is_formal else "informal"
        send_output(f"Salutation saved for {email_address}: {salutation} ({formality})")

    @staticmethod
    def _get_body(email_msg: object, max_chars: int = 5000) -> str:
        """Extract a plain-text body from the email message."""
        body = None
        if hasattr(email_msg, "get_body"):
            body = email_msg.get_body(MIME_TEXT_PLAIN)
            if not body:
                html = email_msg.get_body(MIME_TEXT_HTML)
                if html:
                    body = re.sub(r"<[^>]+>", "", html).strip()
        if not body:
            return "(no body content)"
        return str(body)[:max_chars]
