from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from pathlib import Path

from src.config.settings import ConfigManager
from src.email.imap_client import EnhancedImapClient
from src.email.smtp_client import SmtpClient
from src.ai.openai_client import OpenAIClient
from src.processors.response_processor import ResponseProcessor
from src.processors.task_processor import TaskProcessor
from src.processors.email_inspector import EmailInspector
from src.processors.invite_processor import InviteProcessor
from src.processors.meeting_cleanup import MeetingCleanup
from src.logging.app_logger import ApplicationLogger

logger = logging.getLogger(__name__)


class EmailProcessor:
    """Main email processor that orchestrates the entire workflow."""

    def __init__(self, config_path: str = "settings.json"):
        self.config = ConfigManager(config_path)
        self.app_logger = None
        self.imap_client = None
        self.smtp_client = None
        self.openai_client = None
        self.response_processor = None
        self.task_processor = None
        self._initialize_logger()
        self._initialize_clients()

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
                logger.info(f"Application logger initialized with directory: {self.config.log_dir}")

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
            max_tokens = self.config.openai_max_tokens
            temperature = self.config.openai_temperature
            other_people = self.config.get_other_people_names()
            if api_key:
                self.openai_client = OpenAIClient(
                    api_key,
                    model,
                    max_tokens,
                    temperature,
                    other_people,
                    app_logger=self.app_logger
                )
            else:
                logger.error("No OpenAI API key found")
                return

            # Initialize specialized processors
            self.response_processor = ResponseProcessor(self.config, self.openai_client)
            self.task_processor = TaskProcessor(self.config, self.smtp_client, self.openai_client)

            logger.info("All clients and processors initialized successfully")

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

            for i, (message_id, email_message) in enumerate(recent, 1):
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

    def cleanup_meetings(self) -> None:
        """Archive old meeting emails based on their ICS calendar date."""
        account_config = self.config.get_first_account()
        if not account_config:
            logger.error("No main account configuration found")
            return

        logger.info(f"Starting meeting cleanup (folder: {self.config.meetings_folder}, "
                     f"age limit: {self.config.meetings_age_limit_hours}h, "
                     f"archive: {self.config.meetings_archive_folder})")

        client = EnhancedImapClient(account_config)
        if not client.connect():
            logger.error("Failed to connect to IMAP server")
            return

        try:
            MeetingCleanup.cleanup_old_meetings(client, self.config)
        except Exception as e:
            logger.error(f"Error during meeting cleanup: {e}")
        finally:
            client.disconnect()

    def setup_meetings(self) -> None:
        """Interactive setup for meeting calendar and conflict-check calendars."""
        from src.calendar.google_calendar_client import GoogleCalendarClient

        gcal_client = GoogleCalendarClient(
            credentials_path=self.config.google_calendar_credentials_path,
            token_path=self.config.google_calendar_token_path,
            calendar_id=self.config.google_calendar_id,
        )
        if not gcal_client.authenticate():
            logger.error("Failed to authenticate with Google Calendar")
            return

        calendars = gcal_client.list_calendars()
        if not calendars:
            print("No calendars found.")
            return

        cal_names = {c.get("id", ""): c.get("summary", "(unnamed)") for c in calendars}

        selected_calendar = self._setup_meeting_calendar(calendars, cal_names)
        selected_checks = self._setup_free_check_calendars(calendars, cal_names)

        print("\nSetup complete.")
        print(f"  Meeting calendar: {cal_names.get(selected_calendar, selected_calendar)}")
        if selected_checks:
            names = ", ".join(cal_names.get(c, c) for c in selected_checks)
            print(f"  Conflict-check:   {names}")
        else:
            print("  Conflict-check:   (none)")

    def _setup_meeting_calendar(self, calendars: list[dict], cal_names: dict[str, str]) -> str:
        """Step 1: Let the user pick the calendar for adding events."""
        current_id = self.config.google_calendar_id
        current_name = cal_names.get(current_id, current_id)

        print("\nMeeting Calendar")
        print(f"Current: {current_name} ({current_id})")
        print()

        for i, cal in enumerate(calendars, 1):
            cal_id = cal.get("id", "")
            name = cal.get("summary", "(unnamed)")
            marker = " <-- active" if cal_id == current_id else ""
            print(f"  {i}. {name} -- {cal_id}{marker}")

        print("\nPick a number to change, or press Enter to keep current:")

        while True:
            choice = input("  > ").strip()
            if choice == "":
                return current_id
            if choice.isdigit() and 1 <= int(choice) <= len(calendars):
                selected = calendars[int(choice) - 1]
                new_id = selected["id"]
                self.config.save_setting(["meetings", "google_calendar", "calendar_id"], new_id)
                print(f"  Saved: {selected.get('summary', '')} ({new_id})")
                return new_id
            print("  Invalid choice. Try again.")

    def _setup_free_check_calendars(self, calendars: list[dict], cal_names: dict[str, str]) -> list[str]:
        """Step 2: Let the user toggle which calendars are checked for conflicts."""
        current_checks = set(self.config.free_check_calendars)

        print("\nConflict-Check Calendars")

        while True:
            if current_checks:
                names = ", ".join(cal_names.get(c, c) for c in current_checks)
                print(f"Currently checked: {names}")
            else:
                print("Currently checked: (none)")
            print()

            for i, cal in enumerate(calendars, 1):
                cal_id = cal.get("id", "")
                name = cal.get("summary", "(unnamed)")
                checked = "x" if cal_id in current_checks else " "
                print(f"  {i}. [{checked}] {name} -- {cal_id}")

            print("\nToggle a number, or press Enter when done:")

            choice = input("  > ").strip()
            if choice == "":
                result = list(current_checks)
                self.config.save_setting(
                    ["meetings", "google_calendar", "free_check_calendars"], result,
                )
                return result
            if choice.isdigit() and 1 <= int(choice) <= len(calendars):
                cal_id = calendars[int(choice) - 1].get("id", "")
                if cal_id in current_checks:
                    current_checks.discard(cal_id)
                else:
                    current_checks.add(cal_id)
                print()
            else:
                print("  Invalid input. Enter a single number.\n")

    def set_meeting_calendar(self, calendar_id: str) -> None:
        """Set the Google Calendar ID used for adding events."""
        if self.config.save_setting(["meetings", "google_calendar", "calendar_id"], calendar_id):
            print(f"Meeting calendar set to: {calendar_id}")
        else:
            print("Failed to save setting.")

    def set_meeting_free_check_calendar(self, calendar_id: str) -> None:
        """Add a calendar ID to the list of calendars checked for conflicts."""
        calendars = list(self.config.free_check_calendars)
        if calendar_id in calendars:
            print(f"Calendar already in free-check list: {calendar_id}")
            return
        calendars.append(calendar_id)
        if self.config.save_setting(["meetings", "google_calendar", "free_check_calendars"], calendars):
            print(f"Added to free-check calendars: {calendar_id}")
        else:
            print("Failed to save setting.")

    def remove_meeting_free_check_calendar(self, calendar_id: str) -> None:
        """Remove a calendar ID from the list of calendars checked for conflicts."""
        calendars = list(self.config.free_check_calendars)
        if calendar_id not in calendars:
            print(f"Calendar not in free-check list: {calendar_id}")
            return
        calendars.remove(calendar_id)
        if self.config.save_setting(["meetings", "google_calendar", "free_check_calendars"], calendars):
            print(f"Removed from free-check calendars: {calendar_id}")
        else:
            print("Failed to save setting.")

    def list_calendars(self) -> None:
        """List all available Google Calendars for the authenticated user."""
        from src.calendar.google_calendar_client import GoogleCalendarClient

        gcal_client = GoogleCalendarClient(
            credentials_path=self.config.google_calendar_credentials_path,
            token_path=self.config.google_calendar_token_path,
            calendar_id=self.config.google_calendar_id,
        )
        if not gcal_client.authenticate():
            logger.error("Failed to authenticate with Google Calendar")
            return

        calendars = gcal_client.list_calendars()
        if not calendars:
            print("No calendars found.")
            return

        configured = self.config.google_calendar_id
        print(f"\nConfigured calendar_id: {configured}\n")
        print(f"{'#':<4} {'Name':<40} {'ID':<50} {'Primary'}")
        print("-" * 100)
        for i, cal in enumerate(calendars, 1):
            summary = cal.get("summary", "(unnamed)")
            cal_id = cal.get("id", "")
            primary = "yes" if cal.get("primary") else ""
            marker = " <-- active" if cal_id == configured else ""
            print(f"{i:<4} {summary:<40} {cal_id:<50} {primary}{marker}")

    def process_invites(self) -> None:
        """Interactively process meeting invite emails with Google Calendar."""
        account_config = self.config.get_first_account()
        if not account_config:
            logger.error("No main account configuration found")
            return

        from src.calendar.google_calendar_client import GoogleCalendarClient

        gcal_client = GoogleCalendarClient(
            credentials_path=self.config.google_calendar_credentials_path,
            token_path=self.config.google_calendar_token_path,
            calendar_id=self.config.google_calendar_id,
        )
        if not gcal_client.authenticate():
            logger.error("Failed to authenticate with Google Calendar")
            return

        client = EnhancedImapClient(account_config)
        if not client.connect():
            logger.error("Failed to connect to IMAP server")
            return

        try:
            InviteProcessor.process_invites(
                client, self.config, gcal_client, account_config,
            )
        except Exception as e:
            logger.error(f"Error processing invites: {e}")
        finally:
            client.disconnect()

    def todays_meeting_detail(self, index: int) -> None:
        """Show details for a specific today's meeting by index."""
        account_config = self.config.get_first_account()
        if not account_config:
            logger.error("No main account configuration found")
            return

        client = EnhancedImapClient(account_config)
        if not client.connect():
            logger.error("Failed to connect to IMAP server")
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

        account_config = self.config.get_first_account()
        if not account_config:
            logger.error("No main account configuration found")
            return

        client = EnhancedImapClient(account_config)
        if not client.connect():
            logger.error("Failed to connect to IMAP server")
            return

        try:
            MeetingCleanup.list_todays_meetings(client, self.config, target_date=target_date)
        except Exception as e:
            logger.error(f"Error listing meetings: {e}")
        finally:
            client.disconnect()

    def todays_meetings(self) -> None:
        """List today's meetings from the meetings folder."""
        account_config = self.config.get_first_account()
        if not account_config:
            logger.error("No main account configuration found")
            return

        client = EnhancedImapClient(account_config)
        if not client.connect():
            logger.error("Failed to connect to IMAP server")
            return

        try:
            MeetingCleanup.list_todays_meetings(client, self.config)
        except Exception as e:
            logger.error(f"Error listing today's meetings: {e}")
        finally:
            client.disconnect()

    def test_email(self) -> None:
        """Send a test email to self and verify it arrives via IMAP."""
        account_config = self.config.get_first_account()
        if not account_config:
            print("SEND: ERROR - No main account configuration found")
            return

        email_address = account_config.get("email_address", "")
        if not email_address:
            print("SEND: ERROR - No email_address configured for the first account")
            return

        smtp_cfg = self.config.get_account_smtp_config(account_config)
        if not smtp_cfg:
            print("SEND: ERROR - No SMTP configuration available for the first account")
            return

        smtp_client = SmtpClient(smtp_cfg)
        marker = f"IMAP-AI-Assistant-Test-{datetime.now().strftime('%Y%m%d%H%M%S')}"

        # Step 1: Send test email
        print(f"SEND: Sending test email to {email_address} ...")
        try:
            smtp_client.send_email(
                to_email=email_address,
                subject=marker,
                body="This is an automated test email from IMAP AI Assistant.",
                from_email=smtp_cfg.get("from_email", ""),
            )
            print("SEND: OK")
        except Exception as e:
            print(f"SEND: ERROR - {e}")
            return

        # Step 2: Connect IMAP and poll for arrival
        print("RECEIVE: Connecting to IMAP ...")
        client = EnhancedImapClient(account_config)
        if not client.connect():
            print("RECEIVE: ERROR - Failed to connect to IMAP server")
            return

        try:
            max_attempts = 5
            poll_interval = 3
            for attempt in range(1, max_attempts + 1):
                time.sleep(poll_interval)
                print(f"RECEIVE: Checking for test email (attempt {attempt}/{max_attempts}) ...")
                messages = client.client.get_messages(
                    search_criteria=["UNSEEN", "SUBJECT", marker],
                    folder="INBOX",
                )
                if messages:
                    msg_id = messages[0][0]
                    client.client.delete_message(msg_id)
                    print("RECEIVE: OK")
                    return

            print(
                "RECEIVE: ERROR - Test email was sent but could not be found in INBOX. "
                "Check IMAP settings or allow more delivery time."
            )
        finally:
            client.disconnect()

    def test_connections(self) -> bool:
        """Test all connections and configurations."""
        logger.info("Testing all connections...")

        all_good = True

        # Test configuration
        if not self.config.is_valid():
            logger.error("❌ Configuration validation failed")
            all_good = False
        else:
            logger.info("✅ Configuration is valid")

        # Test IMAP connection
        if self.imap_client:
            if self.imap_client.connect():
                logger.info("✅ IMAP connection successful")
                self.imap_client.disconnect()
            else:
                logger.error("❌ IMAP connection failed")
                all_good = False
        else:
            logger.error("❌ IMAP client not initialized")
            all_good = False

        # Test SMTP connection
        if self.smtp_client:
            if self.smtp_client.test_connection():
                logger.info("✅ SMTP connection successful")
            else:
                logger.error("❌ SMTP connection failed")
                all_good = False
        else:
            logger.error("❌ SMTP client not initialized")
            all_good = False

        # Test OpenAI connection
        if self.openai_client:
            if self.openai_client.test_connection():
                logger.info("✅ OpenAI API connection successful")
            else:
                logger.error("❌ OpenAI API connection failed")
                all_good = False
        else:
            logger.error("❌ OpenAI client not initialized")
            all_good = False

        if all_good:
            logger.info("🎉 All connections and configurations are working properly!")
        else:
            logger.error("⚠️  Some connections or configurations have issues")

        return all_good

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

    def _get_workflows_dir(self) -> Path:
        """Return the path to the workflows directory."""
        return Path(__file__).resolve().parent.parent.parent / "workflows"

    def _get_action_map(self) -> dict[str, callable]:
        """Return mapping of action names to methods."""
        return {
            "process_unread_emails": self.process_unread_emails,
            "process_assignee_responses": self.process_assignee_responses,
            "cleanup_meetings": self.cleanup_meetings,
            "todays_meetings": self.todays_meetings,
            "process_invites": self.process_invites,
        }

    def list_workflows(self) -> None:
        """List all available workflows from the workflows directory."""
        workflows_dir = self._get_workflows_dir()
        if not workflows_dir.is_dir():
            print("No workflows directory found.")
            return

        workflow_files = sorted(workflows_dir.glob("*.json"))
        if not workflow_files:
            print("No workflows found.")
            return

        print("\nAvailable workflows:\n")
        for i, wf_path in enumerate(workflow_files, 1):
            try:
                data = json.loads(wf_path.read_text(encoding="utf-8"))
                name = data.get("name", wf_path.stem)
                description = data.get("description", "")
                print(f"  {i}. {wf_path.stem} — {name}")
                if description:
                    print(f"     {description}")
                print()
            except (json.JSONDecodeError, OSError) as e:
                logger.error(f"Failed to read workflow {wf_path.name}: {e}")

        print("Run a workflow: main.py --workflow <name>")

    def run_workflow(self, name: str) -> None:
        """Load and execute a named workflow from the workflows directory."""
        workflows_dir = self._get_workflows_dir()
        workflow_path = workflows_dir / f"{name}.json"

        if not workflow_path.is_file():
            logger.error(f"Workflow '{name}' not found at {workflow_path}")
            print(f"\nWorkflow '{name}' not found.")
            print("Use --workflow (without a name) to list available workflows.")
            return

        try:
            data = json.loads(workflow_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load workflow '{name}': {e}")
            return

        workflow_name = data.get("name", name)
        steps = data.get("steps", [])

        if not steps:
            logger.warning(f"Workflow '{workflow_name}' has no steps")
            return

        action_map = self._get_action_map()
        logger.info(f"Running workflow: {workflow_name} ({len(steps)} steps)")

        for i, step in enumerate(steps, 1):
            action = step.get("action")
            if not action:
                logger.warning(f"Step {i} has no action, skipping")
                continue

            method = action_map.get(action)
            if not method:
                logger.error(f"Step {i}: unknown action '{action}', skipping")
                continue

            logger.info(f"Step {i}/{len(steps)}: {action}")
            try:
                params = step.get("params", {})
                if params:
                    method(**params)
                else:
                    method()
            except Exception as e:
                logger.error(f"Step {i} ({action}) failed: {e}")

        logger.info(f"Workflow '{workflow_name}' completed")
