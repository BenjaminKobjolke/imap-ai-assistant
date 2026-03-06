from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from src.ai.prompt_loader import PromptLoader
from src.constants import (
    AI_CHAT_INTENT_TEMPERATURE,
    AI_CHAT_INTERPRET_TEMPERATURE,
    AI_CHAT_MAX_INTENT_TOKENS,
    AI_CHAT_MAX_INTERPRET_TOKENS,
    AI_CHAT_MAX_OUTPUT_CHARS,
    AI_CHAT_MAX_VALIDATE_TOKENS,
    AI_CHAT_TIMEOUT,
    AI_CHAT_VALIDATE_TEMPERATURE,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    KEY_CONFIDENCE,
    KEY_FORMAL,
    KEY_REASON,
    KEY_RESPONSE,
    KEY_SALUTATION,
    KEY_STATUS,
    KEY_SUBJECT,
    OPENAI_TIMEOUT,
    PREFIX_REPLY,
    STATUS_UNCLEAR,
)
from src.logging.app_logger import ApplicationLogger

logger = logging.getLogger(__name__)


@dataclass
class TodoResult:
    """Structured result from AI todo generation."""

    title: str
    priority: int
    due_date: str
    assignee: str
    due_time: str = ""

    @property
    def rtm_text(self) -> str:
        """Assemble into RTM format: 'Title !priority ^due_date [HH:MM]'."""
        time_part = f" {self.due_time}" if self.due_time else ""
        return f"{self.title} !{self.priority} ^{self.due_date}{time_part}"


class OpenAIClient:
    """OpenAI client for processing emails into RTM todo format."""

    def __init__(
        self, api_key: str, model: str = DEFAULT_MODEL, max_completion_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE, other_people: list[str] | None = None,
        app_logger: ApplicationLogger | None = None,
    ):
        self.client = OpenAI(api_key=api_key, timeout=OPENAI_TIMEOUT)
        self.model = model
        self.max_completion_tokens = max_completion_tokens
        self.temperature = temperature
        self.other_people = other_people or []
        self.app_logger = app_logger
        self._prompts = PromptLoader()

    @property
    def system_prompt(self) -> str:
        """Get the system prompt."""
        return self._prompts.system_prompt

    @property
    def user_prompt_template(self) -> str:
        """Get the user prompt template."""
        return self._prompts.user_prompt_template

    @property
    def task_completion_system_prompt(self) -> str:
        """Get the task completion system prompt."""
        return self._prompts.task_completion_system_prompt

    @property
    def task_completion_user_prompt_template(self) -> str:
        """Get the task completion user prompt template."""
        return self._prompts.task_completion_user_prompt_template

    @property
    def client_response_system_prompt(self) -> str:
        """Get the client response system prompt."""
        return self._prompts.client_response_system_prompt

    @property
    def client_response_user_prompt_template(self) -> str:
        """Get the client response user prompt template."""
        return self._prompts.client_response_user_prompt_template

    def process_email_to_todo(self, subject: str, first_line: str, body_excerpt: str) -> TodoResult | None:
        """Process email content into RTM todo format using OpenAI."""
        request_id = None
        start_time = time.time()

        try:
            from string import Template
            template = Template(self.user_prompt_template)

            # Create assignees list
            assignees = ["self", *self.other_people]
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
                    "system_prompt": (
                        self.system_prompt[:200] + "..."
                        if len(self.system_prompt) > 200 else self.system_prompt
                    ),
                    "user_prompt": user_prompt
                }
                metadata = {
                    "model": self.model,
                    "max_completion_tokens": self.max_completion_tokens,
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
                max_completion_tokens=self.max_completion_tokens,
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
                    self.app_logger.log_ai_response(
                        request_id, "email_to_todo",
                        response_content, processing_time, tokens_used,
                    )

                try:
                    # Parse JSON response
                    json_response = json.loads(response_content)

                    # Extract structured fields from JSON
                    title = json_response.get('title', '')
                    assignee = json_response.get('assignee', 'self')
                    priority = json_response.get('priority', 2)
                    due_date = json_response.get('due_date', 'tomorrow')

                    # Validate structured fields
                    validated = self._validate_structured_todo(title, priority, due_date)
                    if validated:
                        clean_title, clean_priority, clean_due_date = validated
                        result = TodoResult(clean_title, clean_priority, clean_due_date, assignee)
                        logger.info(f"Validated todo: {result.rtm_text}, assignee: {assignee}")
                        return result
                    else:
                        logger.warning(
                            f"Invalid structured todo from OpenAI: "
                            f"title={title}, priority={priority}, due_date={due_date}"
                        )
                        return self._create_fallback_todo(subject, first_line, body_excerpt)

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON response: {e}")
                    return self._create_fallback_todo(subject, first_line, body_excerpt)
            else:
                logger.error("No response content from OpenAI")
                return self._create_fallback_todo(subject, first_line, body_excerpt)

        except Exception as e:
            logger.error(f"Error processing email with OpenAI: {e}")
            # Log the error
            if self.app_logger:
                if not request_id:
                    request_id = str(time.time())
                self.app_logger.log_ai_error(request_id, "email_to_todo", e, {"subject": subject})
            return self._create_fallback_todo(subject, first_line, body_excerpt)

    def _validate_structured_todo(
        self, title: str | Any, priority: int | Any, due_date: str | Any,
    ) -> tuple[str, int, str] | None:
        """Validate structured todo fields returned by OpenAI."""
        try:
            # Validate title is a non-empty string
            if not isinstance(title, str) or not title.strip():
                logger.debug("Structured todo validation failed: empty or non-string title")
                return None
            clean_title = title.strip()

            # Validate priority is int 1, 2, or 3
            try:
                clean_priority = int(priority)
            except (TypeError, ValueError):
                logger.debug(f"Structured todo validation failed: invalid priority={priority}")
                return None
            if clean_priority not in (1, 2, 3):
                logger.debug(f"Structured todo validation failed: priority={clean_priority} not in 1-3")
                return None

            # Validate due_date matches today|tomorrow|DD.MM.YYYY
            if not isinstance(due_date, str) or not due_date.strip():
                logger.debug("Structured todo validation failed: empty or non-string due_date")
                return None
            clean_due_date = due_date.strip()
            due_date_pattern = r'^(today|tomorrow|\d{1,2}\.\d{1,2}\.\d{4})$'
            if not re.match(due_date_pattern, clean_due_date):
                logger.debug(f"Structured todo validation failed: due_date={clean_due_date} invalid format")
                return None

            return clean_title, clean_priority, clean_due_date

        except Exception as e:
            logger.debug(f"Error validating structured todo: {e}")
            return None

    def _create_fallback_todo(self, subject: str, first_line: str, sender: str = "") -> TodoResult:
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

        result = TodoResult(title=todo_name, priority=2, due_date="tomorrow", assignee="self")
        logger.info(f"Created fallback todo: {result.rtm_text}")
        return result

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

    def check_task_completion(self, original_task: str, assignee_response: str) -> dict[str, Any]:
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
                    "system_prompt": (
                        self.task_completion_system_prompt[:200] + "..."
                        if len(self.task_completion_system_prompt) > 200
                        else self.task_completion_system_prompt
                    ),
                    "user_prompt": user_prompt
                }
                metadata = {
                    "model": self.model,
                    "max_completion_tokens": 150,
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
                max_completion_tokens=150,
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
                    self.app_logger.log_ai_response(
                        request_id, "task_completion",
                        response_content, processing_time, tokens_used,
                    )

                try:
                    json_response: dict[str, Any] = json.loads(response_content)
                    return json_response
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse task completion response: {e}")
                    return {KEY_STATUS: STATUS_UNCLEAR, KEY_CONFIDENCE: 1, KEY_REASON: "Failed to parse response"}
            else:
                return {KEY_STATUS: STATUS_UNCLEAR, KEY_CONFIDENCE: 1, KEY_REASON: "No response from OpenAI"}

        except Exception as e:
            logger.error(f"Error checking task completion: {e}")
            # Log the error
            if self.app_logger:
                if not request_id:
                    request_id = str(time.time())
                self.app_logger.log_ai_error(request_id, "task_completion", e, {"original_task": original_task})
            return {KEY_STATUS: STATUS_UNCLEAR, KEY_CONFIDENCE: 1, KEY_REASON: f"Error: {e!s}"}

    def generate_client_response(self, original_subject: str, original_content: str,
                                 assigned_task: str, assignee_response: str,
                                 last_sent_context: str | None = None) -> dict[str, str]:
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
                    "original_content": (
                        original_content[:500] + "..."
                        if len(original_content) > 500 else original_content
                    ),
                    "assigned_task": assigned_task,
                    "assignee_response": assignee_response,
                    "last_sent_context": (
                        (last_sent_context[:200] + "...")
                        if last_sent_context and len(last_sent_context) > 200
                        else last_sent_context
                    ),
                    "system_prompt": (
                        self.client_response_system_prompt[:200] + "..."
                        if len(self.client_response_system_prompt) > 200
                        else self.client_response_system_prompt
                    ),
                    "user_prompt": (
                        user_prompt[:500] + "..."
                        if len(user_prompt) > 500 else user_prompt
                    )
                }
                metadata = {
                    "model": self.model,
                    "max_completion_tokens": 500,
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
                max_completion_tokens=500,
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
                    self.app_logger.log_ai_response(
                        request_id, "client_response",
                        response_content, processing_time, tokens_used,
                    )

                try:
                    json_response: dict[str, str] = json.loads(response_content)
                    return json_response
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse client response: {e}")
                    return {KEY_RESPONSE: "Task completed.", KEY_SUBJECT: PREFIX_REPLY + original_subject}
            else:
                return {KEY_RESPONSE: "Task completed.", KEY_SUBJECT: PREFIX_REPLY + original_subject}

        except Exception as e:
            logger.error(f"Error generating client response: {e}")
            # Log the error
            if self.app_logger:
                if not request_id:
                    request_id = str(time.time())
                self.app_logger.log_ai_error(request_id, "client_response", e, {"original_subject": original_subject})
            return {KEY_RESPONSE: "Task completed.", KEY_SUBJECT: PREFIX_REPLY + original_subject}

    def generate_draft_reply(
        self,
        original_subject: str,
        original_body: str,
        user_instruction: str,
        conversation_history: str,
    ) -> str | None:
        """Generate a draft reply body from user instruction and original email context."""
        request_id = None
        start_time = time.time()

        try:
            from string import Template

            template = Template(self._prompts.draft_reply_user_prompt_template)
            user_prompt = template.safe_substitute(
                original_subject=original_subject,
                original_body=original_body,
                user_instruction=user_instruction,
                conversation_history=conversation_history or "(none)",
            )

            if self.app_logger:
                request_data = {
                    "original_subject": original_subject,
                    "user_instruction": user_instruction,
                    "system_prompt": self._prompts.draft_reply_system_prompt[:200] + "...",
                    "user_prompt": user_prompt[:500] + "...",
                }
                metadata = {"model": self.model, "max_completion_tokens": 500, "temperature": 0.7}
                request_id = self.app_logger.log_ai_request("draft_reply", request_data, metadata)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._prompts.draft_reply_system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_completion_tokens=500,
                temperature=0.7,
            )

            if response.choices and response.choices[0].message and response.choices[0].message.content:
                content = response.choices[0].message.content.strip()

                if self.app_logger and request_id:
                    processing_time = time.time() - start_time
                    tokens_used = {
                        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                        "total_tokens": response.usage.total_tokens if response.usage else 0,
                    }
                    self.app_logger.log_ai_response(request_id, "draft_reply", content, processing_time, tokens_used)

                return content

            logger.error("No response content from OpenAI for draft reply")
            return None

        except Exception as e:
            logger.error(f"Error generating draft reply: {e}")
            if self.app_logger:
                if not request_id:
                    request_id = str(time.time())
                self.app_logger.log_ai_error(request_id, "draft_reply", e, {"original_subject": original_subject})
            return None

    def correct_grammar(self, body_text: str) -> str | None:
        """Correct grammar and spelling in the given text."""
        request_id = None
        start_time = time.time()

        try:
            from string import Template

            template = Template(self._prompts.draft_grammar_user_prompt_template)
            user_prompt = template.safe_substitute(body_text=body_text)

            if self.app_logger:
                request_data = {
                    "body_text": body_text[:300] + "...",
                    "system_prompt": self._prompts.draft_grammar_system_prompt[:200] + "...",
                }
                metadata = {"model": self.model, "max_completion_tokens": 500, "temperature": 0.1}
                request_id = self.app_logger.log_ai_request("grammar_correction", request_data, metadata)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._prompts.draft_grammar_system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_completion_tokens=500,
                temperature=0.1,
            )

            if response.choices and response.choices[0].message and response.choices[0].message.content:
                content = response.choices[0].message.content.strip()

                if self.app_logger and request_id:
                    processing_time = time.time() - start_time
                    tokens_used = {
                        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                        "total_tokens": response.usage.total_tokens if response.usage else 0,
                    }
                    self.app_logger.log_ai_response(
                        request_id, "grammar_correction", content, processing_time, tokens_used,
                    )

                return content

            logger.error("No response content from OpenAI for grammar correction")
            return None

        except Exception as e:
            logger.error(f"Error correcting grammar: {e}")
            if self.app_logger:
                if not request_id:
                    request_id = str(time.time())
                self.app_logger.log_ai_error(request_id, "grammar_correction", e)
            return None

    def detect_salutation(self, email_address: str, sent_email_bodies: str) -> dict[str, Any] | None:
        """Detect salutation from sent emails using AI. Returns {salutation, formal}."""
        request_id = None
        start_time = time.time()

        try:
            from string import Template

            template = Template(self._prompts.salutation_user_prompt_template)
            user_prompt = template.safe_substitute(
                email_address=email_address,
                sent_emails=sent_email_bodies,
            )

            if self.app_logger:
                request_data = {
                    "email_address": email_address,
                    "sent_emails": sent_email_bodies[:300] + "...",
                    "system_prompt": self._prompts.salutation_system_prompt[:200] + "...",
                }
                metadata = {"model": self.model, "max_completion_tokens": 100, "temperature": 0.3}
                request_id = self.app_logger.log_ai_request("detect_salutation", request_data, metadata)

            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self._prompts.salutation_system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_completion_tokens=100,
                temperature=0.3,
                response_format={"type": "json_object"},
            )

            if response.choices and response.choices[0].message and response.choices[0].message.content:
                content = response.choices[0].message.content.strip()

                if self.app_logger and request_id:
                    processing_time = time.time() - start_time
                    tokens_used = {
                        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                        "total_tokens": response.usage.total_tokens if response.usage else 0,
                    }
                    self.app_logger.log_ai_response(request_id, "detect_salutation", content, processing_time, tokens_used)

                try:
                    result: dict[str, Any] = json.loads(content)
                    if KEY_SALUTATION in result and KEY_FORMAL in result:
                        return result
                    logger.warning(f"Salutation response missing required keys: {result}")
                    return None
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse salutation response: {e}")
                    return None

            logger.error("No response content from OpenAI for salutation detection")
            return None

        except Exception as e:
            logger.error(f"Error detecting salutation: {e}")
            if self.app_logger:
                if not request_id:
                    request_id = str(time.time())
                self.app_logger.log_ai_error(request_id, "detect_salutation", e, {"email_address": email_address})
            return None

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
                    "max_completion_tokens": 10
                }
                request_id = self.app_logger.log_ai_request("connection_test", request_data, metadata)

            # Simple test API call
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Hello"}],
                max_completion_tokens=10
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
                    self.app_logger.log_ai_response(
                        request_id, "connection_test",
                        response_data, processing_time, tokens_used,
                    )

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

    # -- AI chat mode methods ---------------------------------------------------

    def build_ai_chat_system_prompt(self, commands_description: str, calendars: str = "") -> str:
        """Build the system prompt for AI chat intent detection."""
        from datetime import datetime
        from string import Template

        template = Template(self._prompts.ai_chat_system_prompt)
        current_date = datetime.now().strftime("%d.%m.%Y")
        return template.safe_substitute(
            current_date=current_date,
            commands=commands_description,
            calendars=calendars,
        )

    def ai_chat_detect_intent(
        self, messages: list[dict[str, str]],
    ) -> str | None:
        """Phase 1: Detect user intent from conversation history.

        Returns the raw AI response text (expected JSON with command,
        parameters, follow_up_question, summary).
        """
        request_id = None
        start_time = time.time()

        try:
            logger.debug(
                "ai_chat_detect_intent: sending %d messages to model=%s",
                len(messages), self.model,
            )

            if self.app_logger:
                request_data = {"messages_count": len(messages)}
                metadata = {
                    "model": self.model,
                    "max_completion_tokens": AI_CHAT_MAX_INTENT_TOKENS,
                    "temperature": AI_CHAT_INTENT_TEMPERATURE,
                }
                request_id = self.app_logger.log_ai_request(
                    "ai_chat_intent", request_data, metadata,
                )

            logger.debug("ai_chat_detect_intent: calling OpenAI API (timeout=%ss)...", AI_CHAT_TIMEOUT)
            response = self.client.chat.completions.create(  # type: ignore[call-overload]
                model=self.model,
                messages=messages,
                max_completion_tokens=AI_CHAT_MAX_INTENT_TOKENS,
                temperature=AI_CHAT_INTENT_TEMPERATURE,
                response_format={"type": "json_object"},
                timeout=AI_CHAT_TIMEOUT,
            )
            logger.debug("ai_chat_detect_intent: API response received")

            if (
                response.choices
                and response.choices[0].message
                and response.choices[0].message.content
            ):
                content = response.choices[0].message.content.strip()
                logger.debug("AI chat intent response: %s", content)

                if self.app_logger and request_id:
                    processing_time = time.time() - start_time
                    tokens_used = {
                        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                        "total_tokens": response.usage.total_tokens if response.usage else 0,
                    }
                    self.app_logger.log_ai_response(
                        request_id, "ai_chat_intent",
                        content, processing_time, tokens_used,
                    )

                return str(content)

            logger.error("No response content from OpenAI for intent detection")
            return None

        except Exception as e:
            logger.error("Error detecting intent: %s", e, exc_info=True)
            if self.app_logger:
                if not request_id:
                    request_id = str(time.time())
                self.app_logger.log_ai_error(request_id, "ai_chat_intent", e)
            return None

    def ai_chat_validate_parameters(
        self,
        command_name: str,
        extracted_params: dict[str, Any],
        summary: str,
        tools: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Phase 2: Validate and structure parameters via function calling.

        Returns dict with 'name' and 'arguments' from the tool call,
        or None if validation fails.
        """
        request_id = None
        start_time = time.time()

        try:
            logger.debug(
                "ai_chat_validate_parameters: command=%s, params=%s",
                command_name, extracted_params,
            )

            user_content = json.dumps({
                "command": command_name,
                "parameters": extracted_params,
                "summary": summary,
            })

            messages = [
                {"role": "system", "content": self._prompts.ai_chat_function_prompt},
                {"role": "user", "content": user_content},
            ]

            if self.app_logger:
                request_data = {
                    "command": command_name,
                    "parameters": extracted_params,
                    "summary": summary,
                }
                metadata = {
                    "model": self.model,
                    "max_completion_tokens": AI_CHAT_MAX_VALIDATE_TOKENS,
                    "temperature": AI_CHAT_VALIDATE_TEMPERATURE,
                }
                request_id = self.app_logger.log_ai_request(
                    "ai_chat_validate", request_data, metadata,
                )

            logger.debug("ai_chat_validate_parameters: calling OpenAI API (timeout=%ss)...", AI_CHAT_TIMEOUT)
            response = self.client.chat.completions.create(  # type: ignore[call-overload]
                model=self.model,
                messages=messages,
                tools=tools,
                tool_choice={"type": "function", "function": {"name": command_name}},
                max_completion_tokens=AI_CHAT_MAX_VALIDATE_TOKENS,
                temperature=AI_CHAT_VALIDATE_TEMPERATURE,
                timeout=AI_CHAT_TIMEOUT,
            )
            logger.debug("ai_chat_validate_parameters: API response received")

            if (
                response.choices
                and response.choices[0].message
                and response.choices[0].message.tool_calls
            ):
                tool_call = response.choices[0].message.tool_calls[0]
                result: dict[str, Any] = {
                    "name": tool_call.function.name,
                    "arguments": json.loads(tool_call.function.arguments),
                }
                logger.debug("AI chat validate response: %s", result)

                if self.app_logger and request_id:
                    processing_time = time.time() - start_time
                    tokens_used = {
                        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                        "total_tokens": response.usage.total_tokens if response.usage else 0,
                    }
                    self.app_logger.log_ai_response(
                        request_id, "ai_chat_validate",
                        json.dumps(result), processing_time, tokens_used,
                    )

                return result

            logger.error("No tool call in OpenAI response for parameter validation")
            return None

        except Exception as e:
            logger.error("Error validating parameters: %s", e, exc_info=True)
            if self.app_logger:
                if not request_id:
                    request_id = str(time.time())
                self.app_logger.log_ai_error(
                    request_id, "ai_chat_validate", e,
                    {"command": command_name},
                )
            return None

    def ai_chat_interpret_output(
        self,
        user_question: str,
        command_output: str,
    ) -> str | None:
        """Phase 3: Interpret command output to answer the user's question.

        Returns a human-readable interpretation string, or None on failure.
        """
        request_id = None
        start_time = time.time()

        try:
            truncated_output = command_output[:AI_CHAT_MAX_OUTPUT_CHARS]

            user_content = (
                f"Original question: {user_question}\n\n"
                f"Command output:\n{truncated_output}"
            )

            messages = [
                {"role": "system", "content": self._prompts.ai_chat_interpret_prompt},
                {"role": "user", "content": user_content},
            ]

            logger.debug(
                "ai_chat_interpret_output: sending interpretation request, output_len=%d",
                len(truncated_output),
            )

            if self.app_logger:
                request_data = {
                    "user_question": user_question,
                    "output_length": len(truncated_output),
                }
                metadata = {
                    "model": self.model,
                    "max_completion_tokens": AI_CHAT_MAX_INTERPRET_TOKENS,
                    "temperature": AI_CHAT_INTERPRET_TEMPERATURE,
                }
                request_id = self.app_logger.log_ai_request(
                    "ai_chat_interpret", request_data, metadata,
                )

            response = self.client.chat.completions.create(  # type: ignore[call-overload]
                model=self.model,
                messages=messages,
                max_completion_tokens=AI_CHAT_MAX_INTERPRET_TOKENS,
                temperature=AI_CHAT_INTERPRET_TEMPERATURE,
                timeout=AI_CHAT_TIMEOUT,
            )

            if (
                response.choices
                and response.choices[0].message
                and response.choices[0].message.content
            ):
                content = response.choices[0].message.content.strip()
                logger.debug("AI chat interpret response: %s", content)

                if self.app_logger and request_id:
                    processing_time = time.time() - start_time
                    tokens_used = {
                        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                        "total_tokens": response.usage.total_tokens if response.usage else 0,
                    }
                    self.app_logger.log_ai_response(
                        request_id, "ai_chat_interpret",
                        content, processing_time, tokens_used,
                    )

                return str(content)

            logger.error("No response content from OpenAI for output interpretation")
            return None

        except Exception as e:
            logger.error("Error interpreting output: %s", e, exc_info=True)
            if self.app_logger:
                if not request_id:
                    request_id = str(time.time())
                self.app_logger.log_ai_error(request_id, "ai_chat_interpret", e)
            return None
