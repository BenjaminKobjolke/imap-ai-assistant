from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from email.utils import parseaddr
from typing import Any

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
        """Assemble the structured result in Remember The Milk's todo format."""
        time_part = f" {self.due_time}" if self.due_time else ""
        return f"{self.title} !{self.priority} ^{self.due_date}{time_part}"


def validate_structured_todo(
    title: str | Any, priority: int | Any, due_date: str | Any,
) -> tuple[str, int, str] | None:
    """Reject malformed structured values before creating a todo."""
    try:
        if not isinstance(title, str) or not title.strip():
            logger.debug("Structured todo validation failed: empty or non-string title")
            return None
        clean_title = title.strip()

        try:
            clean_priority = int(priority)
        except (TypeError, ValueError):
            logger.debug(f"Structured todo validation failed: invalid priority={priority}")
            return None
        if clean_priority not in (1, 2, 3):
            logger.debug(f"Structured todo validation failed: priority={clean_priority} not in 1-3")
            return None

        if not isinstance(due_date, str) or not due_date.strip():
            logger.debug("Structured todo validation failed: empty or non-string due_date")
            return None
        clean_due_date = due_date.strip()
        due_date_pattern = r"^(today|tomorrow|\d{1,2}\.\d{1,2}\.\d{4})$"
        if not re.match(due_date_pattern, clean_due_date):
            logger.debug(f"Structured todo validation failed: due_date={clean_due_date} invalid format")
            return None
        return clean_title, clean_priority, clean_due_date
    except Exception as error:
        logger.debug(f"Error validating structured todo: {error}")
        return None


def create_fallback_todo(subject: str, first_line: str, sender: str = "") -> TodoResult:
    """Create a safe default todo when AI output cannot be used."""
    todo_name = subject or first_line or "Unknown task"
    todo_name = re.sub(r"^(Re:|Fwd?:|AW:)\s*", "", todo_name, flags=re.IGNORECASE).strip()
    if sender and "xida" not in sender.lower():
        sender_name = extract_sender_name(sender)
        if sender_name:
            todo_name = f"{sender_name}: {todo_name}"
    if len(todo_name) > 50:
        todo_name = todo_name[:50] + "..."
    result = TodoResult(title=todo_name, priority=2, due_date="tomorrow", assignee="self")
    logger.info(f"Created fallback todo: {result.rtm_text}")
    return result


def extract_sender_name(sender: str) -> str:
    """Get a readable sender label from an email address or display name."""
    try:
        name, email_addr = parseaddr(sender)
        if name and name.strip():
            return name.strip()
        if email_addr:
            if "@" in email_addr:
                domain = email_addr.split("@")[1].split(".")[0]
                return domain.title()
            return email_addr
        return sender
    except Exception as error:
        logger.debug(f"Error extracting sender name from '{sender}': {error}")
        return sender
