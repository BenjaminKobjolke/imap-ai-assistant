import logging
import re
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
from openai import OpenAI
from src.logging.app_logger import ApplicationLogger

logger = logging.getLogger(__name__)


class OpenAIClient:
    """OpenAI client for processing emails into RTM todo format."""
    
    def __init__(self, api_key: str, model: str = "gpt-4o", max_tokens: int = 100, temperature: float = 0.3, other_people: List[str] = None, app_logger: Optional[ApplicationLogger] = None):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.other_people = other_people or []
        self.app_logger = app_logger
        self.system_prompt = ""
        self.user_prompt_template = ""
        self.task_completion_system_prompt = ""
        self.task_completion_user_prompt_template = ""
        self.client_response_system_prompt = ""
        self.client_response_user_prompt_template = ""
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
                exit(1)
            
            # Load user prompt template
            user_prompt_path = Path("prompts/user_prompt.txt")
            if user_prompt_path.exists():
                with open(user_prompt_path, 'r', encoding='utf-8') as f:
                    self.user_prompt_template = f.read().strip()
                logger.debug("User prompt template loaded successfully")
            else:
                logger.warning("User prompt template file not found")
                exit(1)
                
            # Load task completion prompts
            task_completion_system_path = Path("prompts/task_completion_system_prompt.txt")
            if task_completion_system_path.exists():
                with open(task_completion_system_path, 'r', encoding='utf-8') as f:
                    self.task_completion_system_prompt = f.read().strip()
                logger.debug("Task completion system prompt loaded successfully")
                
            task_completion_user_path = Path("prompts/task_completion_user_prompt.txt")
            if task_completion_user_path.exists():
                with open(task_completion_user_path, 'r', encoding='utf-8') as f:
                    self.task_completion_user_prompt_template = f.read().strip()
                logger.debug("Task completion user prompt loaded successfully")
                
            # Load client response prompts
            client_response_system_path = Path("prompts/client_response_system_prompt.txt")
            if client_response_system_path.exists():
                with open(client_response_system_path, 'r', encoding='utf-8') as f:
                    self.client_response_system_prompt = f.read().strip()
                logger.debug("Client response system prompt loaded successfully")
                
            client_response_user_path = Path("prompts/client_response_user_prompt.txt")
            if client_response_user_path.exists():
                with open(client_response_user_path, 'r', encoding='utf-8') as f:
                    self.client_response_user_prompt_template = f.read().strip()
                logger.debug("Client response user prompt loaded successfully")
                
        except Exception as e:
            logger.error(f"Error loading prompts: {e}")
            exit(1)
    
    def process_email_to_todo(self, subject: str, first_line: str, body_excerpt: str) -> Optional[Tuple[str, str]]:
        """Process email content into RTM todo format using OpenAI."""
        request_id = None
        start_time = time.time()
        
        try:
            print(f"User prompt template: {self.user_prompt_template}")
            from string import Template
            template = Template(self.user_prompt_template)
            
            # Create assignees list
            assignees = ["self"] + self.other_people
            assignees_str = ", ".join(assignees)
            
            user_prompt = template.safe_substitute(
                subject=subject,
                first_line=first_line,
                body_excerpt=body_excerpt,
                assignees=assignees_str
            )
            
            # Log the request
            if self.app_logger:
                request_data = {
                    "subject": subject,
                    "first_line": first_line,
                    "body_excerpt": body_excerpt,
                    "system_prompt": self.system_prompt[:200] + "..." if len(self.system_prompt) > 200 else self.system_prompt,
                    "user_prompt": user_prompt
                }
                metadata = {
                    "model": self.model,
                    "max_tokens": self.max_tokens,
                    "temperature": self.temperature
                }
                request_id = self.app_logger.log_ai_request("email_to_todo", request_data, metadata)
           
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
                
                # Log the response
                if self.app_logger and request_id:
                    processing_time = time.time() - start_time
                    tokens_used = {
                        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                        "total_tokens": response.usage.total_tokens if response.usage else 0
                    }
                    self.app_logger.log_ai_response(request_id, "email_to_todo", response_content, processing_time, tokens_used)
                
                try:
                    # Parse JSON response
                    json_response = json.loads(response_content)
                    
                    # Extract todo text and assignee from JSON
                    todo_text = json_response.get('todo', '')
                    assignee = json_response.get('assignee', 'self')
                    
                    # Validate and clean the response
                    validated_todo = self._validate_todo_format(todo_text)
                    if validated_todo:
                        logger.info(f"Validated todo: {validated_todo}, assignee: {assignee}")
                        return validated_todo, assignee
                    else:
                        logger.warning(f"Invalid todo format from OpenAI: {todo_text}")
                        # Return a fallback todo
                        return self._create_fallback_todo(subject, first_line, body_excerpt), "self"
                        
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON response: {e}")
                    return self._create_fallback_todo(subject, first_line, body_excerpt), "self"
            else:
                logger.error("No response content from OpenAI")
                return self._create_fallback_todo(subject, first_line, body_excerpt), "self"
                
        except Exception as e:
            logger.error(f"Error processing email with OpenAI: {e}")
            # Log the error
            if self.app_logger:
                if not request_id:
                    request_id = str(time.time())
                self.app_logger.log_ai_error(request_id, "email_to_todo", e, {"subject": subject})
            return self._create_fallback_todo(subject, first_line, body_excerpt), "self"
    
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
    
    def check_task_completion(self, original_task: str, assignee_response: str) -> Dict[str, Any]:
        """Check if a task is completed based on assignee's response."""
        request_id = None
        start_time = time.time()
        
        try:
            from string import Template
            template = Template(self.task_completion_user_prompt_template)
            user_prompt = template.safe_substitute(
                original_task=original_task,
                assignee_response=assignee_response
            )
            
            # Log the request
            if self.app_logger:
                request_data = {
                    "original_task": original_task,
                    "assignee_response": assignee_response,
                    "system_prompt": self.task_completion_system_prompt[:200] + "..." if len(self.task_completion_system_prompt) > 200 else self.task_completion_system_prompt,
                    "user_prompt": user_prompt
                }
                metadata = {
                    "model": self.model,
                    "max_tokens": 150,
                    "temperature": 0.3
                }
                request_id = self.app_logger.log_ai_request("task_completion", request_data, metadata)
            
            # Call OpenAI API with JSON mode
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.task_completion_system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=150,
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            
            if response.choices and response.choices[0].message and response.choices[0].message.content:
                response_content = response.choices[0].message.content.strip()
                logger.info(f"Task completion check response: {response_content}")
                
                # Log the response
                if self.app_logger and request_id:
                    processing_time = time.time() - start_time
                    tokens_used = {
                        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                        "total_tokens": response.usage.total_tokens if response.usage else 0
                    }
                    self.app_logger.log_ai_response(request_id, "task_completion", response_content, processing_time, tokens_used)
                
                try:
                    json_response = json.loads(response_content)
                    return json_response
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse task completion response: {e}")
                    return {"status": "unclear", "confidence": 1, "reason": "Failed to parse response"}
            else:
                return {"status": "unclear", "confidence": 1, "reason": "No response from OpenAI"}
                
        except Exception as e:
            logger.error(f"Error checking task completion: {e}")
            # Log the error
            if self.app_logger:
                if not request_id:
                    request_id = str(time.time())
                self.app_logger.log_ai_error(request_id, "task_completion", e, {"original_task": original_task})
            return {"status": "unclear", "confidence": 1, "reason": f"Error: {str(e)}"}
    
    def generate_client_response(self, original_subject: str, original_content: str, 
                                 assigned_task: str, assignee_response: str, 
                                 last_sent_context: Optional[str] = None) -> Dict[str, str]:
        """Generate a response to send to the client based on completed task."""
        request_id = None
        start_time = time.time()
        
        try:
            from string import Template
            template = Template(self.client_response_user_prompt_template)
            user_prompt = template.safe_substitute(
                original_subject=original_subject,
                original_content=original_content,
                assigned_task=assigned_task,
                assignee_response=assignee_response,
                last_sent_context=last_sent_context or "No previous email context available"
            )
            
            # Log the request
            if self.app_logger:
                request_data = {
                    "original_subject": original_subject,
                    "original_content": original_content[:500] + "..." if len(original_content) > 500 else original_content,
                    "assigned_task": assigned_task,
                    "assignee_response": assignee_response,
                    "last_sent_context": (last_sent_context[:200] + "...") if last_sent_context and len(last_sent_context) > 200 else last_sent_context,
                    "system_prompt": self.client_response_system_prompt[:200] + "..." if len(self.client_response_system_prompt) > 200 else self.client_response_system_prompt,
                    "user_prompt": user_prompt[:500] + "..." if len(user_prompt) > 500 else user_prompt
                }
                metadata = {
                    "model": self.model,
                    "max_tokens": 500,
                    "temperature": 0.7
                }
                request_id = self.app_logger.log_ai_request("client_response", request_data, metadata)
            
            # Call OpenAI API with JSON mode
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.client_response_system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_tokens=500,
                temperature=0.7,
                response_format={"type": "json_object"}
            )
            
            if response.choices and response.choices[0].message and response.choices[0].message.content:
                response_content = response.choices[0].message.content.strip()
                logger.info(f"Client response generation: {response_content}")
                
                # Log the response
                if self.app_logger and request_id:
                    processing_time = time.time() - start_time
                    tokens_used = {
                        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                        "total_tokens": response.usage.total_tokens if response.usage else 0
                    }
                    self.app_logger.log_ai_response(request_id, "client_response", response_content, processing_time, tokens_used)
                
                try:
                    json_response = json.loads(response_content)
                    return json_response
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse client response: {e}")
                    return {"response": "Task completed.", "subject": "Re: " + original_subject}
            else:
                return {"response": "Task completed.", "subject": "Re: " + original_subject}
                
        except Exception as e:
            logger.error(f"Error generating client response: {e}")
            # Log the error
            if self.app_logger:
                if not request_id:
                    request_id = str(time.time())
                self.app_logger.log_ai_error(request_id, "client_response", e, {"original_subject": original_subject})
            return {"response": "Task completed.", "subject": "Re: " + original_subject}
    
    def test_connection(self) -> bool:
        """Test OpenAI API connection."""
        request_id = None
        start_time = time.time()
        
        try:
            # Log the test request
            if self.app_logger:
                request_data = {
                    "test_message": "Hello",
                    "purpose": "connection_test"
                }
                metadata = {
                    "model": self.model,
                    "max_tokens": 10
                }
                request_id = self.app_logger.log_ai_request("connection_test", request_data, metadata)
            
            # Simple test API call
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=10
            )
            
            if response.choices:
                logger.info("OpenAI API connection test successful")
                
                # Log the successful test
                if self.app_logger and request_id:
                    processing_time = time.time() - start_time
                    response_data = {
                        "status": "success",
                        "response": response.choices[0].message.content if response.choices[0].message else None
                    }
                    tokens_used = {
                        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                        "total_tokens": response.usage.total_tokens if response.usage else 0
                    }
                    self.app_logger.log_ai_response(request_id, "connection_test", response_data, processing_time, tokens_used)
                
                return True
            else:
                logger.error("OpenAI API connection test failed: No response")
                return False
                
        except Exception as e:
            logger.error(f"OpenAI API connection test failed: {e}")
            # Log the error
            if self.app_logger:
                if not request_id:
                    request_id = str(time.time())
                self.app_logger.log_ai_error(request_id, "connection_test", e)
            return False
