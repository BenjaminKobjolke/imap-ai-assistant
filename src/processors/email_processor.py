import logging
from typing import List, Tuple, Optional
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
            logger.info(f"Processing message {message_id} from {email_message.from_address}")
            
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
                original_sender=email_message.from_address
            )
            
            if not success:
                logger.error(f"Failed to send RTM todo for message {message_id}")
                return False
            
            # Mark as read on processor account (SUMMERA AI)
            if not self.imap_client.mark_message_as_read(message_id):
                logger.warning(f"Failed to mark message {message_id} as read")
            
            # NEW: Cross-account original email management (and forwarding if needed)
            success = self._handle_original_email(email_message, subject, target_folder, assignee, assignee_email, todo_text, bcc_email)
            if not success:
                logger.warning(f"Failed to handle original email for message {message_id}")
            
            logger.info(f"Successfully processed message {message_id}: {todo_text} (assignee: {assignee})")
            return True
            
        except Exception as e:
            logger.error(f"Error processing single email {message_id}: {e}")
            return False
    
    def _handle_original_email(self, email_message, subject: str, target_folder: str, 
                               assignee: str = "self", assignee_email: str = "", todo_text: str = "", bcc_email: str = "") -> bool:
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
                            additional_message="This task has been assigned to you.\n\nForwarded by IMAP AI Assistant"
                        )
                        
                        if forward_success:
                            logger.info(f"Successfully forwarded original email to {assignee}")
                        else:
                            logger.warning(f"Failed to forward original email to {assignee}")
                    
                    # Now move the original email to the target folder
                    move_success = source_client.client.move_to_folder(original_message_id, target_folder)
                    
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
