from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from string import Template
from typing import Any

from openai import OpenAI

from src.ai.prompt_loader import PromptLoader
from src.ai.todo_result import (
    TodoResult,
    create_fallback_todo,
    validate_structured_todo,
)
from src.constants import (
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
class ChatCall:
    """Bundle the prompts and request settings for one OpenAI chat call."""

    operation: str
    system_prompt: str
    user_prompt: str
    request_data: dict[str, Any]
    max_completion_tokens: int
    temperature: float
    json_mode: bool = False
    error_context: dict[str, Any] | None = None


class OpenAIClient:
    """OpenAI client for processing emails into RTM todo format."""

    def __init__(
        self, api_key: str, model: str = DEFAULT_MODEL, max_completion_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE, other_people: list[str] | None = None,
        app_logger: ApplicationLogger | None = None,
    ) -> None:
        self.client = OpenAI(api_key=api_key, timeout=OPENAI_TIMEOUT)
        self.model = model
        self.max_completion_tokens = max_completion_tokens
        self.temperature = temperature
        self.other_people = other_people or []
        self.app_logger = app_logger
        self._prompts = PromptLoader()

    @staticmethod
    def _usage(response: Any) -> dict[str, int]:
        """Normalize optional API usage values for consistent logs."""
        usage = getattr(response, "usage", None)
        return {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "total_tokens": getattr(usage, "total_tokens", 0) or 0,
        }

    def _chat(self, call: ChatCall) -> str | None:
        """Log, execute, and normalize one chat completion request."""
        request_id: str | None = None
        started = time.time()
        request_data = {
            **call.request_data,
            "system_prompt": call.system_prompt[:200] + "..." if len(call.system_prompt) > 200 else call.system_prompt,
        }
        try:
            if self.app_logger:
                metadata = {
                    "model": self.model,
                    "max_completion_tokens": call.max_completion_tokens,
                    "temperature": call.temperature,
                }
                request_id = self.app_logger.log_ai_request(call.operation, request_data, metadata)

            arguments: dict[str, Any] = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": call.system_prompt},
                    {"role": "user", "content": call.user_prompt},
                ],
                "max_completion_tokens": call.max_completion_tokens,
                "temperature": call.temperature,
            }
            if call.json_mode:
                arguments["response_format"] = {"type": "json_object"}
            response = self.client.chat.completions.create(**arguments)

            content = None
            if response.choices and response.choices[0].message:
                content = response.choices[0].message.content
            if not content:
                return None

            content = content.strip()
            logger.info(f"OpenAI response: {content}")
            if self.app_logger and request_id:
                self.app_logger.log_ai_response(
                    request_id,
                    call.operation,
                    content,
                    time.time() - started,
                    self._usage(response),
                )
            return content
        except Exception as error:
            if self.app_logger:
                if not request_id:
                    request_id = str(time.time())
                self.app_logger.log_ai_error(request_id, call.operation, error, call.error_context)
            raise

    def process_email_to_todo(
        self, subject: str, first_line: str, body_excerpt: str, extra_instructions: str = "",
    ) -> TodoResult | None:
        """Convert email content into an assigned todo, falling back on errors."""
        try:
            template = Template(self._prompts.user_prompt_template)
            assignees_str = ", ".join(["self", *self.other_people])
            user_prompt = template.safe_substitute(
                subject=subject, first_line=first_line, body_excerpt=body_excerpt, assignees=assignees_str,
            )
            if extra_instructions:
                user_prompt = f"{user_prompt}\n\nAdditional instructions:\n{extra_instructions}"
            content = self._chat(ChatCall(
                operation="email_to_todo",
                system_prompt=self._prompts.system_prompt,
                user_prompt=user_prompt,
                request_data={"subject": subject, "first_line": first_line, "body_excerpt": body_excerpt,
                              "user_prompt": user_prompt},
                max_completion_tokens=self.max_completion_tokens,
                temperature=self.temperature,
                json_mode=True,
                error_context={"subject": subject},
            ))
            if content:
                try:
                    data = json.loads(content)
                    title = data.get("title", "")
                    assignee = data.get("assignee", "self")
                    validated = validate_structured_todo(
                        title, data.get("priority", 2), data.get("due_date", "tomorrow")
                    )
                    if validated:
                        clean_title, priority, due_date = validated
                        result = TodoResult(clean_title, priority, due_date, assignee)
                        logger.info("Validated todo: %s, assignee: %s", result.rtm_text, assignee)
                        return result
                    logger.warning(
                        f"Invalid structured todo from OpenAI: title={title}, "
                        f"priority={data.get('priority', 2)}, due_date={data.get('due_date', 'tomorrow')}"
                    )
                except json.JSONDecodeError as error:
                    logger.error(f"Failed to parse JSON response: {error}")
            else:
                logger.error("No response content from OpenAI")
        except Exception as error:
            logger.error(f"Error processing email with OpenAI: {error}")
        return create_fallback_todo(subject, first_line)

    def check_task_completion(self, original_task: str, assignee_response: str) -> dict[str, Any]:
        """Determine whether an assignee's response completes a task."""
        try:
            user_prompt = Template(self._prompts.task_completion_user_prompt_template).safe_substitute(
                original_task=original_task, assignee_response=assignee_response,
            )
            content = self._chat(ChatCall(
                "task_completion", self._prompts.task_completion_system_prompt, user_prompt,
                {"original_task": original_task, "assignee_response": assignee_response, "user_prompt": user_prompt},
                150, 0.3, json_mode=True, error_context={"original_task": original_task},
            ))
            if content:
                try:
                    return json.loads(content)
                except json.JSONDecodeError as error:
                    logger.error(f"Failed to parse task completion response: {error}")
                    return {KEY_STATUS: STATUS_UNCLEAR, KEY_CONFIDENCE: 1, KEY_REASON: "Failed to parse response"}
            return {KEY_STATUS: STATUS_UNCLEAR, KEY_CONFIDENCE: 1, KEY_REASON: "No response from OpenAI"}
        except Exception as error:
            logger.error(f"Error checking task completion: {error}")
            return {KEY_STATUS: STATUS_UNCLEAR, KEY_CONFIDENCE: 1, KEY_REASON: f"Error: {error!s}"}

    def generate_client_response(
        self, original_subject: str, original_content: str, assigned_task: str, assignee_response: str,
        last_sent_context: str | None = None,
    ) -> dict[str, str]:
        """Generate a client reply after an assigned task is completed."""
        fallback = {KEY_RESPONSE: "Task completed.", KEY_SUBJECT: PREFIX_REPLY + original_subject}
        try:
            user_prompt = Template(self._prompts.client_response_user_prompt_template).safe_substitute(
                original_subject=original_subject,
                original_content=original_content,
                assigned_task=assigned_task,
                assignee_response=assignee_response,
                last_sent_context=last_sent_context or "No previous email context available",
            )
            content = self._chat(ChatCall(
                "client_response", self._prompts.client_response_system_prompt, user_prompt,
                {
                    "original_subject": original_subject,
                    "original_content": (
                        original_content[:500] + "..."
                        if len(original_content) > 500
                        else original_content
                    ),
                    "assigned_task": assigned_task,
                    "assignee_response": assignee_response,
                    "last_sent_context": (
                        last_sent_context[:200] + "..."
                        if last_sent_context and len(last_sent_context) > 200
                        else last_sent_context
                    ),
                    "user_prompt": user_prompt[:500] + "..." if len(user_prompt) > 500 else user_prompt,
                },
                500, 0.7, json_mode=True, error_context={"original_subject": original_subject},
            ))
            if content:
                try:
                    return json.loads(content)
                except json.JSONDecodeError as error:
                    logger.error(f"Failed to parse client response: {error}")
            return fallback
        except Exception as error:
            logger.error(f"Error generating client response: {error}")
            return fallback

    def generate_draft_reply(
        self, original_subject: str, original_body: str, user_instruction: str, conversation_history: str,
    ) -> str | None:
        """Draft a reply using the original email and conversation context."""
        try:
            user_prompt = Template(self._prompts.draft_reply_user_prompt_template).safe_substitute(
                original_subject=original_subject, original_body=original_body, user_instruction=user_instruction,
                conversation_history=conversation_history or "(none)",
            )
            content = self._chat(ChatCall(
                "draft_reply", self._prompts.draft_reply_system_prompt, user_prompt,
                {"original_subject": original_subject, "user_instruction": user_instruction,
                 "user_prompt": user_prompt[:500] + "..."},
                500, 0.7, error_context={"original_subject": original_subject},
            ))
            if content:
                return content
            logger.error("No response content from OpenAI for draft reply")
            return None
        except Exception as error:
            logger.error(f"Error generating draft reply: {error}")
            return None

    def correct_grammar(self, body_text: str) -> str | None:
        """Correct grammar and spelling in draft text."""
        try:
            user_prompt = Template(
                self._prompts.draft_grammar_user_prompt_template
            ).safe_substitute(body_text=body_text)
            content = self._chat(ChatCall(
                "grammar_correction", self._prompts.draft_grammar_system_prompt, user_prompt,
                {"body_text": body_text[:300] + "..."}, 500, 0.1,
            ))
            if content:
                return content
            logger.error("No response content from OpenAI for grammar correction")
            return None
        except Exception as error:
            logger.error(f"Error correcting grammar: {error}")
            return None

    def detect_salutation(self, email_address: str, sent_email_bodies: str) -> dict[str, Any] | None:
        """Detect the salutation used for an email address in sent messages."""
        try:
            user_prompt = Template(self._prompts.salutation_user_prompt_template).safe_substitute(
                email_address=email_address, sent_emails=sent_email_bodies,
            )
            content = self._chat(ChatCall(
                "detect_salutation", self._prompts.salutation_system_prompt, user_prompt,
                {"email_address": email_address, "sent_emails": sent_email_bodies[:300] + "..."},
                100, 0.3, json_mode=True, error_context={"email_address": email_address},
            ))
            if content:
                try:
                    result = json.loads(content)
                    if KEY_SALUTATION in result and KEY_FORMAL in result:
                        return result
                    logger.warning(f"Salutation response missing required keys: {result}")
                    return None
                except json.JSONDecodeError as error:
                    logger.error(f"Failed to parse salutation response: {error}")
                    return None
            logger.error("No response content from OpenAI for salutation detection")
            return None
        except Exception as error:
            logger.error(f"Error detecting salutation: {error}")
            return None

    def test_connection(self) -> bool:
        """Test whether the configured OpenAI API connection can answer a short prompt."""
        request_id = None
        start_time = time.time()
        try:
            if self.app_logger:
                request_data = {"test_message": "Hello", "purpose": "connection_test"}
                metadata = {"model": self.model, "max_completion_tokens": 10}
                request_id = self.app_logger.log_ai_request("connection_test", request_data, metadata)
            response = self.client.chat.completions.create(
                model=self.model, messages=[{"role": "user", "content": "Hello"}], max_completion_tokens=10,
            )
            if response.choices:
                logger.info("OpenAI API connection test successful")
                if self.app_logger and request_id:
                    response_data = {
                        "status": "success",
                        "response": response.choices[0].message.content if response.choices[0].message else None,
                    }
                    self.app_logger.log_ai_response(
                        request_id, "connection_test", response_data, time.time() - start_time, self._usage(response),
                    )
                return True
            logger.error("OpenAI API connection test failed: No response")
            return False
        except Exception as error:
            logger.error(f"OpenAI API connection test failed: {error}")
            if self.app_logger:
                if not request_id:
                    request_id = str(time.time())
                self.app_logger.log_ai_error(request_id, "connection_test", error)
            return False
