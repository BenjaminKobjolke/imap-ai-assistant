import email
import logging
import re
from typing import List, Tuple, Optional
from imap_client_lib import ImapClient as BaseImapClient, Account
from email.utils import parseaddr

logger = logging.getLogger(__name__)


class EnhancedImapClient:
    """Enhanced IMAP client with filtering and folder management capabilities."""
    
    def __init__(self, account_config: dict):
        self.account = Account(
            name=account_config["name"],
            server=account_config["server"],
            username=account_config["username"],
            password=account_config["password"],
            port=account_config["port"],
            use_ssl=account_config["use_ssl"]
        )
        self.client = BaseImapClient(self.account)
        self.connected = False
    
    def connect(self) -> bool:
        """Connect to IMAP server."""
        try:
            if self.client.connect():
                self.connected = True
                logger.info(f"Connected to IMAP server {self.account.server}")
                return True
            else:
                logger.error("Failed to connect to IMAP server")
                return False
        except Exception as e:
            logger.error(f"Error connecting to IMAP server: {e}")
            return False
    
    def disconnect(self) -> None:
        """Disconnect from IMAP server."""
        try:
            if self.connected:
                self.client.disconnect()
                self.connected = False
                logger.info("Disconnected from IMAP server")
        except Exception as e:
            logger.error(f"Error disconnecting from IMAP server: {e}")
    
    def get_filtered_unread_messages(self, allowed_senders: List[str]) -> List[Tuple[str, object]]:
        """Get unread messages filtered by allowed senders."""
        if not self.connected:
            logger.error("Not connected to IMAP server")
            return []
        
        try:
            # Get all unread messages
            all_messages = self.client.get_unread_messages()
            filtered_messages = []
            
            for message_id, email_message in all_messages:
                # Check if sender is in allowed list
                sender_email = self._extract_email_address(email_message.from_address)
                if sender_email and sender_email.lower() in [s.lower() for s in allowed_senders]:
                    filtered_messages.append((message_id, email_message))
                    logger.debug(f"Message from {sender_email} matches allowed senders")
                else:
                    logger.debug(f"Message from {sender_email} not in allowed senders, skipping")
            
            logger.info(f"Found {len(filtered_messages)} unread messages from allowed senders")
            return filtered_messages
            
        except Exception as e:
            logger.error(f"Error getting filtered unread messages: {e}")
            return []
    
    def _extract_email_address(self, from_field: str) -> Optional[str]:
        """Extract email address from 'From' field."""
        try:
            # Parse "Name <email@domain.com>" format
            name, email_addr = parseaddr(from_field)
            return email_addr if email_addr else None
        except Exception as e:
            logger.debug(f"Error parsing email address from '{from_field}': {e}")
            return None
    
    def extract_email_content(self, email_message) -> Tuple[str, str, str]:
        """Extract subject, first line, and body excerpt from email message."""
        subject = email_message.subject or ""
        first_line = ""
        body_excerpt = ""
        
        try:
            # Use the new get_body method - much simpler and more reliable!
            body_text = email_message.get_body("text/plain")
            
            # If no plain text, try HTML and strip tags
            if not body_text:
                html_body = email_message.get_body("text/html")
                if html_body:
                    body_text = re.sub(r'<[^>]+>', '', html_body).strip()
            
            if body_text:
                # Get the first line of text
                first_line = body_text.split('\n')[0].strip()
                if len(first_line) > 200:  # Limit length
                    first_line = first_line[:200] + "..."
                
                # Get body excerpt (first 300 characters)
                body_excerpt = body_text[:800]
                        
        except Exception as e:
            logger.debug(f"Error extracting email content: {e}")
        
        # Ensure we always return valid strings
        return subject or "", first_line or "", body_excerpt or ""
    
    def mark_message_as_read(self, message_id: str) -> bool:
        """Mark a message as read."""
        try:
            self.client.mark_as_read(message_id)
            logger.debug(f"Marked message {message_id} as read")
            return True
        except Exception as e:
            logger.error(f"Error marking message {message_id} as read: {e}")
            return False
    
    def move_message_to_folder(self, message_id: str, folder_name: str) -> bool:
        """Move message to specified folder."""
        try:
            # Use the IMAP client's move capability if available
            if hasattr(self.client, 'move_message'):
                logger.info(f"Moving message {message_id} to folder {folder_name}")
                success = self.client.move_message(message_id, folder_name)
                if success:
                    logger.info(f"Successfully moved message {message_id} to {folder_name}")
                    return True
                else:
                    logger.error(f"Failed to move message {message_id} to {folder_name}")
                    return False
            elif hasattr(self.client, 'move_to_folder'):
                logger.info(f"Moving message {message_id} to folder {folder_name}")
                success = self.client.move_to_folder(message_id, folder_name)
                if success:
                    logger.info(f"Successfully moved message {message_id} to {folder_name}")
                    return True
                else:
                    logger.error(f"Failed to move message {message_id} to {folder_name}")
                    return False
            else:
                logger.warning(f"IMAP client doesn't support message moving - logging action only")
                logger.info(f"Would move message {message_id} to folder {folder_name}")
                return True
        except Exception as e:
            logger.error(f"Error moving message {message_id} to folder {folder_name}: {e}")
            return False
    
    def search_emails_by_subject(self, subject_pattern: str, limit: int = 50) -> List[Tuple[str, object]]:
        """Search emails by subject pattern in the current account."""
        if not self.connected:
            logger.error("Not connected to IMAP server")
            return []
        
        try:
            # Strip common email prefixes for better matching
            clean_subject = self._strip_subject_prefixes(subject_pattern)
            logger.debug(f"Searching for emails with subject pattern: '{clean_subject}'")
            
            # BREAKTHROUGH: Using the new get_all_messages() method from v0.2.0!
            # This allows us to search through ALL messages (both read and unread)
            logger.info("Using enhanced library v0.2.0 - searching through ALL messages (both read and unread)")
            
            # Get ALL messages using the new method
            all_messages = self.client.get_all_messages()
            logger.info(f"Searching through {len(all_messages)} total messages")
            
            # Log available methods for debugging
            available_methods = [method for method in dir(self.client) if not method.startswith('_')]
            logger.debug(f"Available IMAP client methods: {available_methods}")
            
            matching_messages = []
            
            for message_id, email_message in all_messages:
                if hasattr(email_message, 'subject') and email_message.subject:
                    message_subject = self._strip_subject_prefixes(email_message.subject)
                    logger.debug(f"Checking message subject: '{message_subject}' against pattern: '{clean_subject}'")
                    
                    # Check for exact match or partial match
                    if (clean_subject.lower() in message_subject.lower() or 
                        message_subject.lower() in clean_subject.lower()):
                        matching_messages.append((message_id, email_message))
                        logger.info(f"Found matching email: {message_subject}")
                
                # Limit results to avoid processing too many emails
                if len(matching_messages) >= limit:
                    break
            
            logger.info(f"Found {len(matching_messages)} emails matching subject pattern '{clean_subject}'")
            
            if len(matching_messages) == 0:
                logger.warning("No matching emails found in ALL messages")
                logger.info("This could mean the email doesn't exist or the subject doesn't match the pattern")
            
            return matching_messages
            
        except Exception as e:
            logger.error(f"Error searching emails by subject: {e}")
            logger.info("Falling back to unread messages only")
            try:
                # Fallback to unread messages if ALL search fails
                all_messages = self.client.get_unread_messages()
                logger.info(f"Fallback: Searching through {len(all_messages)} unread messages")
                
                matching_messages = []
                for message_id, email_message in all_messages:
                    if hasattr(email_message, 'subject') and email_message.subject:
                        message_subject = self._strip_subject_prefixes(email_message.subject)
                        if (clean_subject.lower() in message_subject.lower() or 
                            message_subject.lower() in clean_subject.lower()):
                            matching_messages.append((message_id, email_message))
                            logger.info(f"Found matching email (fallback): {message_subject}")
                
                return matching_messages
            except Exception as fallback_error:
                logger.error(f"Fallback search also failed: {fallback_error}")
                return []
    
    def _strip_subject_prefixes(self, subject: str) -> str:
        """Strip common email prefixes from subject line."""
        if not subject:
            return ""
        
        # Common prefixes to remove
        prefixes = [r'^(Re:|Fwd?:|FW:|AW:|WG:)\s*', r'^(RE:|FWD:|FORWARD:)\s*']
        
        cleaned_subject = subject.strip()
        for prefix_pattern in prefixes:
            cleaned_subject = re.sub(prefix_pattern, '', cleaned_subject, flags=re.IGNORECASE)
            cleaned_subject = cleaned_subject.strip()
        
        return cleaned_subject
    
    def search_and_move_original_email(self, forwarded_subject: str, target_folder: str) -> bool:
        """Search for original email and move it to target folder."""
        try:
            # Strip "Fwd:" prefix to get original subject
            original_subject = self._strip_subject_prefixes(forwarded_subject)
            logger.info(f"Searching for original email with subject: '{original_subject}'")
            logger.info(f"Original forwarded subject was: '{forwarded_subject}'")
            
            # Search for emails with matching subject (now searches ALL messages!)
            matching_emails = self.search_emails_by_subject(original_subject, limit=10)
            
            if not matching_emails:
                logger.warning(f"No emails found with subject pattern: '{original_subject}'")
                logger.info("This could mean:")
                logger.info("1. The original email doesn't exist in this account")
                logger.info("2. The subject pattern doesn't match exactly") 
                logger.info("3. The email might be in a different folder")
                return False
            
            # Move the first matching email (most likely the original)
            message_id, email_message = matching_emails[0]
            
            logger.info(f"Found original email! Moving '{email_message.subject}' to folder '{target_folder}'")
            success = self.move_message_to_folder(message_id, target_folder)
            
            if success:
                logger.info(f"Successfully moved original email to {target_folder}")
                return True
            else:
                logger.error(f"Failed to move original email to {target_folder}")
                return False
                
        except Exception as e:
            logger.error(f"Error in search_and_move_original_email: {e}")
            return False
