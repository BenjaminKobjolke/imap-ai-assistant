"""Assembles and saves a draft reply email to IMAP Drafts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.config.settings import ConfigManager
from src.constants import (
    CFG_EMAIL_ADDRESS,
    HEADER_DRAFT_REPLY,
    MIME_TEXT_HTML,
    PREFIX_REPLY,
)
from src.email.imap_client import EnhancedImapClient
from src.interaction.scheduler_prompts import send_output

logger = logging.getLogger(__name__)


@dataclass
class DraftEmailContent:
    """All data needed to assemble and save a draft reply."""

    to_address: str
    subject: str
    greeting: str
    body_text: str
    footer_html: str
    original_from: str
    original_subject: str
    original_body: str


class DraftEmailBuilder:
    """Builds HTML draft emails and saves them to the IMAP Drafts folder."""

    def __init__(self, config: ConfigManager, imap_client: EnhancedImapClient) -> None:
        self._config = config
        self._imap = imap_client

    def build_and_save(self, content: DraftEmailContent) -> bool:
        """Assemble HTML email and save as draft."""
        try:
            html_body = self._assemble_html(content)
            return self._save_draft(content.to_address, content.subject, html_body)
        except Exception as e:
            logger.error(f"Error building/saving draft: {e}")
            send_output(f"  Error saving draft: {e}")
            return False

    def _assemble_html(self, content: DraftEmailContent) -> str:
        """Build HTML body from greeting + body + footer + quoted original."""
        html_body_text = content.body_text.replace("\n", "<br>")
        html_original = content.original_body.replace("\n", "<br>")

        greeting_block = ""
        if content.greeting:
            greeting_block = f"""<div style="margin-bottom: 10px;">{content.greeting},</div>"""

        return f"""
<div style="font-family: Arial, sans-serif; font-size: 14px; line-height: 1.6;">
    {greeting_block}
    <div style="margin-bottom: 20px;">
        {html_body_text}
    </div>

    {content.footer_html}

    <hr style="margin: 20px 0; border: none; border-top: 1px solid #ccc;">

    <div style="color: #666; font-size: 12px; background-color: #f9f9f9; padding: 10px; border-left: 3px solid #ddd;">
        <strong>-----Original Message-----</strong><br>
        <strong>From:</strong> {content.original_from}<br>
        <strong>Subject:</strong> {content.original_subject}<br><br>
        <div style="margin-top: 10px;">
            {html_original}
        </div>
    </div>
</div>
"""

    def _save_draft(self, to_address: str, subject: str, html_body: str) -> bool:
        """Save the assembled email as a draft via IMAP."""
        account = self._config.get_first_account()
        if not account:
            logger.error("No main account configuration found")
            return False

        drafts_folder = self._config.get_drafts_folder(account)
        from_email = account.get(CFG_EMAIL_ADDRESS, "")

        draft_headers = {
            HEADER_DRAFT_REPLY: datetime.now().isoformat(),
        }

        success = self._imap.client.save_draft(
            to_addresses=[to_address],
            subject=subject,
            body=html_body,
            from_email=from_email,
            custom_headers=draft_headers,
            draft_folder=drafts_folder,
            content_type=MIME_TEXT_HTML,
        )

        if success:
            send_output(f"  Draft saved to '{drafts_folder}'")
            logger.info(f"Draft reply saved for {to_address}: {subject}")
        else:
            send_output("  Failed to save draft.")
            logger.error(f"Failed to save draft for {to_address}")

        return bool(success)

    @staticmethod
    def load_footer_html() -> str:
        """Load footer HTML from data/footer.html."""
        try:
            footer_path = Path("data/footer.html")
            if footer_path.exists():
                with open(footer_path, encoding="utf-8") as f:
                    return f.read()
        except Exception as e:
            logger.warning(f"Could not load footer HTML: {e}")
        return ""

    @staticmethod
    def make_reply_subject(original_subject: str) -> str:
        """Ensure subject starts with 'Re: '."""
        if original_subject.lower().startswith("re: "):
            return original_subject
        return f"{PREFIX_REPLY}{original_subject}"
