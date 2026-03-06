"""Per-session conversation logger for AI chat debug tracing."""

from __future__ import annotations

import logging
from datetime import date, datetime
from pathlib import Path


class ChatConversationLogger:
    """Writes every conversation step to a per-session log file.

    Each chat session gets its own file named ``yyyymmdd_chat_NN.log``
    where *NN* auto-increments based on existing files for that day.
    """

    _PREFIX = "chat"

    def __init__(self, log_dir: str = "logs") -> None:
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._next_log_path()
        self._logger = self._create_logger()

    @property
    def log_path(self) -> Path:
        """Return the path of this session's conversation log file."""
        return self._log_path

    def _next_log_path(self) -> Path:
        """Determine the next available log filename for today."""
        today = date.today().strftime("%Y%m%d")
        existing = sorted(self._log_dir.glob(f"{today}_{self._PREFIX}_*.log"))
        next_num = len(existing) + 1
        return self._log_dir / f"{today}_{self._PREFIX}_{next_num:02d}.log"

    def _create_logger(self) -> logging.Logger:
        """Create a file logger for this session."""
        logger_name = f"chat_conversation.{self._log_path.stem}"
        file_logger = logging.getLogger(logger_name)
        file_logger.setLevel(logging.DEBUG)
        file_logger.propagate = False
        file_logger.handlers.clear()

        handler = logging.FileHandler(self._log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        file_logger.addHandler(handler)
        return file_logger

    def log(self, step: str, content: str) -> None:
        """Append a timestamped step entry to the session log.

        Args:
            step: Label for the conversation step (e.g. USER, PHASE1_INTENT).
            content: The content to log for this step.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._logger.info("[%s] %s: %s", timestamp, step, content)
