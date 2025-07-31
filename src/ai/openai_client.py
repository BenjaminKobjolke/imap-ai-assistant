import logging
import re
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
from openai import OpenAI

logger = logging.getLogger(__name__)


class OpenAIClient:
    """OpenAI client for processing emails into RTM todo format."""
    
    def __init__(self, api_key: str, model: str = "gpt-4o", max_tokens: int = 100, temperature: float = 0.3):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.system_prompt = ""
        self.user_prompt_template = ""
        self._load_prompts()
    
    def _load_prompts(self) -> None:
        """Load system and user prompts from files."""
        try:
            # Calculate current date for dynamic injection
            current_date = datetime.now().strftime("%d.%m.%Y")
            
            # Load system prompt
            system_prompt_path = Path("prompts/system_prompt.txt")
            if system_prompt_path.exists():
                with open(system_prompt_path, 'r', encoding='utf-8') as f:
                    system_prompt_template = f.read().strip()
                # Inject current date into the system prompt
                self.system_prompt = system_prompt_template.format(current_date=current_date)
                logger.debug(f"System prompt loaded successfully with date: {current_date}")
            else:
                logger.warning("System prompt file not found")
            
            # Load user prompt template
            user_prompt_path = Path("prompts/user_prompt.txt")
            if user_prompt_path.exists():
                with open(user_prompt_path, 'r', encoding='utf-8') as f:
                    self.user_prompt_template = f.read().strip()
                logger.debug("User prompt template loaded successfully")
            else:
                logger.warning("User prompt template file not found")
                
        except Exception as e:
            logger.error(f"Error loading prompts: {e}")
    
    def process_email_to_todo(self, subject: str, first_line: str, body_excerpt: str) -> Optional[str]:
        """Process email content into RTM todo format using OpenAI."""
        try:
            from string import Template
            template = Template(self.user_prompt_template)
            user_prompt = template.safe_substitute(
                subject=subject,
                first_line=first_line,
                body_excerpt=body_excerpt  # Note: should be body_excerpt, not sender
            )            
           
            print(f"User prompt: {user_prompt}")
            # Call OpenAI API with JSON mode
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                response_format={"type": "json_object"}
            )
            
            # Extract response content
            if response.choices and response.choices[0].message and response.choices[0].message.content:
                response_content = response.choices[0].message.content.strip()
                logger.info(f"OpenAI response: {response_content}")
                
                try:
                    # Parse JSON response
                    json_response = json.loads(response_content)
                    
                    # Extract todo text from JSON (assuming it has a 'todo' field)
                    # In the future, we can extract multiple fields as needed
                    todo_text = json_response.get('todo', '')
                    
                    # Validate and clean the response
                    validated_todo = self._validate_todo_format(todo_text)
                    if validated_todo:
                        logger.info(f"Validated todo: {validated_todo}")
                        return validated_todo
                    else:
                        logger.warning(f"Invalid todo format from OpenAI: {todo_text}")
                        # Return a fallback todo
                        return self._create_fallback_todo(subject, first_line, body_excerpt)
                        
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON response: {e}")
                    return self._create_fallback_todo(subject, first_line, body_excerpt)
            else:
                logger.error("No response content from OpenAI")
                return self._create_fallback_todo(subject, first_line, body_excerpt)
                
        except Exception as e:
            logger.error(f"Error processing email with OpenAI: {e}")
            return self._create_fallback_todo(subject, first_line, body_excerpt)
    
    def _validate_todo_format(self, todo_text: str) -> Optional[str]:
        """Validate that the todo text follows RTM format: TODONAME !importance ^duedate"""
        try:
            # Clean up the response (remove quotes, extra whitespace)
            todo_text = todo_text.strip().strip('"\'')
            
            # Check if it contains both importance (!1, !2, !3) and due date (^today, ^tomorrow, ^date)
            importance_pattern = r'![123]'
            due_date_pattern = r'\^(today|tomorrow|\d{1,2}\.\d{1,2}\.\d{4})'
            
            has_importance = bool(re.search(importance_pattern, todo_text))
            has_due_date = bool(re.search(due_date_pattern, todo_text))
            
            if has_importance and has_due_date:
                return todo_text
            else:
                logger.debug(f"Todo format validation failed: importance={has_importance}, due_date={has_due_date}")
                return None
                
        except Exception as e:
            logger.debug(f"Error validating todo format: {e}")
            return None
    
    def _create_fallback_todo(self, subject: str, first_line: str, sender: str = "") -> str:
        """Create a fallback todo when OpenAI fails or returns invalid format."""
        # Use subject as todo name, default importance and due date
        todo_name = subject or first_line or "Unknown task"
        
        # Clean up the todo name (remove common email prefixes)
        todo_name = re.sub(r'^(Re:|Fwd?:|AW:)\s*', '', todo_name, flags=re.IGNORECASE)
        todo_name = todo_name.strip()
        
        # Add sender context if it's not from XIDA
        if sender and 'xida' not in sender.lower():
            # Extract sender name or company from sender string
            sender_name = self._extract_sender_name(sender)
            if sender_name:
                todo_name = f"{sender_name}: {todo_name}"
        
        # Limit length
        if len(todo_name) > 50:
            todo_name = todo_name[:50] + "..."
        
        # Return with default importance and due date
        fallback_todo = f"{todo_name} !2 ^tomorrow"
        logger.info(f"Created fallback todo: {fallback_todo}")
        return fallback_todo
    
    def _extract_sender_name(self, sender: str) -> str:
        """Extract clean sender name from sender string."""
        try:
            from email.utils import parseaddr
            # Parse "Name <email@domain.com>" format
            name, email_addr = parseaddr(sender)
            
            if name and name.strip():
                return name.strip()
            elif email_addr:
                # Extract domain name as fallback
                if '@' in email_addr:
                    domain = email_addr.split('@')[1]
                    # Clean up domain (remove .com, .de, etc.)
                    domain = domain.split('.')[0]
                    return domain.title()
                return email_addr
            else:
                return sender
        except Exception as e:
            logger.debug(f"Error extracting sender name from '{sender}': {e}")
            return sender
    
    def test_connection(self) -> bool:
        """Test OpenAI API connection."""
        try:
            # Simple test API call
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=10
            )
            
            if response.choices:
                logger.info("OpenAI API connection test successful")
                return True
            else:
                logger.error("OpenAI API connection test failed: No response")
                return False
                
        except Exception as e:
            logger.error(f"OpenAI API connection test failed: {e}")
            return False
