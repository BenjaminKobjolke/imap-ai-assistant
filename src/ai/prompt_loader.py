from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


class PromptLoader:
    """Loads and stores AI prompt templates from the prompts/ directory."""

    def __init__(self) -> None:
        self.system_prompt = ""
        self.user_prompt_template = ""
        self.task_completion_system_prompt = ""
        self.task_completion_user_prompt_template = ""
        self.client_response_system_prompt = ""
        self.client_response_user_prompt_template = ""
        self._load()

    def _load(self) -> None:
        """Load all prompt templates from files."""
        try:
            current_date = datetime.now().strftime("%d.%m.%Y")

            self.system_prompt = self._read_required(
                "prompts/system_prompt.txt",
            ).format(current_date=current_date)

            self.user_prompt_template = self._read_required(
                "prompts/user_prompt.txt",
            )

            self.task_completion_system_prompt = self._read_optional(
                "prompts/task_completion_system_prompt.txt",
            )
            self.task_completion_user_prompt_template = self._read_optional(
                "prompts/task_completion_user_prompt.txt",
            )
            self.client_response_system_prompt = self._read_optional(
                "prompts/client_response_system_prompt.txt",
            )
            self.client_response_user_prompt_template = self._read_optional(
                "prompts/client_response_user_prompt.txt",
            )

        except Exception as e:
            logger.error(f"Error loading prompts: {e}")
            exit(1)

    def _read_required(self, path: str) -> str:
        """Read a required prompt file, exiting on failure."""
        p = Path(path)
        if not p.exists():
            logger.warning(f"Required prompt file not found: {path}")
            exit(1)
        with open(p, encoding="utf-8") as f:
            content = f.read().strip()
        logger.debug(f"Loaded prompt: {path}")
        return content

    def _read_optional(self, path: str) -> str:
        """Read an optional prompt file, returning empty string if missing."""
        p = Path(path)
        if not p.exists():
            return ""
        with open(p, encoding="utf-8") as f:
            content = f.read().strip()
        logger.debug(f"Loaded prompt: {path}")
        return content
