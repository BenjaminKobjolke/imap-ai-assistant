"""Builds time-of-day greetings from SalutationInfo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from src.constants import GREETING_DEFAULT, GREETING_MORNING, GREETING_MORNING_HOUR_LIMIT


@dataclass
class SalutationInfo:
    """Cached or resolved salutation for a recipient."""

    email_address: str
    salutation: str
    is_formal: bool
    skip_greeting: bool


class GreetingBuilder:
    """Constructs a greeting line from SalutationInfo and time of day."""

    @staticmethod
    def build_greeting(salutation_info: SalutationInfo, now: datetime | None = None) -> str:
        """Return a greeting string, or empty string if greeting is skipped."""
        if salutation_info.skip_greeting:
            return ""

        if now is None:
            now = datetime.now()

        prefix = GREETING_MORNING if now.hour < GREETING_MORNING_HOUR_LIMIT else GREETING_DEFAULT

        if salutation_info.salutation:
            return f"{prefix} {salutation_info.salutation}"
        return prefix
