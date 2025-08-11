import logging
import re
import html
from typing import Optional
from src.config.settings import ConfigManager
from src.email.imap_client import EnhancedImapClient

logger = logging.getLogger(__name__)


class RelationshipAnalyzer:
    """Analyzes client relationships based on past email communication."""
    
    def __init__(self, config: ConfigManager):
        self.config = config
    
    def get_relationship_context(self, client_email: str, main_imap_client: EnhancedImapClient) -> Optional[str]:
        """Get relationship context for a client email address."""
        # Check if client is an assignee (should always be informal)
        if self._is_client_an_assignee(client_email):
            logger.info(f"Client {client_email} is a team member - using informal tone")
            return "CLIENT IS TEAM MEMBER - USE INFORMAL TONE"
        
        # Find last sent email for relationship context
        return self._get_last_sent_email_context(client_email, main_imap_client)
    
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