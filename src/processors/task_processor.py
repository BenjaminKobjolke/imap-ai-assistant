import logging
import uuid
from datetime import datetime
from typing import Dict, Optional, List, Tuple
from src.config.settings import ConfigManager
from src.email.imap_client import EnhancedImapClient
from src.email.smtp_client import SmtpClient
from src.ai.openai_client import OpenAIClient

logger = logging.getLogger(__name__)


class TaskProcessor:
    """Handles task assignment and email processing workflow."""
    
    def __init__(self, config: ConfigManager, smtp_client: SmtpClient, openai_client: OpenAIClient):
        self.config = config
        self.smtp_client = smtp_client
        self.openai_client = openai_client
    
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
            logger.info(f"📨 extract_email_content returned - Types: subject={type(subject)}, first_line={type(first_line)}, body_excerpt={type(body_excerpt)}")
            logger.info(f"📨 extract_email_content returned - Values: subject='{subject}', first_line='{first_line}', body_excerpt='{body_excerpt}'")
            
            # Process with OpenAI
            logger.info("📨 About to call process_email_to_todo...")
            result = self.openai_client.process_email_to_todo(subject, first_line, body_excerpt)
            if not result:
                logger.error(f"Failed to generate todo for message {message_id}")
                return False
            
            todo_text, assignee = result
            logger.info(f"📨 process_email_to_todo completed, todo: {todo_text}, assignee: {assignee}")
            
            # Get processing rules based on assignee
            processing_rules = self.config.get_processing_rules(assignee)
            target_folder = processing_rules["target_folder"]
            subject_tag = processing_rules["additional_subject_tag"]
            assignee_email = processing_rules.get("email_address", "")
            bcc_email = processing_rules.get("bcc", "")
            
            # Prepare task tracking headers
            task_tracking_headers = {
                "X-IMAP-Assistant-Task-ID": task_id,
                "X-IMAP-Assistant-Original-Sender": email_message.from_address,
                "X-IMAP-Assistant-Created": task_created
            }
            
            # Send to Remember the Milk
            rtm_email = self.config.rtm_email
            if not rtm_email:
                logger.error("RTM email address not configured")
                return False
            
            success = self.smtp_client.send_rtm_todo(
                rtm_email=rtm_email,
                todo_text=todo_text,
                subject_tag=subject_tag,
                original_subject=subject,
                original_sender=email_message.from_address,
                task_tracking_headers=task_tracking_headers
            )
            
            if not success:
                logger.error(f"Failed to send RTM todo for message {message_id}")
                return False
            
            # Mark as read on processor account
            if not imap_client.mark_message_as_read(message_id):
                logger.warning(f"Failed to mark message {message_id} as read")
            
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
                               bcc_email: str = "", task_tracking_headers: Optional[Dict[str, str]] = None) -> bool:
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
                    if assignee != "self" and assignee_email and todo_text:
                        success = self._forward_to_assignee(
                            source_client, source_account_config, original_email_message,
                            assignee, assignee_email, todo_text, bcc_email, task_tracking_headers
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
    
    def _forward_to_assignee(self, source_client: EnhancedImapClient, source_account_config: Dict,
                            original_email_message, assignee: str, assignee_email: str, 
                            todo_text: str, bcc_email: str, task_tracking_headers: Dict[str, str]) -> bool:
        """Forward original email to assignee."""
        try:
            bcc_list = [bcc_email] if bcc_email else []
            logger.info(f"Forwarding original email to {assignee} at {assignee_email}" + 
                       (f" with BCC to {bcc_email}" if bcc_email else ""))
            
            # Try to add task tracking headers to forwarded email
            try:
                forward_success = source_client.client.forward_email(
                    email_message=original_email_message,
                    to_addresses=[assignee_email],
                    new_subject=todo_text,
                    smtp_server=source_account_config.get("server"),
                    smtp_port=587,
                    smtp_username=source_account_config.get("username"),
                    smtp_password=source_account_config.get("password"),
                    sender_email=source_account_config.get("email_address"),
                    bcc_addresses=bcc_list,
                    additional_message=f"This task has been assigned to you.\n\nTask ID: {task_tracking_headers.get('X-IMAP-Assistant-Task-ID', 'unknown')}\nForwarded by IMAP AI Assistant",
                    custom_headers=task_tracking_headers
                )
            except TypeError as e:
                if "custom_headers" in str(e):
                    logger.warning("forward_email method doesn't support custom_headers yet - forwarding without tracking headers")
                    forward_success = source_client.client.forward_email(
                        email_message=original_email_message,
                        to_addresses=[assignee_email],
                        new_subject=todo_text,
                        smtp_server=source_account_config.get("server"),
                        smtp_port=587,
                        smtp_username=source_account_config.get("username"),
                        smtp_password=source_account_config.get("password"),
                        sender_email=source_account_config.get("email_address"),
                        bcc_addresses=bcc_list,
                        additional_message=f"This task has been assigned to you.\n\nTask ID: {task_tracking_headers.get('X-IMAP-Assistant-Task-ID', 'unknown')}\nForwarded by IMAP AI Assistant"
                    )
                else:
                    raise
            
            if forward_success:
                logger.info(f"Successfully forwarded original email to {assignee}")
                return True
            else:
                logger.warning(f"Failed to forward original email to {assignee}")
                return False
                
        except Exception as e:
            logger.error(f"Error forwarding email to assignee: {e}")
            return False
    
    def _extract_sender_email(self, from_address: str) -> Optional[str]:
        """Extract email address from sender field."""
        try:
            from email.utils import parseaddr
            name, email_addr = parseaddr(from_address)
            return email_addr if email_addr else None
        except Exception as e:
            logger.debug(f"Error parsing sender email from '{from_address}': {e}")
            return None