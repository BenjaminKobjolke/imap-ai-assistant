"""Shared utilities for fetching and displaying email bodies."""

from __future__ import annotations

import logging
import re

from imap_client_lib import EmailMessage

from src.constants import MIME_TEXT_HTML, MIME_TEXT_PLAIN
from src.email.imap_client import EnhancedImapClient
from src.interaction.scheduler_prompts import send_output

logger = logging.getLogger(__name__)


class EmailBodyViewer:
    """Reusable email body fetching and display utilities."""

    @staticmethod
    def show_body(client: EnhancedImapClient, folder: str, msg_id: str) -> None:
        """Fetch and display the full body from IMAP."""
        try:
            client.client.client.select_folder(folder)
            raw = client.client.client.fetch([int(msg_id)], [b"BODY.PEEK[]"])
            if not raw:
                send_output("  Could not fetch email body.")
                return

            msg_data = raw[int(msg_id)][b"BODY[]"]
            email_msg = EmailMessage.from_bytes(msg_id, msg_data, include_attachments=False)
            body = email_msg.get_body(MIME_TEXT_PLAIN)

            if not body:
                html = email_msg.get_body(MIME_TEXT_HTML)
                if html:
                    body = re.sub(r"<[^>]+>", "", html).strip()

            if body:
                send_output(f"\n{'─' * 50}")
                send_output(body)
                send_output(f"{'─' * 50}\n")
            else:
                send_output("  (empty body)")
        except Exception as e:
            logger.error("Error fetching email body: %s", e)
            send_output(f"  Error fetching body: {e}")

    @staticmethod
    def get_body_excerpt(email_msg: object, max_chars: int = 800) -> str:
        """Extract a plain-text excerpt from the email body."""
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
