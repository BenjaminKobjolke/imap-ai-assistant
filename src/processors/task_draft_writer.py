from __future__ import annotations

import logging
from html import escape
from typing import Any

from src.config.settings import ConfigManager
from src.constants import CFG_EMAIL_ADDRESS, MIME_TEXT_HTML, MIME_TEXT_PLAIN
from src.email.imap_client import EnhancedImapClient
from src.email.smtp_client import build_rtm_todo_body

logger = logging.getLogger(__name__)

FORWARD_SEPARATOR = "---------- Forwarded message ----------"


class TaskDraftWriter:
    """Saves the workflow's outgoing mails as drafts in the main account, for sending by hand."""

    def __init__(self, config: ConfigManager):
        self._config = config

    def save_rtm_todo(self, todo_text: str, subject_tag: str, original_subject: str,
                      original_sender: str, task_tracking_headers: dict[str, str]) -> bool:
        """Draft the RTM todo mail so the todo is only created once the user sends it."""
        rtm_email = self._config.rtm_email
        if not rtm_email:
            logger.error("RTM email address not configured")
            return False

        return self._save(
            to_addresses=[rtm_email],
            subject=f"{todo_text} {subject_tag}",
            body=build_rtm_todo_body(todo_text, original_sender, original_subject),
            custom_headers=task_tracking_headers,
        )

    def save_forward(self, original_email_message: Any, assignee_email: str, todo_text: str,
                     bcc_email: str, task_tracking_headers: dict[str, str], note: str) -> bool:
        """Draft the forward to the assignee so a wrong assignee never receives mail unreviewed."""
        header_lines = [
            FORWARD_SEPARATOR,
            f"From: {original_email_message.from_address}",
            f"Date: {original_email_message.date}",
            f"Subject: {original_email_message.subject}",
        ]
        original_html = original_email_message.get_body(MIME_TEXT_HTML)
        if original_html:
            content_type = MIME_TEXT_HTML
            html_header = "<br>".join(escape(line) for line in header_lines)
            html_note = escape(note).replace("\n", "<br>")
            body = f"<p>{html_note}</p><p>{html_header}</p><div>{original_html}</div>"
        else:
            content_type = MIME_TEXT_PLAIN
            original_text = original_email_message.get_body(MIME_TEXT_PLAIN) or ""
            body = "\n".join([note, "", *header_lines, "", original_text])

        return self._save(
            to_addresses=[assignee_email],
            bcc_addresses=[bcc_email] if bcc_email else [],
            subject=todo_text,
            body=body,
            content_type=content_type,
            attachments=original_email_message.attachments,
            custom_headers=task_tracking_headers,
        )

    def _save(self, **draft_fields: Any) -> bool:
        """Append one draft to the main account's Drafts folder."""
        account = self._config.get_first_account()
        if not account:
            logger.error("No main account configuration found")
            return False

        # ponytail: one short connection per draft; share a client if volume ever matters
        client = EnhancedImapClient(account)
        if not client.connect():
            logger.error(f"Failed to connect to main account: {account.get('name')}")
            return False

        try:
            saved = bool(client.client.save_draft(
                from_email=account.get(CFG_EMAIL_ADDRESS),
                draft_folder=self._config.get_drafts_folder(account),
                **draft_fields,
            ))
            if saved:
                logger.info(f"Saved draft: {draft_fields['subject']}")
            else:
                logger.error(f"Failed to save draft: {draft_fields['subject']}")
            return saved
        finally:
            client.disconnect()
