"""Reusable utilities for viewing and downloading email attachments."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from imap_client_lib import EmailMessage

from src.config.settings import ConfigManager
from src.email.imap_client import EnhancedImapClient
from src.interaction.scheduler_prompts import SchedulerChoice, send_output

logger = logging.getLogger(__name__)


class EmailAttachmentViewer:
    """Reusable email attachment viewing and downloading utilities."""

    @staticmethod
    def show_attachments(
        client: EnhancedImapClient,
        config: ConfigManager,
        folder: str,
        msg_id: str,
    ) -> None:
        """Fetch email, list attachments, and let user download one."""
        email_msg = EmailAttachmentViewer._fetch_email_with_attachments(
            client, folder, msg_id,
        )
        if email_msg is None:
            return

        attachments = getattr(email_msg, "attachments", []) or []
        if not attachments:
            send_output("  No attachments.")
            return

        while True:
            line = "\u2500" * 50
            send_output(f"\n{line}")
            send_output(f"  Attachments ({len(attachments)})")
            send_output(line)
            for i, att in enumerate(attachments, 1):
                send_output(f"  {i}. {att.filename} ({att.content_type})")
            send_output(line)

            choices: list[tuple[str, str]] = [
                (att.filename, f"att_{i}")
                for i, att in enumerate(attachments)
            ]
            choices.append(("Back", "back"))

            action = SchedulerChoice("Download:", choices).choose()

            if action in ("back", "abort"):
                return

            if action.startswith("att_"):
                att_idx = int(action.removeprefix("att_"))
                EmailAttachmentViewer._download_attachment(
                    attachments[att_idx], config.download_folder,
                )

    @staticmethod
    def _fetch_email_with_attachments(
        client: EnhancedImapClient,
        folder: str,
        msg_id: str,
    ) -> EmailMessage | None:
        """Fetch full email from IMAP with attachments included."""
        try:
            client.client.client.select_folder(folder)
            raw = client.client.client.fetch([int(msg_id)], [b"BODY.PEEK[]"])
            if not raw:
                send_output("  Could not fetch email.")
                return None

            msg_data = raw[int(msg_id)][b"BODY[]"]
            return EmailMessage.from_bytes(msg_id, msg_data, include_attachments=True)
        except Exception as e:
            logger.error("Error fetching email with attachments: %s", e)
            send_output(f"  Error fetching email: {e}")
            return None

    @staticmethod
    def _download_attachment(attachment: object, download_dir: Path) -> None:
        """Save attachment bytes to download directory."""
        download_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r'[^\w.\s-]', '_', attachment.filename)[:100]
        att_path = download_dir / safe_name
        try:
            att_path.write_bytes(attachment.data)
            send_output(f"  Downloaded to: {att_path}")
        except Exception as e:
            logger.error("Error downloading attachment: %s", e)
            send_output(f"  Error downloading: {e}")
