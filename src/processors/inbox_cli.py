"""Non-interactive inbox CLI operations for subprocess-based plugin usage."""

from __future__ import annotations

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

logger = logging.getLogger(__name__)


class InboxCli:
    """Non-interactive inbox operations invoked via CLI flags."""

    def __init__(self, config: ConfigManager) -> None:
        self._config = config

    def _connect(self) -> EnhancedImapClient | None:
        """Connect to the main IMAP account. Returns client or None on failure."""
        account_config = self._config.get_first_account()
        if not account_config:
            print("Error: no main account configuration found")
            return None
        client = EnhancedImapClient(account_config)
        if not client.connect():
            print("Error: failed to connect to IMAP server")
            return None
        return client

    def _get_messages(
        self, client: EnhancedImapClient, *, unread_only: bool = False,
    ) -> list[tuple[object, object]]:
        """Fetch INBOX messages. Returns list of (msg_id, email_msg)."""
        if unread_only:
            return client.client.get_unread_messages()
        return client.client.get_all_messages(folder=FOLDER_INBOX)

    def list_inbox(self, *, unread_only: bool = False) -> None:
        """List INBOX emails: [INDEX] FROM | SUBJECT | DATE (1-based)."""
        client = self._connect()
        if not client:
            return
        try:
            messages = self._get_messages(client, unread_only=unread_only)
            if not messages:
                print("INBOX is empty.")
                return

            label = "unread " if unread_only else ""
            print(f"Found {len(messages)} {label}email(s) in INBOX:\n")
            for i, (_msg_id, email_msg) in enumerate(messages, 1):
                from_addr = getattr(email_msg, "from_address", "(unknown)") or "(unknown)"
                subject = getattr(email_msg, "subject", "(no subject)") or "(no subject)"
                date = getattr(email_msg, "date", "") or ""
                print(f"[{i}] {from_addr} | {subject} | {date}")
        finally:
            client.disconnect()

    def show_email(self, index: int) -> None:
        """Show full email details at 1-based index (from, subject, date, body)."""
        client = self._connect()
        if not client:
            return
        try:
            messages = self._get_messages(client)
            if not messages:
                print("INBOX is empty.")
                return
            if index < 1 or index > len(messages):
                print(f"Error: index {index} out of range (1-{len(messages)})")
                return

            _msg_id, email_msg = messages[index - 1]
            from_addr = getattr(email_msg, "from_address", "(unknown)") or "(unknown)"
            subject = getattr(email_msg, "subject", "(no subject)") or "(no subject)"
            date = getattr(email_msg, "date", "") or ""

            print(f"From:    {from_addr}")
            print(f"Subject: {subject}")
            print(f"Date:    {date}")
            print("-" * 50)

            body = self._get_body(email_msg)
            print(body)
        finally:
            client.disconnect()

    def move_email(self, index: int, folder: str) -> None:
        """Move email at index to folder. Marks as read."""
        client = self._connect()
        if not client:
            return
        try:
            messages = self._get_messages(client)
            if not messages:
                print("INBOX is empty.")
                return
            if index < 1 or index > len(messages):
                print(f"Error: index {index} out of range (1-{len(messages)})")
                return

            msg_id, _email_msg = messages[index - 1]
            client.client.client.select_folder(FOLDER_INBOX)
            client.client.mark_as_read(str(msg_id))
            success = client.client.move_to_folder(msg_id, folder)
            if success:
                print(f"Moved email {index} to '{folder}'")
            else:
                print(f"Failed to move email {index} to '{folder}'")
        finally:
            client.disconnect()

    def trash_email(self, index: int) -> None:
        """Move email at index to trash folder. Marks as read."""
        trash = self._config.trash_folder
        self.move_email(index, trash)

    def list_folders(self) -> None:
        """Print all available IMAP folders, sorted."""
        client = self._connect()
        if not client:
            return
        try:
            folders = sorted(client.client.list_folders())
            if not folders:
                print("No folders found.")
                return
            print(f"Available folders ({len(folders)}):\n")
            for folder in folders:
                print(f"  {folder}")
        finally:
            client.disconnect()

    def todo_from_email(self, index: int) -> None:
        """Create RTM todo from email content, move to target_folder."""
        client = self._connect()
        if not client:
            return
        try:
            messages = self._get_messages(client)
            if not messages:
                print("INBOX is empty.")
                return
            if index < 1 or index > len(messages):
                print(f"Error: index {index} out of range (1-{len(messages)})")
                return

            msg_id, email_msg = messages[index - 1]
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
                print("Error: no OpenAI API key configured")
                return

            openai_client = OpenAIClient(api_key, model, max_tokens, temperature, other_people)
            result = TodoService.generate_todo(openai_client, subject, first_line, body_excerpt)
            if not result:
                print("Failed to generate todo from email.")
                return

            todo_svc = TodoService(self._config)
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
                print("Failed to send todo to RTM.")
                return

            print(f"Todo created: {todo_text} {subject_tag}")

            # Move to target folder
            target_folder = rules[CFG_TARGET_FOLDER]
            client.client.client.select_folder(FOLDER_INBOX)
            client.client.mark_as_read(str(msg_id))
            client.client.move_to_folder(msg_id, target_folder)
            print(f"Moved email {index} to '{target_folder}'")
        finally:
            client.disconnect()

    def send_todo_from_email(self, index: int, title: str, priority: int, due_date: str) -> None:
        """Send a confirmed todo from email content and move to target_folder.

        Unlike todo_from_email, this skips AI generation and uses the provided values.
        """
        client = self._connect()
        if not client:
            return
        try:
            messages = self._get_messages(client)
            if not messages:
                print("INBOX is empty.")
                return
            if index < 1 or index > len(messages):
                print(f"Error: index {index} out of range (1-{len(messages)})")
                return

            msg_id, email_msg = messages[index - 1]
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
                print("Failed to send todo to RTM.")
                return

            print(f"Todo created: {todo_text} {subject_tag}")

            # Move to target folder
            target_folder = rules[CFG_TARGET_FOLDER]
            client.client.client.select_folder(FOLDER_INBOX)
            client.client.mark_as_read(str(msg_id))
            client.client.move_to_folder(msg_id, target_folder)
            print(f"Moved email {index} to '{target_folder}'")
        finally:
            client.disconnect()

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
