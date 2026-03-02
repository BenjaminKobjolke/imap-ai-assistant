import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ConfigManager:
    """Configuration manager for IMAP AI Assistant."""

    def __init__(self, config_path: str = "settings.json"):
        self.config_path = config_path
        self._config = {}
        self.load_config()

    def load_config(self) -> None:
        """Load configuration from JSON file."""
        try:
            config_file = Path(self.config_path)
            if not config_file.exists():
                logger.error(f"Configuration file {self.config_path} not found")
                return

            with open(config_file, 'r', encoding='utf-8') as f:
                self._config = json.load(f)

            logger.info(f"Configuration loaded from {self.config_path}")
            self._validate_config()

        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in configuration file: {e}")
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")

    def _validate_config(self) -> None:
        """Validate required configuration sections."""
        required_sections = ["accounts", "openai", "remember_the_milk", "processing", "smtp"]
        missing_sections = [section for section in required_sections if section not in self._config]

        if missing_sections:
            logger.warning(f"Missing configuration sections: {missing_sections}")

    @property
    def accounts(self) -> List[Dict]:
        """Get IMAP account configurations."""
        return self._config.get("accounts", [])

    @property
    def openai_api_key(self) -> Optional[str]:
        """Get OpenAI API key."""
        return self._config.get("openai", {}).get("api_key")

    @property
    def openai_model(self) -> str:
        """Get OpenAI model to use."""
        return self._config.get("openai", {}).get("model", "gpt-4o")

    @property
    def openai_max_tokens(self) -> int:
        """Get OpenAI max tokens."""
        return self._config.get("openai", {}).get("max_tokens", 100)

    @property
    def openai_temperature(self) -> float:
        """Get OpenAI temperature."""
        return self._config.get("openai", {}).get("temperature", 0.3)

    @property
    def rtm_email(self) -> Optional[str]:
        """Get Remember the Milk email address."""
        return self._config.get("remember_the_milk", {}).get("email_address")

    @property
    def target_folder(self) -> str:
        """Get target folder for processed emails (default for my own tasks)."""
        return self._config.get("processing", {}).get("my_own_tasks", {}).get("target_folder", "@BKToDo")

    @property
    def subject_tag(self) -> str:
        """Get additional subject tag (default for my own tasks)."""
        return self._config.get("processing", {}).get("my_own_tasks", {}).get("additional_subject_tag", "#BKToDo")

    def get_processing_rules(self, assignee: str = "self") -> Dict[str, str]:
        """Get processing rules for a specific assignee."""
        processing = self._config.get("processing", {})

        if assignee == "self" or assignee == "me":
            rules = processing.get("my_own_tasks", {})
        else:
            # Check if this person exists in the others section
            others = processing.get("others", {})
            rules = others.get(assignee.lower(), processing.get("my_own_tasks", {}))

        return {
            "target_folder": rules.get("target_folder", "@BKToDo"),
            "additional_subject_tag": rules.get("additional_subject_tag", "#BKToDo"),
            "email_address": rules.get("email_address", ""),
            "bcc": rules.get("bcc", "")
        }

    def get_other_people_names(self) -> List[str]:
        """Get list of other people configured for task assignment."""
        others = self._config.get("processing", {}).get("others", {})
        return list(others.keys())

    @property
    def allowed_senders(self) -> List[str]:
        """Get list of allowed email senders."""
        return self._config.get("allowed_senders", [])

    @property
    def smtp_config(self) -> Dict:
        """Get SMTP configuration."""
        return self._config.get("smtp", {})

    def is_valid(self) -> bool:
        """Check if configuration is valid."""
        return (
            bool(self.accounts) and
            bool(self.openai_api_key) and
            bool(self.rtm_email) and
            bool(self.smtp_config) and
            bool(self.allowed_senders)
        )

    def get_first_account(self) -> Optional[Dict]:
        """Get the first configured account."""
        accounts = self.accounts
        return accounts[0] if accounts else None

    def get_drafts_folder(self, account_config: Optional[Dict] = None) -> str:
        """Get the drafts folder name from account configuration."""
        if account_config is None:
            account_config = self.get_first_account()

        if account_config:
            return account_config.get("drafts_folder", "Drafts")

        return "Drafts"

    def get_sent_folder(self, account_config: Optional[Dict] = None) -> str:
        """Get the sent folder name from account configuration."""
        if account_config is None:
            account_config = self.get_first_account()

        if account_config:
            return account_config.get("sent_folder", "Sent")

        return "Sent"

    def get_sent_search_limit(self) -> int:
        """Get the limit for searching sent emails (for performance)."""
        return self._config.get("sent_search_limit", 100)

    def get_processor_account(self) -> Optional[Dict]:
        """Get the processor account configuration from SMTP settings."""
        smtp_config = self.smtp_config
        if not smtp_config:
            return None

        # Create processor account config from SMTP settings
        # Note: We need to add IMAP server info for the processor account
        processor_account = {
            "name": "SUMMERA AI Processor",
            "email_address": smtp_config.get("from_email", ""),
            "server": smtp_config.get("server", ""),  # Assuming IMAP uses same server
            "username": smtp_config.get("username", ""),
            "password": smtp_config.get("password", ""),
            "port": 993,  # Standard IMAP SSL port
            "use_ssl": True
        }
        return processor_account

    def get_source_account_by_email(self, sender_email: str) -> Optional[Dict]:
        """Get source account configuration by sender email address."""
        sender_email_lower = sender_email.lower()

        for account in self.accounts:
            account_email = account.get("email_address", "").lower()
            if account_email == sender_email_lower:
                return account

        return None

    def get_all_source_accounts(self) -> List[Dict]:
        """Get all source account configurations."""
        return self.accounts

    @property
    def logging_config(self) -> Dict:
        """Get logging configuration."""
        return self._config.get("logging", {})

    @property
    def logging_enabled(self) -> bool:
        """Check if logging is enabled."""
        return self.logging_config.get("enabled", True)

    @property
    def log_dir(self) -> str:
        """Get log directory path."""
        return self.logging_config.get("log_dir", "logs")

    @property
    def log_max_file_size_mb(self) -> int:
        """Get maximum log file size in MB."""
        return self.logging_config.get("max_file_size_mb", 10)

    @property
    def log_backup_count(self) -> int:
        """Get number of backup log files to keep."""
        return self.logging_config.get("backup_count", 5)

    @property
    def meetings_folder(self) -> str:
        """Get the IMAP folder path for meeting emails."""
        return self._config.get("meetings", {}).get("folder", "Company/@Meetings")

    @property
    def meetings_age_limit_hours(self) -> int:
        """Get the age limit in hours for archiving old meetings."""
        return self._config.get("meetings", {}).get("age_limit_hours", 24)

    @property
    def meetings_archive_folder(self) -> str:
        """Get the IMAP folder path for archived meeting emails."""
        return self._config.get("meetings", {}).get("archive_folder", "Company/@OldMeetings")
