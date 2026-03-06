from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.constants import (
    CFG_ADDITIONAL_SUBJECT_TAG,
    CFG_EMAIL_ADDRESS,
    CFG_TARGET_FOLDER,
    DEFAULT_MODEL,
    DEFAULT_TEMPERATURE,
    DEFAULT_TODO_FOLDER,
    DEFAULT_TODO_TAG,
    FOLDER_DRAFTS,
    FOLDER_INBOX,
    FOLDER_SENT,
    FOLDER_TRASH,
)

logger = logging.getLogger(__name__)


class ConfigManager:
    """Configuration manager for IMAP AI Assistant."""

    def __init__(self, config_path: str = "settings.json"):
        self.config_path = config_path
        self._config: dict[str, Any] = {}
        self.load_config()

    def load_config(self) -> None:
        """Load configuration from JSON file."""
        try:
            config_file = Path(self.config_path)
            if not config_file.exists():
                logger.error(f"Configuration file {self.config_path} not found")
                return

            with open(config_file, encoding='utf-8') as f:
                self._config = json.load(f)

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
    def accounts(self) -> list[dict]:
        """Get IMAP account configurations."""
        return self._config.get("accounts", [])

    @property
    def openai_api_key(self) -> str | None:
        """Get OpenAI API key."""
        return self._config.get("openai", {}).get("api_key")

    @property
    def openai_model(self) -> str:
        """Get OpenAI model to use."""
        return self._config.get("openai", {}).get("model", DEFAULT_MODEL)

    @property
    def openai_max_completion_tokens(self) -> int:
        """Get OpenAI max completion tokens."""
        openai_cfg = self._config.get("openai", {})
        return openai_cfg.get("max_completion_tokens", openai_cfg.get("max_tokens", 100))

    @property
    def openai_temperature(self) -> float:
        """Get OpenAI temperature."""
        return self._config.get("openai", {}).get("temperature", DEFAULT_TEMPERATURE)

    @property
    def rtm_email(self) -> str | None:
        """Get Remember the Milk email address."""
        return self._config.get("remember_the_milk", {}).get("email_address")

    @property
    def target_folder(self) -> str:
        """Get target folder for processed emails (default for my own tasks)."""
        return self._config.get("processing", {}).get("my_own_tasks", {}).get(CFG_TARGET_FOLDER, DEFAULT_TODO_FOLDER)

    @property
    def subject_tag(self) -> str:
        """Get additional subject tag (default for my own tasks)."""
        return self._config.get("processing", {}).get("my_own_tasks", {}).get(CFG_ADDITIONAL_SUBJECT_TAG, DEFAULT_TODO_TAG)

    def get_processing_rules(self, assignee: str = "self") -> dict[str, str]:
        """Get processing rules for a specific assignee."""
        processing = self._config.get("processing", {})

        if assignee == "self" or assignee == "me":
            rules = processing.get("my_own_tasks", {})
        else:
            # Check if this person exists in the others section
            others = processing.get("others", {})
            rules = others.get(assignee.lower(), processing.get("my_own_tasks", {}))

        return {
            CFG_TARGET_FOLDER: rules.get(CFG_TARGET_FOLDER, DEFAULT_TODO_FOLDER),
            CFG_ADDITIONAL_SUBJECT_TAG: rules.get(CFG_ADDITIONAL_SUBJECT_TAG, DEFAULT_TODO_TAG),
            CFG_EMAIL_ADDRESS: rules.get(CFG_EMAIL_ADDRESS, ""),
            "bcc": rules.get("bcc", ""),
        }

    def get_other_people_names(self) -> list[str]:
        """Get list of other people configured for task assignment."""
        others = self._config.get("processing", {}).get("others", {})
        return list(others.keys())

    @property
    def allowed_senders(self) -> list[str]:
        """Get list of allowed email senders."""
        return self._config.get("allowed_senders", [])

    @property
    def smtp_config(self) -> dict:
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

    def get_first_account(self) -> dict | None:
        """Get the first configured account."""
        accounts = self.accounts
        return accounts[0] if accounts else None

    def get_drafts_folder(self, account_config: dict | None = None) -> str:
        """Get the drafts folder name from account configuration."""
        if account_config is None:
            account_config = self.get_first_account()

        if account_config:
            return account_config.get("drafts_folder", FOLDER_DRAFTS)

        return FOLDER_DRAFTS

    def get_sent_folder(self, account_config: dict | None = None) -> str:
        """Get the sent folder name from account configuration."""
        if account_config is None:
            account_config = self.get_first_account()

        if account_config:
            return account_config.get("sent_folder", FOLDER_SENT)

        return FOLDER_SENT

    def get_sent_search_limit(self) -> int:
        """Get the limit for searching sent emails (for performance)."""
        return self._config.get("sent_search_limit", 100)

    def get_processor_account(self) -> dict | None:
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

    def get_source_account_by_email(self, sender_email: str) -> dict | None:
        """Get source account configuration by sender email address."""
        sender_email_lower = sender_email.lower()

        for account in self.accounts:
            account_email = account.get("email_address", "").lower()
            if account_email == sender_email_lower:
                return account

        return None

    def get_all_source_accounts(self) -> list[dict]:
        """Get all source account configurations."""
        return self.accounts

    @property
    def processor_done_folder(self) -> str:
        """Get the folder to move processed emails into on the AI account.

        Empty string means don't move — just mark as read (legacy behavior).
        """
        return self._config.get("smtp", {}).get("done_folder", "")

    @property
    def processor_sent_folder(self) -> str:
        """Get the IMAP folder to archive sent messages on the AI account.

        Empty string means don't archive sent messages (disabled).
        """
        return self._config.get("smtp", {}).get("sent_folder", "")

    @property
    def logging_config(self) -> dict:
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

    # -- Chat settings ---------------------------------------------------------

    @property
    def chat_max_history(self) -> int:
        """Max conversation messages to keep in AI chat mode."""
        return self._config.get("chat", {}).get("max_history", 100)

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

    @property
    def meetings_invite_scan_folder(self) -> str:
        """Get the IMAP folder to scan for meeting invites."""
        return self._config.get("meetings", {}).get("invite_scan_folder", FOLDER_INBOX)

    @property
    def meetings_rsvp_send_directly(self) -> bool:
        """Whether to send RSVP directly via SMTP instead of saving as draft."""
        return self._config.get("meetings", {}).get("rsvp_send_directly", False)

    @property
    def google_calendar_credentials_path(self) -> str:
        """Get the path to Google Calendar OAuth credentials file."""
        return self._config.get("meetings", {}).get("google_calendar", {}).get("credentials_path", "credentials.json")

    @property
    def google_calendar_token_path(self) -> str:
        """Get the path to the stored Google Calendar OAuth token."""
        return self._config.get("meetings", {}).get("google_calendar", {}).get("token_path", "token.json")

    @property
    def accepts_meetings_calendar_id(self) -> str:
        """Get the Google Calendar ID to import events into."""
        cal = self._config.get("meetings", {}).get("google_calendar", {})
        return cal.get("accepts_meetings_calendar", {}).get("id", "primary")

    @property
    def accepts_meetings_calendar_name(self) -> str:
        """Get the display name of the calendar used for accepting meetings."""
        cal = self._config.get("meetings", {}).get("google_calendar", {})
        return cal.get("accepts_meetings_calendar", {}).get("name", "")

    @property
    def cached_calendars(self) -> list[dict[str, str]]:
        """Return cached Google Calendar list [{name, id}, ...] from SQLite."""
        from src.search.search_cache import SearchCache

        cache = SearchCache(self.search_cache_path)
        try:
            return cache.get_calendars()
        finally:
            cache.close()

    @property
    def free_check_calendars(self) -> list[dict[str, str]]:
        """Calendar entries to check for scheduling conflicts during invite processing."""
        return self._config.get("meetings", {}).get("google_calendar", {}).get("free_check_calendars", [])

    @property
    def add_date_calendar_id(self) -> str:
        """Get the Google Calendar ID for --add-date events, falling back to accepts_meetings."""
        gcal = self._config.get("meetings", {}).get("google_calendar", {})
        explicit = gcal.get("add_date_calendar", {}).get("id", "")
        return explicit or self.accepts_meetings_calendar_id

    @property
    def add_date_calendar_name(self) -> str:
        """Get the display name of the calendar for --add-date events."""
        gcal = self._config.get("meetings", {}).get("google_calendar", {})
        explicit = gcal.get("add_date_calendar", {}).get("name", "")
        return explicit or self.accepts_meetings_calendar_name

    @property
    def free_check_calendar_ids(self) -> list[str]:
        """Calendar IDs to check for scheduling conflicts."""
        return [c.get("id", "") for c in self.free_check_calendars if c.get("id")]

    def save_setting(self, key_path: list[str], value: object) -> bool:
        """Update a nested config key and persist to settings.json."""
        node = self._config
        for key in key_path[:-1]:
            node = node.setdefault(key, {})
        node[key_path[-1]] = value

        try:
            with open(Path(self.config_path), "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
            logger.info("Saved setting %s = %s", ".".join(key_path), value)
            return True
        except Exception as e:
            logger.error("Failed to save setting: %s", e)
            return False

    def get_subject_tag_rules(self) -> dict:
        """Get subject tag rules configuration."""
        rules = self._config.get("processing", {}).get("subject_tag_rules", {})
        return {
            "sender_rules": rules.get("sender_rules", []),
            "keyword_rules": rules.get("keyword_rules", []),
        }

    def add_sender_tag_rule(self, pattern: str, tag: str) -> None:
        """Add a sender-based subject tag rule."""
        rules = self._config.setdefault("processing", {}).setdefault("subject_tag_rules", {})
        sender_rules = rules.setdefault("sender_rules", [])

        for rule in sender_rules:
            if rule["pattern"].lower() == pattern.lower():
                rule["tag"] = tag
                logger.info(f"Updated sender tag rule: {pattern} -> {tag}")
                self._save_config()
                return

        sender_rules.append({"pattern": pattern, "tag": tag})
        logger.info(f"Added sender tag rule: {pattern} -> {tag}")
        self._save_config()

    def remove_sender_tag_rule(self, pattern: str) -> bool:
        """Remove a sender-based subject tag rule by pattern."""
        rules = self._config.get("processing", {}).get("subject_tag_rules", {})
        sender_rules = rules.get("sender_rules", [])

        for i, rule in enumerate(sender_rules):
            if rule["pattern"].lower() == pattern.lower():
                sender_rules.pop(i)
                logger.info(f"Removed sender tag rule: {pattern}")
                self._save_config()
                return True

        logger.warning(f"Sender tag rule not found: {pattern}")
        return False

    def add_keyword_tag_rule(self, keywords: list[str], tag: str, match: str = "all") -> None:
        """Add a keyword-based subject tag rule."""
        rules = self._config.setdefault("processing", {}).setdefault("subject_tag_rules", {})
        keyword_rules = rules.setdefault("keyword_rules", [])

        for rule in keyword_rules:
            if rule["tag"] == tag:
                rule["keywords"] = keywords
                rule["match"] = match
                logger.info(f"Updated keyword tag rule: {tag} (keywords: {keywords}, match: {match})")
                self._save_config()
                return

        keyword_rules.append({"keywords": keywords, "tag": tag, "match": match})
        logger.info(f"Added keyword tag rule: {tag} (keywords: {keywords}, match: {match})")
        self._save_config()

    def remove_keyword_tag_rule(self, tag: str) -> bool:
        """Remove a keyword-based subject tag rule by tag."""
        rules = self._config.get("processing", {}).get("subject_tag_rules", {})
        keyword_rules = rules.get("keyword_rules", [])

        for i, rule in enumerate(keyword_rules):
            if rule["tag"] == tag:
                keyword_rules.pop(i)
                logger.info(f"Removed keyword tag rule: {tag}")
                self._save_config()
                return True

        logger.warning(f"Keyword tag rule not found: {tag}")
        return False

    def list_tag_rules(self) -> None:
        """Print all subject tag rules to console."""
        rules = self.get_subject_tag_rules()
        sender_rules = rules["sender_rules"]
        keyword_rules = rules["keyword_rules"]

        if not sender_rules and not keyword_rules:
            logger.info("No subject tag rules configured.")
            return

        if sender_rules:
            logger.info("Sender rules:")
            for rule in sender_rules:
                logger.info(f"  {rule['pattern']} -> {rule['tag']}")

        if keyword_rules:
            logger.info("Keyword rules:")
            for rule in keyword_rules:
                keywords_str = ", ".join(rule["keywords"])
                match_mode = rule.get("match", "all")
                logger.info(f"  [{match_mode}] ({keywords_str}) -> {rule['tag']}")

    def _save_config(self) -> None:
        """Persist the current config to settings.json."""
        try:
            with open(Path(self.config_path), "w", encoding="utf-8") as f:
                json.dump(self._config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    @property
    def download_folder(self) -> Path:
        """Get the folder path for downloading email attachments."""
        return Path(self._config.get("download_folder", "downloads"))

    @property
    def trash_folder(self) -> str:
        """Get the IMAP trash folder path."""
        return self._config.get("trash_folder", FOLDER_TRASH)

    @property
    def search_results_folder(self) -> str:
        """IMAP folder to copy search results into."""
        return self._config.get("search", {}).get("results_folder", "search-results")

    @property
    def search_cache_validity_days(self) -> int:
        """How many days before cached data is considered stale."""
        return self._config.get("search", {}).get("cache_validity_days", 30)

    @property
    def search_cache_path(self) -> Path:
        """Path to the SQLite search cache database."""
        return Path(self._config.get("search", {}).get("cache_db", "data/cache.db"))

    @property
    def search_exclude_folders(self) -> list[str]:
        """Folder names to exclude from search and cache building."""
        search = self._config.get("search", {})
        return search.get("exclude_folders", search.get("cache_exclude_folders", []))

    @property
    def search_live_folders(self) -> list[str]:
        """Folder names that are always searched live via IMAP, never from cache."""
        return self._config.get("search", {}).get("live_folders", [FOLDER_INBOX])

    def get_account_smtp_config(self, account_config: dict | None = None) -> dict | None:
        """Get SMTP configuration from a specific account entry.

        Falls back to the global smtp config if the account has no SMTP settings.
        """
        if account_config is None:
            account_config = self.get_first_account()

        if not account_config:
            return self.smtp_config or None

        smtp_server = account_config.get("smtp_server")
        if not smtp_server:
            return self.smtp_config or None

        return {
            "server": smtp_server,
            "port": account_config.get("smtp_port", 587),
            "use_tls": account_config.get("smtp_use_tls", True),
            "username": account_config.get("smtp_username", account_config.get("username", "")),
            "password": account_config.get("smtp_password", account_config.get("password", "")),
            "from_email": account_config.get("email_address", ""),
        }
