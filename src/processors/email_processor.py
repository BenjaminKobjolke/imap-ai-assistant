from __future__ import annotations

import logging
from pathlib import Path

from src.ai.openai_client import OpenAIClient
from src.config.settings import ConfigManager
from src.email.imap_client import EnhancedImapClient
from src.email.smtp_client import SmtpClient
from src.logging.app_logger import ApplicationLogger
from src.processors.calendar_setup import CalendarSetup
from src.processors.connection_tester import ConnectionTester
from src.processors.email_inspector import EmailInspector
from src.processors.invite_processor import InviteProcessor
from src.processors.meeting_cleanup import MeetingCleanup
from src.processors.response_processor import ResponseProcessor
from src.processors.tag_rules_wizard import TagRulesWizard
from src.processors.task_processor import TaskProcessor
from src.processors.workflow_runner import WorkflowRunner
from src.search.cache_builder import CacheBuilder
from src.search.email_search import EmailSearch

logger = logging.getLogger(__name__)


class EmailProcessor:
    """Main email processor that orchestrates the entire workflow."""

    def __init__(self, config_path: str = "settings.json", dry_run: bool = False):
        self.config = ConfigManager(config_path)
        self.dry_run = dry_run
        self.app_logger = None
        self.imap_client = None
        self.smtp_client = None
        self.openai_client = None
        self.response_processor = None
        self.task_processor = None
        self._calendar_setup = CalendarSetup(self.config)
        self._tag_wizard = TagRulesWizard(self.config)
        self._initialize_logger()
        self._initialize_clients()
        self._connection_tester = ConnectionTester(
            self.config, self.imap_client, self.smtp_client, self.openai_client,
        )
        self._workflow_runner = WorkflowRunner(
            Path(__file__).resolve().parent.parent.parent / "workflows",
            {
                "process_unread_emails": self.process_unread_emails,
                "process_assignee_responses": self.process_assignee_responses,
                "cleanup_meetings": self.cleanup_meetings,
                "todays_meetings": self.todays_meetings,
                "process_invites": self.process_invites,
            },
        )

    def _initialize_logger(self) -> None:
        """Initialize the application logger if enabled."""
        if self.config.logging_enabled:
            try:
                max_bytes = self.config.log_max_file_size_mb * 1024 * 1024  # Convert MB to bytes
                self.app_logger = ApplicationLogger(
                    log_dir=self.config.log_dir,
                    max_bytes=max_bytes,
                    backup_count=self.config.log_backup_count
                )
                # Log system startup
                self.app_logger.log_event(
                    "system",
                    "startup",
                    {"config_path": self.config.config_path},
                    level="info"
                )
            except Exception as e:
                logger.error(f"Failed to initialize application logger: {e}")
                self.app_logger = None

    def _initialize_clients(self) -> None:
        """Initialize all client instances."""
        try:
            # Validate configuration
            if not self.config.is_valid():
                logger.error("Invalid configuration. Please check settings.json")
                return

            # Initialize IMAP client for processor account (from SMTP config)
            processor_account = self.config.get_processor_account()
            if processor_account:
                self.imap_client = EnhancedImapClient(processor_account)
            else:
                logger.error("No processor account configuration found")
                return

            # Initialize SMTP client
            smtp_config = self.config.smtp_config
            if smtp_config:
                self.smtp_client = SmtpClient(smtp_config)
            else:
                logger.error("No SMTP configuration found")
                return

            # Initialize OpenAI client
            api_key = self.config.openai_api_key
            model = self.config.openai_model
            max_completion_tokens = self.config.openai_max_completion_tokens
            temperature = self.config.openai_temperature
            other_people = self.config.get_other_people_names()
            if api_key:
                self.openai_client = OpenAIClient(
                    api_key,
                    model,
                    max_completion_tokens,
                    temperature,
                    other_people,
                    app_logger=self.app_logger
                )
            else:
                logger.error("No OpenAI API key found")
                return

            # Initialize specialized processors
            self.response_processor = ResponseProcessor(self.config, self.openai_client, dry_run=self.dry_run)
            self.task_processor = TaskProcessor(self.config, self.smtp_client, self.openai_client, dry_run=self.dry_run)

        except Exception as e:
            logger.error(f"Error initializing clients: {e}")

    def process_assignee_responses(self) -> None:
        """Process responses from assignees in the main account."""
        if not self.response_processor:
            logger.error("Response processor not initialized")
            return

        self.response_processor.process_assignee_responses()

    def process_unread_emails(self) -> None:
        """Main method to process all unread emails."""
        if not all([self.imap_client, self.smtp_client, self.openai_client, self.task_processor]):
            logger.error("Clients and processors not properly initialized")
            return

        # Type guards - we know these are not None after the check above
        assert self.imap_client is not None
        assert self.smtp_client is not None
        assert self.openai_client is not None
        assert self.task_processor is not None

        try:
            logger.info("Starting email processing workflow")

            # Connect to IMAP server
            if not self.imap_client.connect():
                logger.error("Failed to connect to IMAP server")
                return

            try:
                # Get filtered unread messages
                allowed_senders = self.config.allowed_senders
                messages = self.imap_client.get_filtered_unread_messages(allowed_senders)

                if not messages:
                    logger.info("No unread messages from allowed senders found")
                    return

                logger.info(f"Processing {len(messages)} unread messages")

                # Process each message
                processed_count = 0
                failed_count = 0

                for message_id, email_message in messages:
                    try:
                        success = self.task_processor.process_single_email(self.imap_client, message_id, email_message)
                        if success:
                            processed_count += 1
                        else:
                            failed_count += 1
                    except Exception as e:
                        logger.error(f"Error processing message {message_id}: {e}")
                        failed_count += 1

                logger.info(f"Email processing completed: {processed_count} successful, {failed_count} failed")

            finally:
                # Always disconnect
                self.imap_client.disconnect()

        except Exception as e:
            logger.error(f"Error in email processing workflow: {e}")

    def inspect_folder(self, folder_name: str, use_processor_account: bool = False) -> None:
        """Inspect emails in a given IMAP folder for debugging purposes.

        Read-only: does not mark emails as read or modify anything.
        """
        # Choose account
        if use_processor_account:
            account_config = self.config.get_processor_account()
            account_label = "processor account"
        else:
            account_config = self.config.get_first_account()
            account_label = "main account"

        if not account_config:
            logger.error(f"No {account_label} configuration found")
            return

        username = account_config.get('username', 'unknown')
        logger.info(f"Inspecting folder '{folder_name}' on {account_label} ({username})")

        client = EnhancedImapClient(account_config)
        if not client.connect():
            logger.error("Failed to connect to IMAP server")
            return

        try:
            messages = client.client.get_all_messages(folder=folder_name)
            if not messages:
                logger.info(f"No messages found in folder '{folder_name}'")
                return

            # Limit to 10 most recent
            recent = messages[-10:] if len(messages) > 10 else messages
            total = len(recent)

            logger.info(f"Found {len(messages)} message(s), showing {total} most recent")
            print(f"\n{'=' * 50}")
            print(f"  Folder: {folder_name}  |  Account: {account_label}")
            print(f"  Total messages: {len(messages)}  |  Showing: {total}")
            print(f"{'=' * 50}")

            for i, (_message_id, email_message) in enumerate(recent, 1):
                try:
                    saved_path = EmailInspector.save_to_file(email_message, client)
                    EmailInspector.print_summary(i, total, email_message, client, saved_path)
                except Exception as e:
                    subject = getattr(email_message, 'subject', '?')
                    logger.error(f"Error processing email {i}/{total} '{subject}': {e}")
                    continue

            logger.info("Inspection complete. Files saved to debug/ directory.")

        except Exception as e:
            logger.error(f"Error inspecting folder '{folder_name}': {e}")
        finally:
            client.disconnect()

    def _connect_main_account(self) -> EnhancedImapClient | None:
        """Connect to the main IMAP account. Returns client or None on failure."""
        account_config = self.config.get_first_account()
        if not account_config:
            logger.error("No main account configuration found")
            return None
        client = EnhancedImapClient(account_config)
        if not client.connect():
            logger.error("Failed to connect to IMAP server")
            return None
        return client

    def cleanup_meetings(self) -> None:
        """Archive old meeting emails based on their ICS calendar date."""
        logger.info(f"Starting meeting cleanup (folder: {self.config.meetings_folder}, "
                     f"age limit: {self.config.meetings_age_limit_hours}h, "
                     f"archive: {self.config.meetings_archive_folder})")
        client = self._connect_main_account()
        if not client:
            return
        try:
            MeetingCleanup.cleanup_old_meetings(client, self.config)
        except Exception as e:
            logger.error(f"Error during meeting cleanup: {e}")
        finally:
            client.disconnect()

    # -- Calendar setup delegations --------------------------------------------------

    def setup_meetings(self) -> None:
        """Interactive setup for meeting calendar and conflict-check calendars."""
        self._calendar_setup.setup_meetings()

    def set_meeting_calendar(self, calendar_id: str) -> None:
        """Set the Google Calendar ID used for adding events."""
        self._calendar_setup.set_meeting_calendar(calendar_id)

    def set_meeting_free_check_calendar(self, calendar_id: str) -> None:
        """Add a calendar ID to the list of calendars checked for conflicts."""
        self._calendar_setup.set_meeting_free_check_calendar(calendar_id)

    def remove_meeting_free_check_calendar(self, calendar_id: str) -> None:
        """Remove a calendar ID from the conflict-check list."""
        self._calendar_setup.remove_meeting_free_check_calendar(calendar_id)

    def set_add_date_calendar(self, calendar_id: str) -> None:
        """Set the default Google Calendar ID for --add-date events."""
        self._calendar_setup.set_add_date_calendar(calendar_id)

    def add_date(self, raw_args: list[str]) -> None:
        """Create a Google Calendar event from CLI arguments."""
        self._calendar_setup.add_date(raw_args)

    def list_calendars(self) -> None:
        """List all available Google Calendars for the authenticated user."""
        self._calendar_setup.list_calendars()

    # -- Tag rules delegations ------------------------------------------------------

    def list_tag_rules(self) -> None:
        """List all subject tag rules."""
        self._tag_wizard.list_tag_rules()

    def add_sender_tag(self, pattern: str, tag: str) -> None:
        """Add a sender-based subject tag rule."""
        self._tag_wizard.add_sender_tag(pattern, tag)

    def remove_sender_tag(self, pattern: str) -> None:
        """Remove a sender-based subject tag rule."""
        self._tag_wizard.remove_sender_tag(pattern)

    def add_keyword_tag(self, tag: str, keywords: list[str], match: str = "all") -> None:
        """Add a keyword-based subject tag rule."""
        self._tag_wizard.add_keyword_tag(tag, keywords, match)

    def remove_keyword_tag(self, tag: str) -> None:
        """Remove a keyword-based subject tag rule."""
        self._tag_wizard.remove_keyword_tag(tag)

    def setup_tag_rules(self) -> None:
        """Interactive wizard to manage subject tag rules."""
        self._tag_wizard.setup_tag_rules()

    def process_invites(self) -> None:
        """Interactively process meeting invite emails with Google Calendar."""
        from src.calendar.google_calendar_client import GoogleCalendarClient

        gcal_client = GoogleCalendarClient(
            credentials_path=self.config.google_calendar_credentials_path,
            token_path=self.config.google_calendar_token_path,
            calendar_id=self.config.accepts_meetings_calendar_id,
        )
        if not gcal_client.authenticate():
            logger.error("Failed to authenticate with Google Calendar")
            return

        account_config = self.config.get_first_account()
        client = self._connect_main_account()
        if not client or not account_config:
            return
        try:
            InviteProcessor.process_invites(client, self.config, gcal_client, account_config)
        except Exception as e:
            logger.error(f"Error processing invites: {e}")
        finally:
            client.disconnect()

    def todays_meeting_detail(self, index: int) -> None:
        """Show details for a specific today's meeting by index."""
        client = self._connect_main_account()
        if not client:
            return
        try:
            MeetingCleanup.show_meeting_detail(client, self.config, index)
        except Exception as e:
            logger.error(f"Error showing meeting detail: {e}")
        finally:
            client.disconnect()

    def meetings(self, date_str: str) -> None:
        """List meetings for a given date string."""
        try:
            target_date = MeetingCleanup._parse_date(date_str)
        except ValueError as e:
            logger.error(str(e))
            return
        client = self._connect_main_account()
        if not client:
            return
        try:
            MeetingCleanup.list_todays_meetings(client, self.config, target_date=target_date)
        except Exception as e:
            logger.error(f"Error listing meetings: {e}")
        finally:
            client.disconnect()

    def todays_meetings(self) -> None:
        """List today's meetings from the meetings folder."""
        client = self._connect_main_account()
        if not client:
            return
        try:
            MeetingCleanup.list_todays_meetings(client, self.config)
        except Exception as e:
            logger.error(f"Error listing today's meetings: {e}")
        finally:
            client.disconnect()

    def test_email(self) -> None:
        """Send a test email to self and verify it arrives via IMAP."""
        self._connection_tester.test_email()

    def test_connections(self) -> bool:
        """Test all connections and configurations."""
        return self._connection_tester.test_connections()

    def get_status_summary(self) -> dict:
        """Get a summary of the current status."""
        return {
            "config_valid": self.config.is_valid(),
            "imap_initialized": self.imap_client is not None,
            "smtp_initialized": self.smtp_client is not None,
            "openai_initialized": self.openai_client is not None,
            "allowed_senders": self.config.allowed_senders,
            "target_folder": self.config.target_folder,
            "subject_tag": self.config.subject_tag,
            "openai_model": self.config.openai_model
        }

    # -- Search delegations ---------------------------------------------------------

    def search_emails(
        self,
        search_term: str,
        body_term: str | None = None,
        date: str | None = None,
        date_after: str | None = None,
        date_before: str | None = None,
        path: str | None = None,
    ) -> None:
        """Search emails using the cached index."""
        client = self._connect_main_account()
        if not client:
            return
        try:
            EmailSearch.search(
                client, self.config, search_term, body_term,
                date, date_after, date_before, path,
            )
        except Exception as e:
            logger.error(f"Error searching emails: {e}")
        finally:
            client.disconnect()

    def search_wizard(self) -> None:
        """Interactive search wizard."""
        client = self._connect_main_account()
        if not client:
            return
        try:
            EmailSearch.wizard(client, self.config)
        except Exception as e:
            logger.error(f"Error in search wizard: {e}")
        finally:
            client.disconnect()

    def update_search_cache(self, folders: str | None = None, fast: bool = False) -> None:
        """Rebuild the email search cache."""
        client = self._connect_main_account()
        if not client:
            return
        try:
            CacheBuilder.update_cache(client, self.config, folders, fast=fast)
        except Exception as e:
            logger.error(f"Error updating search cache: {e}")
        finally:
            client.disconnect()

    # -- Workflow delegations -------------------------------------------------------

    def list_workflows(self) -> None:
        """List all available workflows from the workflows directory."""
        self._workflow_runner.list_workflows()

    def run_workflow(self, name: str) -> None:
        """Load and execute a named workflow."""
        self._workflow_runner.run_workflow(name)
