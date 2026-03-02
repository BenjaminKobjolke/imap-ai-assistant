from __future__ import annotations

import logging
import re
from typing import List, Tuple, Optional
from imap_client_lib import ImapClient as BaseImapClient, Account
from email.utils import parseaddr

logger = logging.getLogger(__name__)


class EnhancedImapClient:
    """Enhanced IMAP client with filtering and folder management capabilities."""

    def __init__(self, account_config: dict):
        self.account = Account(
            name=account_config["name"],
            server=account_config["server"],
            username=account_config["username"],
            password=account_config["password"],
            port=account_config["port"],
            use_ssl=account_config["use_ssl"]
        )
        self.client = BaseImapClient(self.account)
        self.connected = False

    def connect(self) -> bool:
        """Connect to IMAP server."""
        try:
            if self.client.connect():
                self.connected = True
                logger.info(f"Connected to IMAP server {self.account.server}")
                return True
            else:
                logger.error("Failed to connect to IMAP server")
                return False
        except Exception as e:
            logger.error(f"Error connecting to IMAP server: {e}")
            return False

    def disconnect(self) -> None:
        """Disconnect from IMAP server."""
        try:
            if self.connected:
                self.client.disconnect()
                self.connected = False
                logger.info("Disconnected from IMAP server")
        except Exception as e:
            logger.error(f"Error disconnecting from IMAP server: {e}")

    def get_filtered_unread_messages(self, allowed_senders: List[str]) -> List[Tuple[str, object]]:
        """Get unread messages filtered by allowed senders."""
        if not self.connected:
            logger.error("Not connected to IMAP server")
            return []

        try:
            # Get all unread messages
            all_messages = self.client.get_unread_messages()
            filtered_messages = []

            for message_id, email_message in all_messages:
                # Check if sender is in allowed list
                sender_email = self._extract_email_address(email_message.from_address)
                if sender_email and sender_email.lower() in [s.lower() for s in allowed_senders]:
                    filtered_messages.append((message_id, email_message))
                    logger.debug(f"Message from {sender_email} matches allowed senders")
                else:
                    logger.debug(f"Message from {sender_email} not in allowed senders, skipping")

            logger.info(f"Found {len(filtered_messages)} unread messages from allowed senders")
            return filtered_messages

        except Exception as e:
            logger.error(f"Error getting filtered unread messages: {e}")
            return []

    def _extract_email_address(self, from_field: str) -> Optional[str]:
        """Extract email address from 'From' field."""
        try:
            # Parse "Name <email@domain.com>" format
            name, email_addr = parseaddr(from_field)
            return email_addr if email_addr else None
        except Exception as e:
            logger.debug(f"Error parsing email address from '{from_field}': {e}")
            return None

    def extract_email_content(self, email_message) -> Tuple[str, str, str]:
        """Extract subject, first line, and body excerpt from email message."""
        subject = email_message.subject or ""
        first_line = ""
        body_excerpt = ""

        try:
            # Use the new get_body method - much simpler and more reliable!
            body_text = email_message.get_body("text/plain")

            # If no plain text, try HTML and strip tags
            if not body_text:
                html_body = email_message.get_body("text/html")
                if html_body:
                    body_text = re.sub(r'<[^>]+>', '', html_body).strip()

            if body_text:
                # Get the first line of text
                first_line = body_text.split('\n')[0].strip()
                if len(first_line) > 200:  # Limit length
                    first_line = first_line[:200] + "..."

                # Get body excerpt (first 300 characters)
                body_excerpt = body_text[:800]

        except Exception as e:
            logger.debug(f"Error extracting email content: {e}")

        # Ensure we always return valid strings
        return subject or "", first_line or "", body_excerpt or ""

    def mark_message_as_read(self, message_id: str) -> bool:
        """Mark a message as read."""
        try:
            self.client.mark_as_read(message_id)
            logger.debug(f"Marked message {message_id} as read")
            return True
        except Exception as e:
            logger.error(f"Error marking message {message_id} as read: {e}")
            return False

    def append_to_folder(
        self, folder: str, message_bytes: bytes, flags: list[bytes] | None = None,
    ) -> bool:
        """Append a fully-composed message to an IMAP folder.

        Uses the same low-level IMAP append as invite_processor.py.
        """
        if flags is None:
            flags = [b"\\Seen"]

        try:
            self.client.client.append(folder, message_bytes, flags)
            logger.info(f"Appended message to IMAP folder \"{folder}\"")
            return True
        except Exception as e:
            logger.error(f"Failed to append message to IMAP folder \"{folder}\": {e}")
            return False

    def _strip_subject_prefixes(self, subject: str) -> str:
        """Strip common email prefixes from subject line."""
        if not subject:
            return ""

        # Common prefixes to remove
        prefixes = [r'^(Re:|Fwd?:|FW:|AW:|WG:)\s*', r'^(RE:|FWD:|FORWARD:)\s*']

        cleaned_subject = subject.strip()
        for prefix_pattern in prefixes:
            cleaned_subject = re.sub(prefix_pattern, '', cleaned_subject, flags=re.IGNORECASE)
            cleaned_subject = cleaned_subject.strip()

        return cleaned_subject

