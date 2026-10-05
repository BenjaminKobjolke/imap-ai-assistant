from __future__ import annotations

import logging
import uuid
from datetime import datetime

from src.ai.openai_client import OpenAIClient
from src.config.settings import ConfigManager
from src.constants import (
    CFG_ADDITIONAL_SUBJECT_TAG,
    CFG_EMAIL_ADDRESS,
    CFG_TARGET_FOLDER,
    HEADER_CREATED,
    HEADER_ORIGINAL_SENDER,
    HEADER_TASK_ID,
    MARKER_DRY_RUN,
)
from src.email.imap_client import EnhancedImapClient
from src.email.smtp_client import SmtpClient
from src.interaction.scheduler_prompts import scheduler_choose, scheduler_confirm, send_output
from src.processors.task_draft_writer import TaskDraftWriter
from src.services.todo_service import TodoService, forwarded_senders

logger = logging.getLogger(__name__)


class TaskProcessor:
    """Handles task assignment and email processing workflow."""

    def __init__(self, config: ConfigManager, smtp_client: SmtpClient, openai_client: OpenAIClient,
                 dry_run: bool = False, drafts_only: bool = False):
        self.config = config
        self.smtp_client = smtp_client
        self.openai_client = openai_client
        self.dry_run = dry_run
        self.drafts_only = drafts_only
        self._todo_processor = TodoService(config)
        self._draft_writer = TaskDraftWriter(config)

    def process_single_email(self, imap_client: EnhancedImapClient, message_id: str, email_message) -> bool:
        """Process a single email message."""
        try:
            # Generate unique task ID for tracking
            task_id = str(uuid.uuid4())
            task_created = datetime.now().isoformat()

            logger.info(f"Processing message {message_id} from {email_message.from_address} (Task ID: {task_id})")

            # Extract email content
            logger.info("📨 About to call extract_email_content...")
            subject, first_line, body_excerpt = imap_client.extract_email_content(email_message)
            logger.info(
                f"📨 extract_email_content returned - Types: subject={type(subject)}, "
                f"first_line={type(first_line)}, body_excerpt={type(body_excerpt)}"
            )
            logger.info(
                f"📨 extract_email_content returned - Values: subject='{subject}', "
                f"first_line='{first_line}', body_excerpt='{body_excerpt}'"
            )
            send_output(f"Processing email from {email_message.from_address}: {subject}")

            # Sender rules must also see who wrote a forwarded mail
            rule_sender = f"{email_message.from_address} {forwarded_senders(body_excerpt)}"

            # Process with OpenAI
            logger.info("📨 About to call process_email_to_todo...")
            result = TodoService.generate_todo(
                self.openai_client, subject, first_line, body_excerpt,
                self._todo_processor.resolve_rule_prompt(rule_sender, subject),
            )
            if not result:
                logger.error(f"Failed to generate todo for message {message_id}")
                return False

            logger.info(f"📨 process_email_to_todo completed, todo: {result.rtm_text}, assignee: {result.assignee}")

            # Let user review/edit todo fields individually
            result = TodoService.edit_todo(result)

            # Let user review/edit assignee; a rule assignee applies only when no name was given
            rule_assignee = self._todo_processor.resolve_rule_assignee(rule_sender, subject)
            suggested = rule_assignee if rule_assignee and result.assignee == "self" else result.assignee
            assignee_options = ["self", *self.config.get_other_people_names()]
            default_index = assignee_options.index(suggested) if suggested in assignee_options else 0
            assignee_index = scheduler_choose(
                f"Assignee for this task (suggested: {suggested}):",
                assignee_options,
                default=default_index,
            )
            assignee = assignee_options[assignee_index]
            todo_text = result.rtm_text
            send_output(f"Todo: {todo_text} (assignee: {assignee})")

            # Get processing rules based on assignee
            processing_rules = self.config.get_processing_rules(assignee)
            target_folder = processing_rules[CFG_TARGET_FOLDER]
            subject_tag = processing_rules[CFG_ADDITIONAL_SUBJECT_TAG]

            # Append extra tags from sender/keyword rules
            extra_tags = self._todo_processor.resolve_extra_tags(rule_sender, subject)
            if extra_tags:
                subject_tag = f"{subject_tag} {extra_tags}"

            # Let user edit tags
            subject_tag = TodoService.edit_tags(subject_tag)
            assignee_email = processing_rules.get(CFG_EMAIL_ADDRESS, "")
            bcc_email = processing_rules.get("bcc", "")

            # Prepare task tracking headers
            task_tracking_headers = {
                HEADER_TASK_ID: task_id,
                HEADER_ORIGINAL_SENDER: email_message.from_address,
                HEADER_CREATED: task_created,
            }

            if self.dry_run:
                final_subject = f"{todo_text} {subject_tag}"
                logger.info(f"{MARKER_DRY_RUN} Final subject: {final_subject}")
                logger.info(f"{MARKER_DRY_RUN} Would mark message {message_id} as read")
                done_folder = self.config.processor_done_folder
                if done_folder:
                    logger.info(f"{MARKER_DRY_RUN} Would move message to \"{done_folder}\" on processor account")
                sent_folder = self.config.processor_sent_folder
                if sent_folder:
                    logger.info(f"{MARKER_DRY_RUN} Would append sent message to \"{sent_folder}\" on processor account")
                logger.info(f"{MARKER_DRY_RUN} Would handle original email (move to {target_folder}, "
                            f"forward to {assignee_email or 'N/A'})")
                return True

            todo_prompt = "Save todo as draft?" if self.drafts_only else "Send todo to RTM?"
            if not scheduler_confirm(f"{todo_prompt} [{todo_text} {subject_tag}]", default=True):
                logger.info("User declined sending todo to RTM — skipping")
                return False

            sent_message_bytes: bytes | None = None
            if self.drafts_only:
                success = self._draft_writer.save_rtm_todo(
                    todo_text, subject_tag,
                    subject, email_message.from_address, task_tracking_headers,
                )
            else:
                success, sent_message_bytes = self._todo_processor.send_todo(
                    todo_text, subject_tag,
                    subject, email_message.from_address, task_tracking_headers,
                )

            if not success:
                logger.error(f"Failed to send RTM todo for message {message_id}")
                return False

            send_output("Todo saved as draft" if self.drafts_only else "Todo sent to RTM")

            # Mark as read on processor account
            if not imap_client.mark_message_as_read(message_id):
                logger.warning(f"Failed to mark message {message_id} as read")

            # Move to done folder on processor account if configured
            done_folder = self.config.processor_done_folder
            if done_folder:
                if not imap_client.client.move_to_folder(message_id, done_folder):
                    logger.warning(f"Failed to move message {message_id} to \"{done_folder}\" on processor account")
                else:
                    logger.info(f"Moved message {message_id} to \"{done_folder}\" on processor account")

            # Append sent message to IMAP Sent folder if configured
            sent_folder = self.config.processor_sent_folder
            if sent_folder and sent_message_bytes:
                if not imap_client.append_to_folder(sent_folder, sent_message_bytes):
                    logger.warning(f"Failed to append sent message to \"{sent_folder}\" on processor account")
                else:
                    logger.info(f"Appended sent message to \"{sent_folder}\" on processor account")

            # Handle original email management and forwarding
            success = self._handle_original_email(
                email_message, subject, target_folder, assignee,
                assignee_email, todo_text, bcc_email, task_tracking_headers
            )
            if not success:
                logger.warning(f"Failed to handle original email for message {message_id}")

            logger.info(f"Successfully processed message {message_id}: {todo_text} (assignee: {assignee})")
            return True

        except Exception as e:
            logger.error(f"Error processing single email {message_id}: {e}")
            return False

    def _handle_original_email(self, email_message, subject: str, target_folder: str,
                               assignee: str = "self", assignee_email: str = "", todo_text: str = "",
                               bcc_email: str = "", task_tracking_headers: dict[str, str] | None = None) -> bool:
        """Handle finding and moving original email in sender's account, and forward if needed."""
        try:
            # Extract sender email address
            sender_email = self._extract_sender_email(email_message.from_address)
            if not sender_email:
                logger.warning("Could not extract sender email address")
                return False

            logger.info(f"Looking for source account for sender: {sender_email}")

            # Find source account configuration
            source_account_config = self.config.get_source_account_by_email(sender_email)
            if not source_account_config:
                logger.warning(f"No source account found for sender: {sender_email}")
                return False

            logger.info(f"Found source account: {source_account_config['name']}")

            # Connect to source account
            source_client = EnhancedImapClient(source_account_config)
            if not source_client.connect():
                logger.error(f"Failed to connect to source account: {source_account_config['name']}")
                return False

            try:
                # Find the original email using library methods directly
                original_subject = source_client._strip_subject_prefixes(subject)
                logger.info(f"Looking for original email with subject: '{original_subject}'")

                # Get all messages and search for matching subject
                all_messages = source_client.client.get_all_messages()
                matching_emails = []

                for message_id, email_message in all_messages:
                    if hasattr(email_message, 'subject') and email_message.subject:
                        message_subject = source_client._strip_subject_prefixes(email_message.subject)
                        if (original_subject.lower() in message_subject.lower() or
                            message_subject.lower() in original_subject.lower()):
                            matching_emails.append((message_id, email_message))
                            if len(matching_emails) >= 5:  # Limit to 5 results
                                break

                if matching_emails:
                    original_message_id, original_email_message = matching_emails[0]
                    logger.info(f"Found original email: {original_email_message.subject}")

                    # Forward email to assignee if not self
                    forward_prompt = (
                        f"Save forward to {assignee} ({assignee_email}) as draft?" if self.drafts_only
                        else f"Forward email to {assignee} ({assignee_email})?"
                    )
                    if assignee != "self" and assignee_email and todo_text and scheduler_confirm(
                        forward_prompt, default=True
                    ):
                        headers = task_tracking_headers or {}
                        if self.drafts_only:
                            success = self._draft_writer.save_forward(
                                original_email_message, assignee_email, todo_text, bcc_email,
                                headers, self._forward_note(headers),
                            )
                            if success:
                                send_output(f"Forward to {assignee} saved as draft")
                        else:
                            success = self._forward_to_assignee(
                                source_client, source_account_config, original_email_message,
                                assignee, assignee_email, todo_text, bcc_email, headers
                            )
                        if not success:
                            logger.warning(f"Failed to forward original email to {assignee}")

                    # Move the original email to the target folder with task tracking headers
                    move_success = source_client.client.move_to_folder(
                        original_message_id, target_folder, custom_headers=task_tracking_headers
                    )

                    if move_success:
                        logger.info(f"Successfully moved original email to {target_folder}")
                        return True
                    else:
                        logger.warning(f"Failed to move original email to {target_folder}")
                        return False
                else:
                    logger.warning(f"Could not find original email with subject: '{original_subject}'")
                    return False

            finally:
                source_client.disconnect()

        except Exception as e:
            logger.error(f"Error handling original email: {e}")
            return False

    def _forward_to_assignee(self, source_client: EnhancedImapClient, source_account_config: dict,
                            original_email_message, assignee: str, assignee_email: str,
                            todo_text: str, bcc_email: str, task_tracking_headers: dict[str, str]) -> bool:
        """Forward original email to assignee."""
        try:
            bcc_list = [bcc_email] if bcc_email else []
            logger.info(f"Forwarding original email to {assignee} at {assignee_email}" +
                       (f" with BCC to {bcc_email}" if bcc_email else ""))

            forward_args = {
                "email_message": original_email_message,
                "to_addresses": [assignee_email],
                "new_subject": todo_text,
                "smtp_server": source_account_config.get("server"),
                "smtp_port": 587,
                "smtp_username": source_account_config.get("username"),
                "smtp_password": source_account_config.get("password"),
                "sender_email": source_account_config.get("email_address"),
                "bcc_addresses": bcc_list,
                "additional_message": self._forward_note(task_tracking_headers),
            }

            # Try to add task tracking headers to forwarded email
            try:
                forward_success = source_client.client.forward_email(
                    **forward_args, custom_headers=task_tracking_headers,
                )
            except TypeError as e:
                if "custom_headers" not in str(e):
                    raise
                logger.warning(
                    "forward_email doesn't support custom_headers yet - forwarding without tracking"
                )
                forward_success = source_client.client.forward_email(**forward_args)

            if forward_success:
                send_output(f"Forwarded to {assignee}")
                logger.info(f"Successfully forwarded original email to {assignee}")
                return True
            else:
                logger.warning(f"Failed to forward original email to {assignee}")
                return False

        except Exception as e:
            logger.error(f"Error forwarding email to assignee: {e}")
            return False

    @staticmethod
    def _forward_note(task_tracking_headers: dict[str, str]) -> str:
        """Text put above the forwarded email, identical whether it is sent or drafted."""
        return (
            "This task has been assigned to you.\n\nTask ID: "
            f"{task_tracking_headers.get(HEADER_TASK_ID, 'unknown')}"
            "\nForwarded by IMAP AI Assistant"
        )

    def _extract_sender_email(self, from_address: str) -> str | None:
        """Extract email address from sender field."""
        try:
            from email.utils import parseaddr
            _, email_addr = parseaddr(from_address)
            return email_addr if email_addr else None
        except Exception as e:
            logger.debug(f"Error parsing sender email from '{from_address}': {e}")
            return None
