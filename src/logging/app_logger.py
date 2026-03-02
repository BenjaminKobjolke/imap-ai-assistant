import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional
from logging.handlers import RotatingFileHandler


class ApplicationLogger:
    """Universal application logger with rotating file handler and category support."""

    def __init__(self, log_dir: str = "logs", max_bytes: int = 10485760, backup_count: int = 5):
        """
        Initialize the ApplicationLogger.

        Args:
            log_dir: Directory to store log files
            max_bytes: Maximum size of each log file in bytes (default: 10MB)
            backup_count: Number of backup files to keep
        """
        self.log_dir = Path(log_dir)
        self.max_bytes = max_bytes
        self.backup_count = backup_count
        self.loggers = {}

        # Create log directory if it doesn't exist
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Configure root logger to suppress duplicate logs
        logging.getLogger().setLevel(logging.WARNING)

    def get_logger(self, category: str) -> logging.Logger:
        """
        Get or create a logger for a specific category.

        Args:
            category: Log category (e.g., 'ai', 'email', 'system')

        Returns:
            Logger instance for the category
        """
        if category not in self.loggers:
            self._create_logger(category)
        return self.loggers[category]

    def _create_logger(self, category: str) -> None:
        """
        Create a new logger for a category with rotating file handler.

        Args:
            category: Log category name
        """
        logger_name = f"app.{category}"
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False

        # Remove existing handlers to avoid duplicates
        logger.handlers.clear()

        # Create rotating file handler
        log_file = self.log_dir / f"{category}.log"
        handler = RotatingFileHandler(
            log_file,
            maxBytes=self.max_bytes,
            backupCount=self.backup_count,
            encoding='utf-8'
        )

        # Set formatter for structured logging
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)

        logger.addHandler(handler)
        self.loggers[category] = logger

    def log_ai_request(self, request_type: str, request_data: Dict[str, Any],
                      metadata: Optional[Dict[str, Any]] = None) -> str:
        """
        Log an AI API request.

        Args:
            request_type: Type of request (e.g., 'email_to_todo', 'task_completion')
            request_data: Request payload data
            metadata: Additional metadata (model, temperature, etc.)

        Returns:
            Request ID for tracking
        """
        request_id = str(uuid.uuid4())
        logger = self.get_logger('ai')

        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'request_id': request_id,
            'type': 'request',
            'request_type': request_type,
            'data': request_data,
            'metadata': metadata or {}
        }

        logger.info(json.dumps(log_entry, ensure_ascii=False))
        return request_id

    def log_ai_response(self, request_id: str, request_type: str,
                       response_data: Any, processing_time: float = 0,
                       tokens_used: Optional[Dict[str, int]] = None) -> None:
        """
        Log an AI API response.

        Args:
            request_id: Request ID from log_ai_request
            request_type: Type of request
            response_data: Response from AI
            processing_time: Time taken to process request
            tokens_used: Token usage information
        """
        logger = self.get_logger('ai')

        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'request_id': request_id,
            'type': 'response',
            'request_type': request_type,
            'data': response_data,
            'processing_time': processing_time,
            'tokens_used': tokens_used or {}
        }

        logger.info(json.dumps(log_entry, ensure_ascii=False))

    def log_ai_error(self, request_id: str, request_type: str,
                    error: Exception, request_data: Optional[Dict[str, Any]] = None) -> None:
        """
        Log an AI API error.

        Args:
            request_id: Request ID from log_ai_request
            request_type: Type of request
            error: Exception that occurred
            request_data: Original request data
        """
        logger = self.get_logger('ai')

        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'request_id': request_id,
            'type': 'error',
            'request_type': request_type,
            'error': {
                'type': type(error).__name__,
                'message': str(error)
            },
            'request_data': request_data
        }

        logger.error(json.dumps(log_entry, ensure_ascii=False))

    def log_event(self, category: str, event_type: str, data: Any,
                 level: str = 'info', metadata: Optional[Dict[str, Any]] = None) -> None:
        """
        Log a general application event.

        Args:
            category: Log category
            event_type: Type of event
            data: Event data
            level: Log level (debug, info, warning, error, critical)
            metadata: Additional metadata
        """
        logger = self.get_logger(category)

        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'event_type': event_type,
            'data': data,
            'metadata': metadata or {}
        }

        log_method = getattr(logger, level.lower(), logger.info)
        log_method(json.dumps(log_entry, ensure_ascii=False))

    def get_log_file_path(self, category: str) -> Path:
        """
        Get the current log file path for a category.

        Args:
            category: Log category

        Returns:
            Path to the log file
        """
        return self.log_dir / f"{category}.log"

    def get_all_log_files(self, category: str) -> list:
        """
        Get all log files for a category including rotated backups.

        Args:
            category: Log category

        Returns:
            List of log file paths
        """
        log_files = []
        base_file = self.log_dir / f"{category}.log"

        # Add main log file
        if base_file.exists():
            log_files.append(base_file)

        # Add rotated files
        for i in range(1, self.backup_count + 1):
            rotated_file = self.log_dir / f"{category}.log.{i}"
            if rotated_file.exists():
                log_files.append(rotated_file)

        return log_files
