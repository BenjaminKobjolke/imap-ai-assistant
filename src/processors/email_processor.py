import logging
import uuid
from datetime import datetime
from typing import List, Tuple, Optional, Dict
from src.config.settings import ConfigManager
from src.email.imap_client import EnhancedImapClient
from src.email.smtp_client import SmtpClient
from src.ai.openai_client import OpenAIClient

logger = logging.getLogger(__name__)


class EmailProcessor:
    """Main email processor that orchestrates the entire workflow."""
    
    def __init__(self, config_path: str = "settings.json"):
        self.config = ConfigManager(config_path)
        self.imap_client = None
        self.smtp_client = None
        self.openai_client = None
        self._initialize_clients()
    
    def _initialize_clients(self) -> None:
        """Initialize all client instances."""
        try:
            # Validate configuration
            if not self.config.is_valid():
                logger.error("Invalid configuration. Please check settings.json")
                return
            
            # Initialize IMAP client for processor account (from SMTP config)
            processor_account = self.config.get_processor_account()
            if processor_account:
                self.imap_client = EnhancedImapClient(processor_account)
            else:
                logger.error("No processor account configuration found")
                return
            
            # Initialize SMTP client
            smtp_config = self.config.smtp_config
            if smtp_config:
                self.smtp_client = SmtpClient(smtp_config)
            else:
                logger.error("No SMTP configuration found")
                return
            
            # Initialize OpenAI client
            api_key = self.config.openai_api_key
            model = self.config.openai_model
            max_tokens = self.config.openai_max_tokens
            temperature = self.config.openai_temperature
            other_people = self.config.get_other_people_names()
            if api_key:
                self.openai_client = OpenAIClient(api_key, model, max_tokens, temperature, other_people)
            else:
                logger.error("No OpenAI API key found")
                return
            
            logger.info("All clients initialized successfully")
            
        except Exception as e:
            logger.error(f"Error initializing clients: {e}")
    
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
                    self._process_assignee_response(main_imap_client, message_id, email_message)
                except Exception as e:
                    logger.error(f"Error processing assignee response {message_id}: {e}")
                    
        finally:
            main_imap_client.disconnect()

    def process_unread_emails(self) -> None:
        """Main method to process all unread emails."""
        if not all([self.imap_client, self.smtp_client, self.openai_client]):
            logger.error("Clients not properly initialized")
            return
        
        # Type guards - we know these are not None after the check above
        assert self.imap_client is not None
        assert self.smtp_client is not None
        assert self.openai_client is not None
        
        try:
            logger.info("Starting email processing workflow")
            
            # Connect to IMAP server
            if not self.imap_client.connect():
                logger.error("Failed to connect to IMAP server")
                return
            
            try:
                # Get filtered unread messages
                allowed_senders = self.config.allowed_senders
                messages = self.imap_client.get_filtered_unread_messages(allowed_senders)
                
                if not messages:
                    logger.info("No unread messages from allowed senders found")
                    return
                
                logger.info(f"Processing {len(messages)} unread messages")
                
                # Process each message
                processed_count = 0
                failed_count = 0
                
                for message_id, email_message in messages:
                    try:
                        success = self._process_single_email(message_id, email_message)
                        if success:
                            processed_count += 1
                        else:
                            failed_count += 1
                    except Exception as e:
                        logger.error(f"Error processing message {message_id}: {e}")
                        failed_count += 1
                
                logger.info(f"Email processing completed: {processed_count} successful, {failed_count} failed")
                
            finally:
                # Always disconnect
                self.imap_client.disconnect()
                
        except Exception as e:
            logger.error(f"Error in email processing workflow: {e}")
    
    def _process_single_email(self, message_id: str, email_message) -> bool:
        """Process a single email message."""
        # Type guards
        assert self.imap_client is not None
        assert self.smtp_client is not None
        assert self.openai_client is not None
        
        try:
            # Generate unique task ID for tracking
            task_id = str(uuid.uuid4())
            task_created = datetime.now().isoformat()
            
            logger.info(f"Processing message {message_id} from {email_message.from_address} (Task ID: {task_id})")
            
            # Extract email content (now includes body excerpt)
            logger.info("📨 About to call extract_email_content...")
            subject, first_line, body_excerpt = self.imap_client.extract_email_content(email_message)
            logger.info(f"📨 extract_email_content returned - Types: subject={type(subject)}, first_line={type(first_line)}, body_excerpt={type(body_excerpt)}")
            logger.info(f"📨 extract_email_content returned - Values: subject='{subject}', first_line='{first_line}', body_excerpt='{body_excerpt}'")
            
            # Process with OpenAI (now with body excerpt for better sender context)
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
            
            # Mark as read on processor account (SUMMERA AI)
            if not self.imap_client.mark_message_as_read(message_id):
                logger.warning(f"Failed to mark message {message_id} as read")
            
            # NEW: Cross-account original email management (and forwarding if needed)
            success = self._handle_original_email(email_message, subject, target_folder, assignee, assignee_email, todo_text, bcc_email, task_tracking_headers)
            if not success:
                logger.warning(f"Failed to handle original email for message {message_id}")
            
            logger.info(f"Successfully processed message {message_id}: {todo_text} (assignee: {assignee})")
            return True
            
        except Exception as e:
            logger.error(f"Error processing single email {message_id}: {e}")
            return False
    
    def _handle_original_email(self, email_message, subject: str, target_folder: str, 
                               assignee: str = "self", assignee_email: str = "", todo_text: str = "", bcc_email: str = "", 
                               task_tracking_headers: Optional[Dict[str, str]] = None) -> bool:
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
                # First, find the original email using library methods directly  
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
                        else:
                            logger.warning(f"Failed to forward original email to {assignee}")
                    
                    # Now move the original email to the target folder with task tracking headers
                    move_success = source_client.client.move_to_folder(original_message_id, target_folder, custom_headers=task_tracking_headers)
                    
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
                # Always disconnect from source account
                source_client.disconnect()
                
        except Exception as e:
            logger.error(f"Error handling original email: {e}")
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
    
    def _get_last_sent_email_context(self, client_email: str, main_imap_client: EnhancedImapClient) -> Optional[str]:
        """Find the last email sent to this client for relationship context."""
        try:
            main_account_config = self.config.get_first_account()
            if not main_account_config:
                return None
                
            sent_folder = self.config.get_sent_folder(main_account_config)
            logger.debug(f"Searching for last sent email to {client_email} in folder: {sent_folder}")
            
            # Get recent messages from sent folder (library default limit: 100)
            # Using get_messages instead of get_all_messages for better performance
            recent_sent_messages = main_imap_client.client.get_messages(folder=sent_folder)
            logger.debug(f"Retrieved {len(recent_sent_messages)} recent messages from sent folder for analysis")
            
            # Search for the most recent email to this client
            # Messages are typically returned in reverse chronological order (newest first)
            for msg_id, email_msg in recent_sent_messages:
                if hasattr(email_msg, 'to') or hasattr(email_msg, 'to_address'):
                    # Check different possible attributes for recipient
                    to_address = getattr(email_msg, 'to', None) or getattr(email_msg, 'to_address', None)
                    
                    if to_address and client_email.lower() in to_address.lower():
                        # Found a sent email to this client
                        try:
                            # Extract first 500 characters of the email content
                            subject, first_line, body_excerpt = main_imap_client.extract_email_content(email_msg)
                            
                            # Strip any remaining HTML tags from the content
                            import re
                            import html
                            
                            if body_excerpt:
                                # Remove HTML tags
                                clean_body = re.sub(r'<[^>]+>', '', body_excerpt)
                                # Decode HTML entities
                                clean_body = html.unescape(clean_body)
                                # Clean up extra whitespace
                                clean_body = ' '.join(clean_body.split())
                            else:
                                clean_body = ""
                            
                            # Combine subject and body for context
                            context = f"Subject: {subject}\n{clean_body}" if clean_body else f"Subject: {subject}"
                            context_snippet = context[:500]
                            
                            logger.info(f"Found last sent email to {client_email}: {subject[:50]}...")
                            logger.debug(f"Last sent context (first 100 chars): {context_snippet[:100]}...")
                            return context_snippet
                            
                        except Exception as e:
                            logger.debug(f"Error extracting content from sent email: {e}")
                            continue
            
            logger.debug(f"No previous sent emails found to {client_email}")
            return None
            
        except Exception as e:
            logger.warning(f"Error searching for last sent email to {client_email}: {e}")
            return None
    
    def _is_client_an_assignee(self, client_email: str) -> bool:
        """Check if the client email matches any assignee email address."""
        try:
            # Get all assignee names and their email addresses
            other_people = self.config.get_other_people_names()
            
            for assignee_name in other_people:
                assignee_rules = self.config.get_processing_rules(assignee_name)
                assignee_email = assignee_rules.get("email_address", "")
                
                if assignee_email and client_email.lower() == assignee_email.lower():
                    logger.debug(f"Client {client_email} matches assignee {assignee_name}")
                    return True
            
            return False
            
        except Exception as e:
            logger.debug(f"Error checking if client is assignee: {e}")
            return False
    
    def _process_assignee_response(self, main_imap_client: EnhancedImapClient, message_id: str, email_message) -> None:
        """Process a single assignee response email."""
        sender_email = self._extract_sender_email(email_message.from_address)
        if not sender_email:
            return
            
        # Check if sender is one of our assignees
        other_people = self.config.get_other_people_names()
        assignee_configs = {name: self.config.get_processing_rules(name) for name in other_people}
        
        assignee_name = None
        for name, config in assignee_configs.items():
            if config.get("email_address", "").lower() == sender_email.lower():
                assignee_name = name
                break
                
        if not assignee_name:
            logger.debug(f"Email from {sender_email} is not from a known assignee")
            return
            
        logger.info(f"Processing response from assignee: {assignee_name}")
        
        # Extract email content
        subject, first_line, body_excerpt = main_imap_client.extract_email_content(email_message)
        
        # Find the original task by extracting task ID from response headers
        original_task = self._find_original_task(assignee_name, email_message)
        if not original_task:
            logger.warning(f"Could not find original task for response from {assignee_name}")
            # Still mark email as read even if we can't find the original task
            try:
                main_imap_client.mark_message_as_read(message_id)
                logger.debug(f"Marked unmatched assignee response email {message_id} as read")
            except Exception as e:
                logger.warning(f"Failed to mark unmatched response email {message_id} as read: {e}")
            return
            
        # Use OpenAI to determine if task is completed
        task_status = self._check_task_completion(original_task, body_excerpt)
        
        if task_status.get("status") == "completed":
            logger.info(f"Task completed by {assignee_name}: {original_task}")
            
            # Generate client response
            self._generate_client_response(original_task, body_excerpt, main_imap_client)
            
            logger.info("Task completed - marking response email as read")
        else:
            logger.info(f"Task not completed by {assignee_name}. Status: {task_status.get('status')} - {task_status.get('reason')}")
        
        # Always mark the response email as read after processing (regardless of completion status)
        try:
            main_imap_client.mark_message_as_read(message_id)
            logger.debug(f"Marked assignee response email {message_id} as read")
        except Exception as e:
            logger.warning(f"Failed to mark response email {message_id} as read: {e}")
    
    def _find_original_task(self, assignee_name: str, response_email_message) -> Optional[Dict]:
        """Find the original task by extracting task ID from response email headers."""
        try:
            logger.info(f"Searching for original task for assignee: {assignee_name}")
            
            # Extract task ID from response email headers
            task_id = None
            if hasattr(response_email_message, 'raw_message'):
                task_id = response_email_message.raw_message.get('X-IMAP-Assistant-Task-ID')
                logger.debug(f"Extracted task ID from raw_message: {task_id}")
            
            if not task_id:
                logger.warning("Could not find X-IMAP-Assistant-Task-ID header in response email")
                logger.info("Trying to extract task ID from email body as fallback...")
                
                # Fallback: Extract task ID from email body
                try:
                    # Try multiple methods to get email content
                    body_content = None
                    
                    # Method 1: Use extract_email_content from imap client
                    main_account_config = self.config.get_first_account()
                    if main_account_config:
                        temp_client = EnhancedImapClient(main_account_config)
                        try:
                            subject, first_line, body_excerpt = temp_client.extract_email_content(response_email_message)
                            body_content = body_excerpt
                            logger.debug(f"Extracted body using extract_email_content: {body_content[:200] if body_content else 'None'}...")
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
                        import re
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
                        else:
                            logger.warning("❌ Could not find task ID pattern in email body")
                            logger.debug("Expected pattern format: 'Task ID: 12345678-1234-1234-1234-123456789abc'")
                    else:
                        logger.warning("No body content found in email message using any method")
                    
                except Exception as e:
                    logger.error(f"Error extracting body content: {e}")
                
                if not task_id:
                    logger.warning("This response may not be related to a task we forwarded")
                    return None
                
            logger.info(f"Found task ID in response: {task_id}")
            
            # Get processing rules for assignee to find target folder
            processing_rules = self.config.get_processing_rules(assignee_name)
            target_folder = processing_rules.get("target_folder")
            
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
                        msg_task_id = email_msg.raw_message.get('X-IMAP-Assistant-Task-ID')
                        
                        if msg_task_id:
                            found_task_ids.append(msg_task_id)
                            logger.debug(f"Found task ID in folder: {msg_task_id}")
                        
                        if msg_task_id == task_id:
                            # Extract email content for the original client request
                            msg_subject_full, _, msg_body = main_client.extract_email_content(email_msg)
                            
                            logger.info(f"✅ Found matching original task by task ID: {msg_subject_full}")
                            
                            return {
                                "task_subject": msg_subject_full,
                                "task_body": msg_body,
                                "message_id": msg_id,
                                "email_message": email_msg,
                                "task_id": task_id
                            }
                    else:
                        logger.debug(f"Email message {msg_id} has no raw_message attribute")
                            
                logger.warning(f"❌ No email found in {target_folder} with task ID: {task_id}")
                logger.info(f"Available task IDs in folder: {found_task_ids}")
                logger.info(f"Looking for: {task_id}")
                logger.info("This suggests the response is not related to any task we forwarded, or there's a task ID mismatch")
                return None
                
            finally:
                main_client.disconnect()
                
        except Exception as e:
            logger.error(f"Error finding original task: {e}")
            return None
    
    def _check_task_completion(self, original_task: Dict, assignee_response: str) -> dict:
        """Use OpenAI to check if task is completed."""
        if not self.openai_client:
            logger.error("OpenAI client not initialized")
            return {"status": "unclear", "confidence": 1, "reason": "OpenAI client not available"}
            
        # Use the task subject as the original task description
        task_description = original_task.get("task_subject", "")
        
        return self.openai_client.check_task_completion(task_description, assignee_response)
    
    def _generate_client_response(self, original_task: Dict, assignee_response: str, main_imap_client: EnhancedImapClient) -> None:
        """Generate and send response to original client."""
        try:
            if not self.openai_client or not self.smtp_client:
                logger.error("Required clients not initialized")
                return
                
            # Extract original email information
            email_message = original_task.get("email_message")
            if not email_message:
                logger.error("No original email message found")
                return
                
            # Get the original sender (client who made the request)
            original_sender = self._extract_sender_email(email_message.from_address)
            if not original_sender:
                logger.error("Could not extract original sender email")
                return
                
            # Check if client is an assignee (should always be informal)
            is_assignee_client = self._is_client_an_assignee(original_sender)
            
            # Find last sent email to this client for relationship context (unless client is assignee)
            if is_assignee_client:
                last_sent_context = "CLIENT IS TEAM MEMBER - USE INFORMAL TONE"
                logger.info(f"Client {original_sender} is a team member - using informal tone")
            else:
                last_sent_context = self._get_last_sent_email_context(original_sender, main_imap_client)
            
            # Generate response using OpenAI with relationship context
            response_data = self.openai_client.generate_client_response(
                original_subject=original_task.get("task_subject", ""),
                original_content=original_task.get("task_body", ""),
                assigned_task=original_task.get("task_subject", ""),
                assignee_response=assignee_response,
                last_sent_context=last_sent_context
            )
            
            # Send response email to original client
            response_subject = response_data.get("subject", f"Re: {original_task.get('task_subject', 'Your request')}")
            response_body = response_data.get("response", "Your request has been completed.")
            
            # Create draft response instead of sending immediately
            main_account_config = self.config.get_first_account()
            if main_account_config:
                # Create IMAP client for main account to save draft
                main_imap_client = EnhancedImapClient(main_account_config)
                if main_imap_client.connect():
                    try:
                        # Create clean draft email as a proper reply
                        draft_subject = f"[DRAFT-RESPONSE] {response_subject}"
                        
                        # Create proper reply format with original email quoted
                        original_email_content = original_task.get('task_body', '')
                        original_subject = original_task.get('task_subject', '')
                        
                        # Load footer HTML
                        footer_html = ""
                        try:
                            from pathlib import Path
                            footer_path = Path("data/footer.html")
                            if footer_path.exists():
                                with open(footer_path, 'r', encoding='utf-8') as f:
                                    footer_html = f.read()
                                logger.debug("Footer HTML loaded successfully")
                            else:
                                logger.warning("Footer HTML file not found at data/footer.html")
                        except Exception as e:
                            logger.warning(f"Could not load footer HTML: {e}")
                        
                        # Create HTML formatted draft body
                        # Convert line breaks in response and original content
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
                        else:
                            logger.error(f"Failed to create draft response for client: {original_sender}")
                            
                    finally:
                        main_imap_client.disconnect()
                else:
                    logger.error("Failed to connect to main account for draft creation")
                    
        except Exception as e:
            logger.error(f"Error generating client response: {e}")
    
    
    def test_connections(self) -> bool:
        """Test all connections and configurations."""
        logger.info("Testing all connections...")
        
        all_good = True
        
        # Test configuration
        if not self.config.is_valid():
            logger.error("❌ Configuration validation failed")
            all_good = False
        else:
            logger.info("✅ Configuration is valid")
        
        # Test IMAP connection
        if self.imap_client:
            if self.imap_client.connect():
                logger.info("✅ IMAP connection successful")
                self.imap_client.disconnect()
            else:
                logger.error("❌ IMAP connection failed")
                all_good = False
        else:
            logger.error("❌ IMAP client not initialized")
            all_good = False
        
        # Test SMTP connection
        if self.smtp_client:
            if self.smtp_client.test_connection():
                logger.info("✅ SMTP connection successful")
            else:
                logger.error("❌ SMTP connection failed")
                all_good = False
        else:
            logger.error("❌ SMTP client not initialized")
            all_good = False
        
        # Test OpenAI connection
        if self.openai_client:
            if self.openai_client.test_connection():
                logger.info("✅ OpenAI API connection successful")
            else:
                logger.error("❌ OpenAI API connection failed")
                all_good = False
        else:
            logger.error("❌ OpenAI client not initialized")
            all_good = False
        
        if all_good:
            logger.info("🎉 All connections and configurations are working properly!")
        else:
            logger.error("⚠️  Some connections or configurations have issues")
        
        return all_good
    
    def get_status_summary(self) -> dict:
        """Get a summary of the current status."""
        return {
            "config_valid": self.config.is_valid(),
            "imap_initialized": self.imap_client is not None,
            "smtp_initialized": self.smtp_client is not None,
            "openai_initialized": self.openai_client is not None,
            "allowed_senders": self.config.allowed_senders,
            "target_folder": self.config.target_folder,
            "subject_tag": self.config.subject_tag,
            "openai_model": self.config.openai_model
        }
