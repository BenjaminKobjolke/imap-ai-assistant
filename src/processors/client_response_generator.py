import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from src.config.settings import ConfigManager
from src.email.imap_client import EnhancedImapClient
from src.ai.openai_client import OpenAIClient

logger = logging.getLogger(__name__)


class ClientResponseGenerator:
    """Handles generation and creation of client response drafts."""

    def __init__(self, config: ConfigManager, openai_client: OpenAIClient):
        self.config = config
        self.openai_client = openai_client

    def generate_and_create_draft(self, original_task: Dict, assignee_response: str,
                                 original_sender: str, last_sent_context: Optional[str],
                                 main_imap_client: EnhancedImapClient) -> bool:
        """Generate client response and create draft email."""
        try:
            if not self.openai_client:
                logger.error("OpenAI client not initialized")
                return False

            # Extract original email information
            email_message = original_task.get("email_message")
            if not email_message:
                logger.error("No original email message found")
                return False

            # Generate response using OpenAI with relationship context
            response_data = self.openai_client.generate_client_response(
                original_subject=original_task.get("task_subject", ""),
                original_content=original_task.get("task_body", ""),
                assigned_task=original_task.get("task_subject", ""),
                assignee_response=assignee_response,
                last_sent_context=last_sent_context
            )

            # Create draft email
            return self._create_draft_email(
                response_data=response_data,
                original_task=original_task,
                original_sender=original_sender,
                main_imap_client=main_imap_client
            )

        except Exception as e:
            logger.error(f"Error generating client response: {e}")
            return False

    def _create_draft_email(self, response_data: Dict, original_task: Dict,
                           original_sender: str, main_imap_client: EnhancedImapClient) -> bool:
        """Create draft email with generated response."""
        try:
            # Get response content
            response_subject = response_data.get("subject", f"Re: {original_task.get('task_subject', 'Your request')}")
            response_body = response_data.get("response", "Your request has been completed.")

            # Create draft response instead of sending immediately
            main_account_config = self.config.get_first_account()
            if not main_account_config:
                logger.error("No main account configuration found")
                return False

            # Create clean draft email as a proper reply
            draft_subject = f"[DRAFT-RESPONSE] {response_subject}"

            # Create proper reply format with original email quoted
            original_email_content = original_task.get('task_body', '')
            original_subject = original_task.get('task_subject', '')

            # Load footer HTML
            footer_html = self._load_footer_html()

            # Create HTML formatted draft body
            html_response = response_body.replace('\n', '<br>')
            html_original_content = original_email_content.replace('\n', '<br>')

            draft_body = f"""
<div style="font-family: Arial, sans-serif; font-size: 14px; line-height: 1.6;">
    <div style="margin-bottom: 20px;">
        {html_response}
    </div>

    {footer_html}

    <hr style="margin: 20px 0; border: none; border-top: 1px solid #ccc;">

    <div style="color: #666; font-size: 12px; background-color: #f9f9f9; padding: 10px; border-left: 3px solid #ddd;">
        <strong>-----Original Message-----</strong><br>
        <strong>From:</strong> {original_sender}<br>
        <strong>Subject:</strong> {original_subject}<br><br>
        <div style="margin-top: 10px;">
            {html_original_content}
        </div>
    </div>
</div>
"""

            # Create draft using the library's save_draft method
            drafts_folder = self.config.get_drafts_folder(main_account_config)

            # Add task tracking headers to the draft
            draft_headers = {
                "X-IMAP-Assistant-Task-ID": original_task.get('task_id', 'unknown'),
                "X-IMAP-Assistant-Original-Sender": original_sender,
                "X-IMAP-Assistant-Draft-Created": datetime.now().isoformat()
            }

            success = main_imap_client.client.save_draft(
                to_addresses=[original_sender],
                subject=draft_subject,
                body=draft_body,
                from_email=main_account_config.get("email_address"),
                custom_headers=draft_headers,
                draft_folder=drafts_folder,
                content_type="text/html"
            )

            if success:
                logger.info(f"Successfully created draft response for client: {original_sender}")
                logger.info(f"Draft subject: {draft_subject}")
                logger.info("Task completed, draft response created for manual review")
                return True
            else:
                logger.error(f"Failed to create draft response for client: {original_sender}")
                return False

        except Exception as e:
            logger.error(f"Error creating draft email: {e}")
            return False

    def _load_footer_html(self) -> str:
        """Load footer HTML from file."""
        footer_html = ""
        try:
            footer_path = Path("data/footer.html")
            if footer_path.exists():
                with open(footer_path, 'r', encoding='utf-8') as f:
                    footer_html = f.read()
                logger.debug("Footer HTML loaded successfully")
            else:
                logger.warning("Footer HTML file not found at data/footer.html")
        except Exception as e:
            logger.warning(f"Could not load footer HTML: {e}")
        return footer_html
