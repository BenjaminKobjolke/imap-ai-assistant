"""Self-contained todo creation and sending. Owns its own SMTP transport."""

from __future__ import annotations

import logging
import re

from src.ai.openai_client import OpenAIClient, TodoResult
from src.config.settings import ConfigManager
from src.constants import CFG_ADDITIONAL_SUBJECT_TAG
from src.email.smtp_client import SmtpClient
from src.interaction.scheduler_prompts import ask_or_accept, scheduler_ask, scheduler_choose, send_output

logger = logging.getLogger(__name__)

_FORWARDED_SENDER_PATTERN = re.compile(r"^(?:From|Von):[ \t]*(.+)$", re.MULTILINE | re.IGNORECASE)


def forwarded_senders(body: str) -> str:
    """Return the original senders quoted in a forwarded body.

    A forwarded mail arrives from the forwarder, so sender rules would
    otherwise never see who wrote it.
    """
    # ponytail: callers pass the 800-char body excerpt, enough for the forward
    # header at the top; pass the full body if deeper quoted mails must match.
    return " ".join(match.strip() for match in _FORWARDED_SENDER_PATTERN.findall(body))


class TodoService:
    """Self-contained todo creation and sending. Owns its own SMTP transport."""

    def __init__(self, config: ConfigManager) -> None:
        self._config = config
        self._smtp_client = SmtpClient(config.smtp_config)

    # ------------------------------------------------------------------
    # Static methods (no state needed)
    # ------------------------------------------------------------------

    @staticmethod
    def generate_todo(
        openai_client: OpenAIClient,
        subject: str,
        first_line: str,
        body_excerpt: str,
    ) -> TodoResult | None:
        """AI-generate an RTM todo from email content.

        Returns a TodoResult or None on failure.
        """
        return openai_client.process_email_to_todo(subject, first_line, body_excerpt)

    @staticmethod
    def edit_todo(result: TodoResult) -> TodoResult:
        """Let the user edit each todo field individually."""
        title = ask_or_accept("Title:", default=result.title)

        priority_options = [
            "1 - very important",
            "2 - important",
            "3 - not so important",
        ]
        priority_index = scheduler_choose(
            "Priority:",
            priority_options,
            default=result.priority - 1,
        )
        priority = priority_index + 1

        due_date_options = ["today", "tomorrow", "Edit"]
        default_due = next(
            (i for i, o in enumerate(due_date_options) if o == result.due_date),
            0,
        )
        due_choice = scheduler_choose(
            f"Due date: {result.due_date}",
            due_date_options,
            default=default_due,
        )
        if due_choice == 2:  # Edit
            due_date = scheduler_ask("Due date (DD.MM.YYYY):", default=result.due_date)
        else:
            due_date = due_date_options[due_choice]

        return TodoResult(
            title=title,
            priority=priority,
            due_date=due_date,
            assignee=result.assignee,
        )

    @staticmethod
    def edit_tags(subject_tag: str) -> str:
        """Let the user edit the resolved tags string."""
        return ask_or_accept("Tags:", default=subject_tag)

    # ------------------------------------------------------------------
    # Instance methods (use self._smtp_client and self._config)
    # ------------------------------------------------------------------

    def _matching_rules(self, sender: str, subject: str) -> list[dict]:
        """Return the sender and keyword rules that match, sender rules first."""
        rules = self._config.get_subject_tag_rules()
        sender_lower = sender.lower()
        subject_lower = subject.lower()

        matched = [rule for rule in rules["sender_rules"] if rule["pattern"].lower() in sender_lower]

        for rule in rules["keyword_rules"]:
            hits = [kw.lower() in subject_lower for kw in rule["keywords"]]
            match_mode = rule.get("match", "all")
            if (match_mode == "all" and all(hits)) or (match_mode == "any" and any(hits)):
                matched.append(rule)

        return matched

    def resolve_extra_tags(self, sender: str, subject: str) -> str:
        """Evaluate sender and keyword tag rules, return extra tags to append."""
        return " ".join(rule["tag"] for rule in self._matching_rules(sender, subject))

    def resolve_rule_assignee(self, sender: str, subject: str) -> str | None:
        """Return the default assignee of the first matching rule that names one."""
        for rule in self._matching_rules(sender, subject):
            if rule.get("assignee"):
                return str(rule["assignee"])
        return None

    def send_todo(
        self,
        todo_text: str,
        subject_tag: str,
        original_subject: str,
        original_sender: str,
        task_tracking_headers: dict[str, str] | None = None,
    ) -> tuple[bool, bytes | None]:
        """Send todo to RTM via SMTP. Returns (success, message_bytes)."""
        rtm_email = self._config.rtm_email
        if not rtm_email:
            send_output("RTM email address not configured.")
            return False, None

        return self._smtp_client.send_rtm_todo(
            rtm_email=rtm_email,
            todo_text=todo_text,
            subject_tag=subject_tag,
            original_subject=original_subject,
            original_sender=original_sender,
            task_tracking_headers=task_tracking_headers,
        )

    def create_and_send(
        self,
        openai_client: OpenAIClient,
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
        result = TodoService.generate_todo(openai_client, subject, first_line, body_excerpt)
        if not result:
            send_output("Failed to generate todo.")
            return False, ""

        result = TodoService.edit_todo(result)

        rules = self._config.get_processing_rules("self")
        subject_tag = rules[CFG_ADDITIONAL_SUBJECT_TAG]

        extra = self.resolve_extra_tags(from_address, subject)
        if extra:
            subject_tag = f"{subject_tag} {extra}"

        subject_tag = TodoService.edit_tags(subject_tag)

        todo_text = result.rtm_text

        if dry_run:
            send_output(f"DRY RUN: would send '{todo_text} {subject_tag}'")
            return True, todo_text

        confirm_choice = scheduler_choose(
            f"Send todo to RTM? [{todo_text} {subject_tag}]",
            ["Accept", "Abort"],
            default=0,
        )
        if confirm_choice == 1:  # Abort
            return False, todo_text

        success, _ = self.send_todo(
            todo_text, subject_tag, subject, from_address,
        )
        if success:
            send_output("Todo sent to RTM")
        return success, todo_text

    def send_direct(self, title: str, priority: int = 3, due_date: str = "today", due_time: str = "") -> bool:
        """Create and send a todo directly (no email context). Used by AI chat."""
        result = TodoResult(title=title, priority=priority, due_date=due_date, assignee="self", due_time=due_time)
        todo_text = result.rtm_text

        rules = self._config.get_processing_rules("self")
        subject_tag = rules[CFG_ADDITIONAL_SUBJECT_TAG]

        success, _ = self.send_todo(
            todo_text, subject_tag, original_subject="", original_sender="AI Chat",
        )
        if success:
            send_output(f"Todo sent: {todo_text} {subject_tag}")
        else:
            send_output("Failed to send todo to RTM.")
        return success


# Backwards-compatible alias
RtmTodoCreator = TodoService
