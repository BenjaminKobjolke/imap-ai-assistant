"""Per-session error logger for AI chat command failures."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any


class ChatErrorLogger:
    """Writes command errors to a per-session log file.

    Each chat session gets its own file named ``yyyymmdd_chat_error_NN.log``
    where *NN* auto-increments based on existing files for that day.
    """

    _PREFIX = "chat_error"

    def __init__(self, log_dir: str = "logs") -> None:
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._log_path = self._next_log_path()
        self._logger = self._create_logger()

    @property
    def log_path(self) -> Path:
        """Return the path of this session's error log file."""
        return self._log_path

    def _next_log_path(self) -> Path:
        """Determine the next available log filename for today."""
        today = date.today().strftime("%Y%m%d")
        existing = sorted(self._log_dir.glob(f"{today}_{self._PREFIX}_*.log"))
        next_num = len(existing) + 1
        return self._log_dir / f"{today}_{self._PREFIX}_{next_num:02d}.log"

    def _create_logger(self) -> logging.Logger:
        """Create a file logger for this session."""
        logger_name = f"chat_error.{self._log_path.stem}"
        file_logger = logging.getLogger(logger_name)
        file_logger.setLevel(logging.DEBUG)
        file_logger.propagate = False
        file_logger.handlers.clear()

        handler = logging.FileHandler(self._log_path, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        file_logger.addHandler(handler)
        return file_logger

    def log_error(
        self,
        command_name: str,
        parameters: dict[str, Any],
        error: str,
        traceback: str | None = None,
    ) -> None:
        """Append a structured error entry to the session log.

        Args:
            command_name: Name of the command that failed.
            parameters: Parameters passed to the command.
            error: Human-readable error description.
            traceback: Optional Python traceback string.
        """
        entry: dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "command": command_name,
            "parameters": parameters,
            "error": error,
        }
        if traceback:
            entry["traceback"] = traceback

        self._logger.error(json.dumps(entry, ensure_ascii=False))
