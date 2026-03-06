"""Tests for ChatErrorLogger per-session error logging."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from src.logging.chat_error_logger import ChatErrorLogger


class TestLogFileName:
    """Tests for session log file naming."""

    def test_creates_log_file_with_correct_name(self, tmp_path: Path) -> None:
        """First session of the day produces _01 suffix."""
        error_logger = ChatErrorLogger(str(tmp_path))
        today = date.today().strftime("%Y%m%d")
        assert error_logger.log_path.name == f"{today}_chat_error_01.log"
        assert error_logger.log_path.parent == tmp_path

    def test_increments_sequence_number(self, tmp_path: Path) -> None:
        """Second session of the day produces _02 suffix."""
        today = date.today().strftime("%Y%m%d")
        # Create a pre-existing log file for today
        (tmp_path / f"{today}_chat_error_01.log").touch()

        error_logger = ChatErrorLogger(str(tmp_path))
        assert error_logger.log_path.name == f"{today}_chat_error_02.log"

    def test_creates_log_directory(self, tmp_path: Path) -> None:
        """Logger creates the log directory if it does not exist."""
        nested = tmp_path / "sub" / "logs"
        ChatErrorLogger(str(nested))
        assert nested.is_dir()


class TestLogError:
    """Tests for the log_error method."""

    def test_writes_json_entry(self, tmp_path: Path) -> None:
        """log_error writes a valid JSON line to the file."""
        error_logger = ChatErrorLogger(str(tmp_path))
        error_logger.log_error(
            command_name="add_date",
            parameters={"title": "Meeting"},
            error="Unrecognised argument: today",
        )

        content = error_logger.log_path.read_text(encoding="utf-8").strip()
        entry = json.loads(content)
        assert entry["command"] == "add_date"
        assert entry["parameters"] == {"title": "Meeting"}
        assert entry["error"] == "Unrecognised argument: today"

    def test_includes_timestamp(self, tmp_path: Path) -> None:
        """Log entry contains an ISO-format timestamp."""
        error_logger = ChatErrorLogger(str(tmp_path))
        error_logger.log_error(
            command_name="search",
            parameters={"search_term": "test"},
            error="connection timeout",
        )

        content = error_logger.log_path.read_text(encoding="utf-8").strip()
        entry = json.loads(content)
        assert "timestamp" in entry
        # Should be parseable as ISO format
        assert "T" in entry["timestamp"]

    def test_includes_traceback_when_provided(self, tmp_path: Path) -> None:
        """Traceback field is present when explicitly passed."""
        error_logger = ChatErrorLogger(str(tmp_path))
        error_logger.log_error(
            command_name="add_date",
            parameters={},
            error="boom",
            traceback="Traceback (most recent call last):\n  File ...",
        )

        content = error_logger.log_path.read_text(encoding="utf-8").strip()
        entry = json.loads(content)
        assert "traceback" in entry
        assert "most recent call last" in entry["traceback"]

    def test_omits_traceback_when_not_provided(self, tmp_path: Path) -> None:
        """Traceback field is absent when not passed."""
        error_logger = ChatErrorLogger(str(tmp_path))
        error_logger.log_error(
            command_name="add_date",
            parameters={},
            error="silent fail",
        )

        content = error_logger.log_path.read_text(encoding="utf-8").strip()
        entry = json.loads(content)
        assert "traceback" not in entry

    def test_multiple_errors_append(self, tmp_path: Path) -> None:
        """Multiple log_error calls produce multiple JSON lines."""
        error_logger = ChatErrorLogger(str(tmp_path))
        error_logger.log_error(command_name="a", parameters={}, error="err1")
        error_logger.log_error(command_name="b", parameters={}, error="err2")

        lines = error_logger.log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["command"] == "a"
        assert json.loads(lines[1])["command"] == "b"
