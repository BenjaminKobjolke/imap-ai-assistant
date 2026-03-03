"""Shared RTM todo creation logic used by TaskProcessor and InboxZero."""

from __future__ import annotations

import logging

from src.ai.openai_client import OpenAIClient
from src.config.settings import ConfigManager
from src.email.smtp_client import SmtpClient
from src.interaction.scheduler_prompts import scheduler_ask, scheduler_confirm, send_output

logger = logging.getLogger(__name__)


class RtmTodoCreator:
    """Reusable static methods for creating and sending RTM todos."""

    @staticmethod
    def generate_todo(
        openai_client: OpenAIClient,
        subject: str,
        first_line: str,
        body_excerpt: str,
    ) -> tuple[str, str] | None:
        """AI-generate an RTM todo from email content.

        Returns (todo_text, assignee) or None on failure.
        """
        return openai_client.process_email_to_todo(subject, first_line, body_excerpt)

    @staticmethod
    def edit_todo(todo_text: str) -> str:
        """Let the user edit the generated todo text via scheduler_ask."""
        return scheduler_ask(
            f"Todo text: {todo_text}\nEdit todo (or keep as-is):",
            default=todo_text,
        )

    @staticmethod
    def resolve_extra_tags(config: ConfigManager, sender: str, subject: str) -> str:
        """Evaluate sender and keyword tag rules, return extra tags to append."""
        rules = config.get_subject_tag_rules()
        tags: list[str] = []
        sender_lower = sender.lower()
        subject_lower = subject.lower()

        for rule in rules["sender_rules"]:
            if rule["pattern"].lower() in sender_lower:
                tags.append(rule["tag"])

        for rule in rules["keyword_rules"]:
            keywords = [kw.lower() for kw in rule["keywords"]]
            match_mode = rule.get("match", "all")
            if match_mode == "all":
                if all(kw in subject_lower for kw in keywords):
                    tags.append(rule["tag"])
            elif match_mode == "any" and any(kw in subject_lower for kw in keywords):
                tags.append(rule["tag"])

        return " ".join(tags)

    @staticmethod
    def send_todo(
        smtp_client: SmtpClient,
        config: ConfigManager,
        todo_text: str,
        subject_tag: str,
        original_subject: str,
        original_sender: str,
        task_tracking_headers: dict[str, str] | None = None,
    ) -> tuple[bool, bytes | None]:
        """Send todo to RTM via SMTP. Returns (success, message_bytes)."""
        rtm_email = config.rtm_email
        if not rtm_email:
            send_output("RTM email address not configured.")
            return False, None

        return smtp_client.send_rtm_todo(
            rtm_email=rtm_email,
            todo_text=todo_text,
            subject_tag=subject_tag,
            original_subject=original_subject,
            original_sender=original_sender,
            task_tracking_headers=task_tracking_headers,
        )

    @staticmethod
    def create_and_send(
        openai_client: OpenAIClient,
        smtp_client: SmtpClient,
        config: ConfigManager,
        subject: str,
        first_line: str,
        body_excerpt: str,
        from_address: str,
        *,
        dry_run: bool = False,
    ) -> tuple[bool, str]:
        """Full interactive flow: AI generate -> edit -> confirm -> send.

        Returns (success, todo_text). Used by inbox-zero.
        """
        result = RtmTodoCreator.generate_todo(openai_client, subject, first_line, body_excerpt)
        if not result:
            send_output("Failed to generate todo.")
            return False, ""

        todo_text, _assignee = result
        todo_text = RtmTodoCreator.edit_todo(todo_text)

        rules = config.get_processing_rules("self")
        subject_tag = rules["additional_subject_tag"]

        extra = RtmTodoCreator.resolve_extra_tags(config, from_address, subject)
        if extra:
            subject_tag = f"{subject_tag} {extra}"

        if dry_run:
            send_output(f"DRY RUN: would send '{todo_text} {subject_tag}'")
            return True, todo_text

        if not scheduler_confirm(f"Send todo to RTM? [{todo_text} {subject_tag}]", default=True):
            return False, todo_text

        success, _ = RtmTodoCreator.send_todo(
            smtp_client, config, todo_text, subject_tag, subject, from_address,
        )
        if success:
            send_output("Todo sent to RTM")
        return success, todo_text
