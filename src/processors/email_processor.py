from __future__ import annotations

import logging
from pathlib import Path

from src.ai.openai_client import OpenAIClient
from src.config.settings import ConfigManager
from src.email.imap_client import EnhancedImapClient
from src.email.smtp_client import SmtpClient
from src.logging.app_logger import ApplicationLogger
from src.processors.connection_tester import ConnectionTester
from src.processors.invite_processor import InviteProcessor
from src.processors.response_processor import ResponseProcessor
from src.processors.tag_rules_wizard import TagRulesWizard
from src.processors.task_processor import TaskProcessor
from src.processors.workflow_runner import WorkflowRunner
from src.services.calendar_service import CalendarServiceAI, CalendarServiceInteractive
from src.services.email_service import EmailService
from src.services.meeting_service import MeetingServiceAI, MeetingServiceInteractive

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
        self._calendar_service = CalendarServiceInteractive(self.config)
        self._meeting_service = MeetingServiceInteractive(self.config)
        self._tag_wizard = TagRulesWizard(self.config)
        self._initialize_logger()
        self._initialize_clients()
        self._email_service = EmailService(self.config, self.openai_client)
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
                "inbox_zero": self.inbox_zero,
            },
        )

    def _initialize_logger(self) -> None:
        """Initialize the application logger if enabled."""
        if self.config.logging_enabled:
            try:
                max_bytes = self.config.log_max_file_size_mb * 1024 * 1024
                self.app_logger = ApplicationLogger(
                    log_dir=self.config.log_dir,
                    max_bytes=max_bytes,
                    backup_count=self.config.log_backup_count
                )
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
            if not self.config.is_valid():
                logger.error("Invalid configuration. Please check settings.json")
                return

            processor_account = self.config.get_processor_account()
            if processor_account:
                self.imap_client = EnhancedImapClient(processor_account)
            else:
                logger.error("No processor account configuration found")
                return

            smtp_config = self.config.smtp_config
            if smtp_config:
                self.smtp_client = SmtpClient(smtp_config)
            else:
                logger.error("No SMTP configuration found")
                return

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

            self.response_processor = ResponseProcessor(self.config, self.openai_client, dry_run=self.dry_run)
            self.task_processor = TaskProcessor(self.config, self.smtp_client, self.openai_client, dry_run=self.dry_run)

        except Exception as e:
            logger.error(f"Error initializing clients: {e}")

    # -- Core email processing --------------------------------------------------

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

        assert self.imap_client is not None
        assert self.smtp_client is not None
        assert self.openai_client is not None
        assert self.task_processor is not None

        try:
            logger.info("Starting email processing workflow")

            if not self.imap_client.connect():
                logger.error("Failed to connect to IMAP server")
                return

            try:
                allowed_senders = self.config.allowed_senders
                messages = self.imap_client.get_filtered_unread_messages(allowed_senders)

                if not messages:
                    logger.info("No unread messages from allowed senders found")
                    return

                logger.info(f"Processing {len(messages)} unread messages")

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
                self.imap_client.disconnect()

        except Exception as e:
            logger.error(f"Error in email processing workflow: {e}")

    # -- Email service delegations ----------------------------------------------

    def inspect_folder(self, folder_name: str, use_processor_account: bool = False) -> None:
        """Inspect emails in a given IMAP folder for debugging purposes."""
        self._email_service.inspect_folder(folder_name, use_processor_account)

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
        self._email_service.search_emails(search_term, body_term, date, date_after, date_before, path)

    def search_wizard(self) -> None:
        """Interactive search wizard."""
        self._email_service.search_wizard()

    def update_search_cache(self, folders: str | None = None, fast: bool = False) -> None:
        """Rebuild the email search cache."""
        self._email_service.update_search_cache(folders, fast=fast)

    def update_calendar_cache(self) -> None:
        """Public wrapper: fetch and cache Google Calendar list."""
        self._email_service.update_calendar_cache()

    def list_cached_calendars(self) -> None:
        """Print cached Google Calendar names and IDs."""
        self._email_service.list_cached_calendars()

    def browse(self) -> None:
        """Interactive IMAP folder and email browser."""
        self._email_service.browse()

    # -- Meeting service delegations --------------------------------------------

    def cleanup_meetings(self) -> None:
        """Archive old meeting emails based on their ICS calendar date."""
        self._meeting_service.cleanup_meetings()

    def todays_meetings(self) -> None:
        """List today's meetings from the meetings folder and Google Calendar."""
        self._meeting_service.todays_meetings()

    def meetings(self, date_str: str) -> None:
        """List meetings for a given date string."""
        self._meeting_service.meetings(date_str)

    def todays_meeting_detail(self, index: int) -> None:
        """Show details for a specific today's meeting by index."""
        self._meeting_service.todays_meeting_detail(index)

    def process_invites(self) -> None:
        """Interactively process meeting invite emails with Google Calendar."""
        self._meeting_service.process_invites()

    # -- Calendar service delegations -------------------------------------------

    def setup_meetings(self) -> None:
        """Interactive setup for meeting calendar and conflict-check calendars."""
        self._calendar_service.setup_meetings()

    def set_meeting_calendar(self, calendar_id: str) -> None:
        """Set the Google Calendar ID used for adding events."""
        self._calendar_service.set_meeting_calendar(calendar_id)

    def set_meeting_free_check_calendar(self, calendar_id: str) -> None:
        """Add a calendar ID to the list of calendars checked for conflicts."""
        self._calendar_service.set_meeting_free_check_calendar(calendar_id)

    def remove_meeting_free_check_calendar(self, calendar_id: str) -> None:
        """Remove a calendar ID from the conflict-check list."""
        self._calendar_service.remove_meeting_free_check_calendar(calendar_id)

    def set_add_date_calendar(self, calendar_id: str) -> None:
        """Set the default Google Calendar ID for --add-date events."""
        self._calendar_service.set_add_date_calendar(calendar_id)

    def add_date(self, raw_args: list[str]) -> None:
        """Create a Google Calendar event from CLI arguments."""
        self._calendar_service.add_date(raw_args)

    def list_calendars(self) -> None:
        """List all available Google Calendars for the authenticated user."""
        self._calendar_service.list_calendars()

    # -- Tag rules delegations --------------------------------------------------

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

    # -- Inbox zero -------------------------------------------------------------

    def inbox_zero(self, *, unread_only: bool = False) -> None:
        """Interactively process INBOX emails one by one to achieve inbox zero."""
        from src.calendar.google_calendar_client import GoogleCalendarClient
        from src.processors.inbox_zero import InboxZero

        gcal_client = GoogleCalendarClient.from_config(self.config)
        if gcal_client is None:
            logger.info("Google Calendar not available — invite calendar features disabled")

        account_config = self.config.get_first_account()

        client = self._email_service._connect_main_account()
        if not client:
            return

        invite_processor = InviteProcessor(client, self.config, gcal_client, account_config)

        try:
            InboxZero.process_inbox(
                client, self.config, self.smtp_client, self.openai_client,
                dry_run=self.dry_run,
                unread_only=unread_only,
                invite_processor=invite_processor,
            )
        except Exception as e:
            logger.error(f"Error during inbox-zero: {e}")
        finally:
            client.disconnect()

    # -- Connection testing -----------------------------------------------------

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

    # -- Workflow delegations ---------------------------------------------------

    def list_workflows(self) -> None:
        """List all available workflows from the workflows directory."""
        self._workflow_runner.list_workflows()

    def run_workflow(self, name: str) -> None:
        """Load and execute a named workflow."""
        self._workflow_runner.run_workflow(name)

    # -- Todo delegation -------------------------------------------------------

    def add_todo(self, title: str, priority: int = 3, due_date: str = "today", due_time: str = "") -> None:
        """Create and send a todo directly to RTM."""
        from src.services.todo_service import TodoService
        todo_proc = TodoService(self.config)
        todo_proc.send_direct(title, priority, due_date, due_time)

    # -- AI chat delegation ----------------------------------------------------

    def ai_chat(self, initial_message: str | None = None) -> None:
        """Start the conversational AI mode for natural language commands."""
        from src.ai.chat_handler import ChatHandler, CommandExecutor
        from src.ai.command_registry import CommandRegistry

        if not self.openai_client:
            logger.error("OpenAI client not initialized")
            return

        saved_meeting = self._meeting_service
        saved_calendar = self._calendar_service
        self._meeting_service = MeetingServiceAI(self.config)
        self._calendar_service = CalendarServiceAI(self.config)
        try:
            registry = CommandRegistry()
            executor = CommandExecutor(self)
            executor.bind_to_registry(registry)
            handler = ChatHandler(
                self.openai_client, registry, executor, self.app_logger, self.config,
            )
            handler.run(initial_message=initial_message)
        finally:
            self._meeting_service = saved_meeting
            self._calendar_service = saved_calendar
