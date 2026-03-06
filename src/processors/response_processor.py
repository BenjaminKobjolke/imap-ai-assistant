from __future__ import annotations

import logging
import re

from src.ai.openai_client import OpenAIClient
from src.config.settings import ConfigManager
from src.constants import (
    CFG_EMAIL_ADDRESS,
    CFG_TARGET_FOLDER,
    HEADER_TASK_ID,
    KEY_CONFIDENCE,
    KEY_EMAIL_MESSAGE,
    KEY_MESSAGE_ID,
    KEY_REASON,
    KEY_STATUS,
    KEY_TASK_BODY,
    KEY_TASK_ID,
    KEY_TASK_SUBJECT,
    MARKER_DRY_RUN,
    STATUS_COMPLETED,
    STATUS_UNCLEAR,
)
from src.email.imap_client import EnhancedImapClient
from src.interaction.scheduler_prompts import scheduler_confirm, send_output
from src.processors.client_response_generator import ClientResponseGenerator
from src.processors.relationship_analyzer import RelationshipAnalyzer

logger = logging.getLogger(__name__)


class ResponseProcessor:
    """Handles processing of assignee responses and task completion detection."""

    def __init__(self, config: ConfigManager, openai_client: OpenAIClient, dry_run: bool = False):
        self.config = config
        self.openai_client = openai_client
        self.dry_run = dry_run
        self.client_response_generator = ClientResponseGenerator(config, openai_client)
        self.relationship_analyzer = RelationshipAnalyzer(config)

    def process_assignee_responses(self) -> None:
        """Process responses from assignees in the main account."""
        # Get the first account (main account, not SMTP processor account)
        main_account_config = self.config.get_first_account()
        if not main_account_config:
            logger.error("No main account configuration found")
            return

        # Create IMAP client for main account
        main_imap_client = EnhancedImapClient(main_account_config)

        if not main_imap_client.connect():
            logger.error("Failed to connect to main account")
            return

        try:
            # Get unread messages from main account
            all_messages = main_imap_client.client.get_unread_messages()
            logger.info(f"Found {len(all_messages)} unread messages in main account")

            for message_id, email_message in all_messages:
                try:
                    self._process_single_assignee_response(main_imap_client, message_id, email_message)
                except Exception as e:
                    logger.error(f"Error processing assignee response {message_id}: {e}")

        finally:
            main_imap_client.disconnect()

    def _process_single_assignee_response(self, main_imap_client: EnhancedImapClient,
                                         message_id: str, email_message) -> None:
        """Process a single assignee response email."""
        sender_email = self._extract_sender_email(email_message.from_address)
        if not sender_email:
            return

        # Check if sender is one of our assignees
        other_people = self.config.get_other_people_names()
        assignee_configs = {name: self.config.get_processing_rules(name) for name in other_people}

        assignee_name = None
        for name, config in assignee_configs.items():
            if config.get(CFG_EMAIL_ADDRESS, "").lower() == sender_email.lower():
                assignee_name = name
                break

        if not assignee_name:
            logger.debug(f"Email from {sender_email} is not from a known assignee")
            return

        send_output(f"Processing response from {assignee_name}")
        logger.info(f"Processing response from assignee: {assignee_name}")

        # Extract email content
        _subject, _first_line, body_excerpt = main_imap_client.extract_email_content(email_message)

        # Find the original task by extracting task ID from response headers
        original_task = self._find_original_task(assignee_name, email_message)
        if not original_task:
            logger.warning(f"Could not find original task for response from {assignee_name}")
            # Still mark email as read even if we can't find the original task
            if self.dry_run:
                logger.info(f"{MARKER_DRY_RUN} Would mark unmatched response email {message_id} as read")
            else:
                try:
                    main_imap_client.mark_message_as_read(message_id)
                    logger.debug(f"Marked unmatched assignee response email {message_id} as read")
                except Exception as e:
                    logger.warning(f"Failed to mark unmatched response email {message_id} as read: {e}")
            return

        # Use OpenAI to determine if task is completed
        task_status = self._check_task_completion(original_task, body_excerpt)

        # Let user confirm the AI assessment when running interactively
        status = task_status.get(KEY_STATUS, STATUS_UNCLEAR)
        confidence = task_status.get(KEY_CONFIDENCE, 0)
        reason = task_status.get(KEY_REASON, "")
        if not scheduler_confirm(
            f"AI assessment — status: {status}, confidence: {confidence}, reason: {reason}. Accept?",
            default=True,
        ):
            logger.info("User rejected AI assessment — overriding to 'unclear'")
            task_status = {KEY_STATUS: STATUS_UNCLEAR, KEY_CONFIDENCE: 0, KEY_REASON: "User override"}

        send_output(f"Task status: {task_status.get(KEY_STATUS, STATUS_UNCLEAR)}")

        if task_status.get(KEY_STATUS) == STATUS_COMPLETED:
            logger.info(f"Task completed by {assignee_name}: {original_task}")

            if self.dry_run:
                logger.info(f"{MARKER_DRY_RUN} Would generate client response for completed task")
            elif scheduler_confirm("Generate client response for completed task?", default=True):
                # Generate client response
                self._generate_client_response(original_task, body_excerpt, main_imap_client)
            else:
                logger.info("User declined client response generation — skipping")

            logger.info("Task completed - marking response email as read")
        else:
            status = task_status.get(KEY_STATUS)
            reason = task_status.get(KEY_REASON)
            logger.info(f"Task not completed by {assignee_name}. Status: {status} - {reason}")

        # Always mark the response email as read after processing (regardless of completion status)
        if self.dry_run:
            logger.info(f"{MARKER_DRY_RUN} Would mark response email {message_id} as read")
        else:
            try:
                main_imap_client.mark_message_as_read(message_id)
                logger.debug(f"Marked assignee response email {message_id} as read")
            except Exception as e:
                logger.warning(f"Failed to mark response email {message_id} as read: {e}")

    def _find_original_task(self, assignee_name: str, response_email_message: object) -> dict | None:
        """Find the original task by extracting task ID from response email headers."""
        try:
            logger.info(f"Searching for original task for assignee: {assignee_name}")

            # Extract task ID from response email headers
            task_id = None
            if hasattr(response_email_message, 'raw_message'):
                task_id = response_email_message.raw_message.get(HEADER_TASK_ID)
                logger.debug(f"Extracted task ID from raw_message: {task_id}")

            if not task_id:
                logger.warning(f"Could not find {HEADER_TASK_ID} header in response email")
                logger.info("Trying to extract task ID from email body as fallback...")

                # Fallback: Extract task ID from email body
                task_id = self._extract_task_id_from_body(response_email_message)

                if not task_id:
                    logger.warning("This response may not be related to a task we forwarded")
                    return None

            logger.info(f"Found task ID in response: {task_id}")

            # Find the original task using the task ID
            return self._find_task_by_id(assignee_name, task_id)

        except Exception as e:
            logger.error(f"Error finding original task: {e}")
            return None

    def _extract_task_id_from_body(self, response_email_message: object) -> str | None:
        """Extract task ID from email body as fallback."""
        try:
            # Try multiple methods to get email content
            body_content = None

            # Method 1: Use extract_email_content from imap client
            main_account_config = self.config.get_first_account()
            if main_account_config:
                temp_client = EnhancedImapClient(main_account_config)
                try:
                    _subject, _first_line, body_excerpt = temp_client.extract_email_content(response_email_message)
                    body_content = body_excerpt
                    preview = body_content[:200] if body_content else 'None'
                    logger.debug(f"Extracted body using extract_email_content: {preview}...")
                except Exception as e:
                    logger.debug(f"extract_email_content failed: {e}")

            # Method 2: Direct attribute access
            if not body_content:
                if hasattr(response_email_message, 'get_content'):
                    body_content = response_email_message.get_content()
                    logger.debug("Used get_content() method")
                elif hasattr(response_email_message, 'body'):
                    body_content = response_email_message.body
                    logger.debug("Used body attribute")
                elif hasattr(response_email_message, 'text'):
                    body_content = response_email_message.text
                    logger.debug("Used text attribute")

            if body_content:
                # Strip HTML tags if present
                html_stripped = re.sub(r'<[^>]+>', '', body_content)
                # Decode HTML entities
                import html
                clean_content = html.unescape(html_stripped)

                logger.debug(f"Original body length: {len(body_content)}, After HTML stripping: {len(clean_content)}")
                logger.debug(f"Clean email body content (first 500 chars): {clean_content[:500]}...")

                # Look for "Task ID: <uuid>" pattern in the clean body
                task_id_pattern = r'Task ID:\s*([a-f0-9-]{36})'
                logger.debug(f"Searching for pattern: {task_id_pattern}")

                match = re.search(task_id_pattern, clean_content, re.IGNORECASE)
                if match:
                    task_id = match.group(1)
                    logger.info(f"✅ Found task ID in email body: {task_id}")
                    return task_id
                else:
                    logger.warning("❌ Could not find task ID pattern in email body")
                    logger.debug("Expected pattern format: 'Task ID: 12345678-1234-1234-1234-123456789abc'")
            else:
                logger.warning("No body content found in email message using any method")

            return None

        except Exception as e:
            logger.error(f"Error extracting task ID from body: {e}")
            return None

    def _find_task_by_id(self, assignee_name: str, task_id: str) -> dict | None:
        """Find task in target folder by task ID."""
        try:
            # Get processing rules for assignee to find target folder
            processing_rules = self.config.get_processing_rules(assignee_name)
            target_folder = processing_rules.get(CFG_TARGET_FOLDER)

            logger.info(f"Target folder for {assignee_name}: {target_folder}")

            if not target_folder:
                logger.error(f"No target folder configured for {assignee_name}")
                return None

            # Connect to main account
            main_account_config = self.config.get_first_account()
            if not main_account_config:
                return None

            main_client = EnhancedImapClient(main_account_config)
            if not main_client.connect():
                return None

            try:
                # Get all messages from target folder (the library should handle folder selection internally)
                logger.info(f"Getting messages from target folder: {target_folder}")
                all_messages = main_client.client.get_all_messages(folder=target_folder)
                logger.info(f"Found {len(all_messages)} messages in target folder {target_folder}")
                logger.info(f"Searching for email with task ID: {task_id}")

                # Search for email with matching task ID
                found_task_ids = []
                for msg_id, email_msg in all_messages:
                    if hasattr(email_msg, 'raw_message'):
                        msg_task_id = email_msg.raw_message.get(HEADER_TASK_ID)

                        if msg_task_id:
                            found_task_ids.append(msg_task_id)
                            logger.debug(f"Found task ID in folder: {msg_task_id}")

                        if msg_task_id == task_id:
                            # Extract email content for the original client request
                            msg_subject_full, _, msg_body = main_client.extract_email_content(email_msg)

                            logger.info(f"✅ Found matching original task by task ID: {msg_subject_full}")

                            return {
                                KEY_TASK_SUBJECT: msg_subject_full,
                                KEY_TASK_BODY: msg_body,
                                KEY_MESSAGE_ID: msg_id,
                                KEY_EMAIL_MESSAGE: email_msg,
                                KEY_TASK_ID: task_id,
                            }
                    else:
                        logger.debug(f"Email message {msg_id} has no raw_message attribute")

                logger.warning(f"❌ No email found in {target_folder} with task ID: {task_id}")
                logger.info(f"Available task IDs in folder: {found_task_ids}")
                logger.info(f"Looking for: {task_id}")
                logger.info(
                    "Response is not related to any forwarded task, or there's a task ID mismatch"
                )
                return None

            finally:
                main_client.disconnect()

        except Exception as e:
            logger.error(f"Error finding task by ID: {e}")
            return None

    def _check_task_completion(self, original_task: dict, assignee_response: str) -> dict:
        """Use OpenAI to check if task is completed."""
        if not self.openai_client:
            logger.error("OpenAI client not initialized")
            return {KEY_STATUS: STATUS_UNCLEAR, KEY_CONFIDENCE: 1, KEY_REASON: "OpenAI client not available"}

        # Use the task subject as the original task description
        task_description = original_task.get(KEY_TASK_SUBJECT, "")

        return self.openai_client.check_task_completion(task_description, assignee_response)

    def _generate_client_response(self, original_task: dict, assignee_response: str,
                                 main_imap_client: EnhancedImapClient) -> None:
        """Generate and send response to original client."""
        try:
            # Get the original sender (client who made the request)
            email_message = original_task.get(KEY_EMAIL_MESSAGE)
            if not email_message:
                logger.error("No original email message found")
                return

            original_sender = self._extract_sender_email(email_message.from_address)
            if not original_sender:
                logger.error("Could not extract original sender email")
                return

            # Get relationship context for this client
            last_sent_context = self.relationship_analyzer.get_relationship_context(original_sender, main_imap_client)

            # Generate and create draft response
            success = self.client_response_generator.generate_and_create_draft(
                original_task=original_task,
                assignee_response=assignee_response,
                original_sender=original_sender,
                last_sent_context=last_sent_context,
                main_imap_client=main_imap_client
            )

            if not success:
                logger.error(f"Failed to generate client response for {original_sender}")

        except Exception as e:
            logger.error(f"Error generating client response: {e}")

    def _extract_sender_email(self, from_address: str) -> str | None:
        """Extract email address from sender field."""
        try:
            from email.utils import parseaddr
            _, email_addr = parseaddr(from_address)
            return email_addr if email_addr else None
        except Exception as e:
            logger.debug(f"Error parsing sender email from '{from_address}': {e}")
            return None
