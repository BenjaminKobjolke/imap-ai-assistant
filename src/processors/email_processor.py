from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timedelta
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

    def __init__(self, config_path: str = "settings.json", dry_run: bool = False):
        self.config = ConfigManager(config_path)
        self.dry_run = dry_run
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
            self.response_processor = ResponseProcessor(self.config, self.openai_client, dry_run=self.dry_run)
            self.task_processor = TaskProcessor(self.config, self.smtp_client, self.openai_client, dry_run=self.dry_run)

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
            calendar_id=self.config.accepts_meetings_calendar_id,
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
        selected_add_date = self._setup_add_date_calendar(calendars, cal_names)

        print("\nSetup complete.")
        print(f"  Meeting calendar: {cal_names.get(selected_calendar, selected_calendar)}")
        if selected_checks:
            names = ", ".join(cal_names.get(c, c) for c in selected_checks)
            print(f"  Conflict-check:   {names}")
        else:
            print("  Conflict-check:   (none)")
        print(f"  Add-date calendar: {cal_names.get(selected_add_date, selected_add_date)}")

    def _setup_meeting_calendar(self, calendars: list[dict], cal_names: dict[str, str]) -> str:
        """Step 1: Let the user pick the calendar for adding events."""
        current_id = self.config.accepts_meetings_calendar_id
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
                new_name = selected.get("summary", "")
                self.config.save_setting(
                    ["meetings", "google_calendar", "accepts_meetings_calendar"],
                    {"name": new_name, "id": new_id},
                )
                print(f"  Saved: {new_name} ({new_id})")
                return new_id
            print("  Invalid choice. Try again.")

    def _setup_free_check_calendars(self, calendars: list[dict], cal_names: dict[str, str]) -> list[str]:
        """Step 2: Let the user toggle which calendars are checked for conflicts."""
        current_check_ids = set(self.config.free_check_calendar_ids)

        print("\nConflict-Check Calendars")

        while True:
            if current_check_ids:
                names = ", ".join(cal_names.get(c, c) for c in current_check_ids)
                print(f"Currently checked: {names}")
            else:
                print("Currently checked: (none)")
            print()

            for i, cal in enumerate(calendars, 1):
                cal_id = cal.get("id", "")
                name = cal.get("summary", "(unnamed)")
                checked = "x" if cal_id in current_check_ids else " "
                print(f"  {i}. [{checked}] {name} -- {cal_id}")

            print("\nToggle a number, or press Enter when done:")

            choice = input("  > ").strip()
            if choice == "":
                result = [
                    {"name": cal_names.get(cid, ""), "id": cid}
                    for cid in current_check_ids
                ]
                self.config.save_setting(
                    ["meetings", "google_calendar", "free_check_calendars"], result,
                )
                return list(current_check_ids)
            if choice.isdigit() and 1 <= int(choice) <= len(calendars):
                cal_id = calendars[int(choice) - 1].get("id", "")
                if cal_id in current_check_ids:
                    current_check_ids.discard(cal_id)
                else:
                    current_check_ids.add(cal_id)
                print()
            else:
                print("  Invalid input. Enter a single number.\n")

    def set_meeting_calendar(self, calendar_id: str) -> None:
        """Set the Google Calendar ID used for adding events."""
        value = {"name": "", "id": calendar_id}
        if self.config.save_setting(["meetings", "google_calendar", "accepts_meetings_calendar"], value):
            print(f"Meeting calendar set to: {calendar_id}")
        else:
            print("Failed to save setting.")

    def set_meeting_free_check_calendar(self, calendar_id: str) -> None:
        """Add a calendar ID to the list of calendars checked for conflicts."""
        existing = list(self.config.free_check_calendars)
        if calendar_id in self.config.free_check_calendar_ids:
            print(f"Calendar already in free-check list: {calendar_id}")
            return
        existing.append({"name": "", "id": calendar_id})
        if self.config.save_setting(["meetings", "google_calendar", "free_check_calendars"], existing):
            print(f"Added to free-check calendars: {calendar_id}")
        else:
            print("Failed to save setting.")

    def remove_meeting_free_check_calendar(self, calendar_id: str) -> None:
        """Remove a calendar ID from the list of calendars checked for conflicts."""
        existing = list(self.config.free_check_calendars)
        updated = [c for c in existing if c.get("id") != calendar_id]
        if len(updated) == len(existing):
            print(f"Calendar not in free-check list: {calendar_id}")
            return
        if self.config.save_setting(["meetings", "google_calendar", "free_check_calendars"], updated):
            print(f"Removed from free-check calendars: {calendar_id}")
        else:
            print("Failed to save setting.")

    def add_date(self, raw_args: list[str]) -> None:
        """Create a Google Calendar event from CLI arguments."""
        parsed = self._parse_add_date_args(raw_args)
        if parsed is None:
            return

        title, event_date, start_hour, end_hour, calendar_query = parsed

        from src.calendar.google_calendar_client import GoogleCalendarClient

        calendar_id = self.config.add_date_calendar_id

        gcal_client = GoogleCalendarClient(
            credentials_path=self.config.google_calendar_credentials_path,
            token_path=self.config.google_calendar_token_path,
            calendar_id=calendar_id,
        )
        if not gcal_client.authenticate():
            logger.error("Failed to authenticate with Google Calendar")
            return

        if calendar_query:
            resolved_id = self._resolve_calendar_query(gcal_client, calendar_query)
            if resolved_id is None:
                return
            calendar_id = resolved_id
            gcal_client.calendar_id = calendar_id

        start_dt = datetime(event_date.year, event_date.month, event_date.day, start_hour)
        end_dt = start_dt + timedelta(hours=end_hour - start_hour)

        event_id = gcal_client.create_event(title, start_dt, end_dt)
        if event_id:
            cal_name = self.config.add_date_calendar_name
            if calendar_query:
                cal_name = calendar_query
            date_str = event_date.strftime("%d.%m.%Y")
            print(f"Created: {title} on {date_str} {start_hour:02d}:00-{end_hour:02d}:00 ({cal_name})")
        else:
            print("Failed to create event.")

    def _parse_add_date_args(self, raw_args: list[str]) -> tuple | None:
        """Parse --add-date arguments into (title, date, start_hour, end_hour, calendar_query)."""
        from datetime import date as date_type

        if not raw_args:
            print("Usage: --add-date TITLE [DATE] [START[-END]] [@CALENDAR]")
            return None

        title = raw_args[0]
        tokens = raw_args[1:]

        event_date: date_type = date_type.today()
        start_hour: int | None = None
        end_hour: int | None = None
        calendar_query: str | None = None

        time_re = re.compile(r"^(\d{1,2})(?:-(\d{1,2}))?$")

        for token in tokens:
            if token.startswith("@"):
                calendar_query = token[1:]
                continue

            if "." in token:
                try:
                    event_date = MeetingCleanup._parse_date(token)
                    continue
                except ValueError:
                    pass

            m = time_re.match(token)
            if m:
                start_hour = int(m.group(1))
                end_hour = int(m.group(2)) if m.group(2) else start_hour + 1
                continue

            print(f"Unrecognised argument: {token}")
            return None

        now = datetime.now()
        if start_hour is None:
            start_hour = now.hour
        if end_hour is None:
            end_hour = start_hour + 1

        return title, event_date, start_hour, end_hour, calendar_query

    def _resolve_calendar_query(self, gcal_client, query: str) -> str | None:
        """Resolve a partial calendar name to a calendar ID via substring match."""
        calendars = gcal_client.list_calendars()
        query_lower = query.lower()
        matches = [
            c for c in calendars
            if query_lower in c.get("summary", "").lower()
        ]

        if not matches:
            print(f"No calendar matching '{query}' found.")
            return None

        if len(matches) == 1:
            cal = matches[0]
            print(f"Calendar: {cal.get('summary', '')} ({cal.get('id', '')})")
            return cal.get("id", "")

        print(f"\nMultiple calendars match '{query}':\n")
        for i, cal in enumerate(matches, 1):
            print(f"  {i}. {cal.get('summary', '')} -- {cal.get('id', '')}")

        print("\nPick a number:")
        while True:
            choice = input("  > ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(matches):
                selected = matches[int(choice) - 1]
                return selected.get("id", "")
            print("  Invalid choice. Try again.")

    def list_tag_rules(self) -> None:
        """List all subject tag rules."""
        self.config.list_tag_rules()

    def add_sender_tag(self, pattern: str, tag: str) -> None:
        """Add a sender-based subject tag rule."""
        self.config.add_sender_tag_rule(pattern, tag)

    def remove_sender_tag(self, pattern: str) -> None:
        """Remove a sender-based subject tag rule."""
        if not self.config.remove_sender_tag_rule(pattern):
            print(f"No sender tag rule found for pattern: {pattern}")

    def add_keyword_tag(self, tag: str, keywords: list[str], match: str = "all") -> None:
        """Add a keyword-based subject tag rule."""
        self.config.add_keyword_tag_rule(keywords, tag, match)

    def remove_keyword_tag(self, tag: str) -> None:
        """Remove a keyword-based subject tag rule."""
        if not self.config.remove_keyword_tag_rule(tag):
            print(f"No keyword tag rule found for tag: {tag}")

    def setup_tag_rules(self) -> None:
        """Interactive wizard to list, add, edit, and delete subject tag rules."""
        while True:
            rules = self.config.get_subject_tag_rules()
            sender_rules = rules["sender_rules"]
            keyword_rules = rules["keyword_rules"]

            combined = []
            for rule in sender_rules:
                combined.append(("sender", rule))
            for rule in keyword_rules:
                combined.append(("keyword", rule))

            print("\nSubject Tag Rules")
            print("=================\n")

            if not combined:
                print("  (no rules configured)\n")
            else:
                if sender_rules:
                    print("Sender rules:")
                    for i, rule in enumerate(sender_rules, 1):
                        print(f"  {i}. {rule['pattern']} -> {rule['tag']}")
                    print()

                if keyword_rules:
                    print("Keyword rules:")
                    offset = len(sender_rules)
                    for i, rule in enumerate(keyword_rules, offset + 1):
                        keywords_str = ", ".join(rule["keywords"])
                        match_mode = rule.get("match", "all")
                        print(f"  {i}. [{match_mode}] ({keywords_str}) -> {rule['tag']}")
                    print()

            print("Actions: [a]dd  [e]dit NUMBER  [d]elete NUMBER  [Enter] done")
            choice = input("  > ").strip().lower()

            if choice == "":
                print("Done.")
                return

            if choice == "a":
                self._tag_rules_add()
            elif choice.startswith("e"):
                self._tag_rules_edit(choice, combined)
            elif choice.startswith("d"):
                self._tag_rules_delete(choice, combined)
            else:
                print("  Invalid action.")

    def _tag_rules_add(self) -> None:
        """Prompt the user to add a new sender or keyword tag rule."""
        print("\n  Type: [s]ender  [k]eyword")
        rule_type = input("  > ").strip().lower()

        if rule_type == "s":
            pattern = input("  Sender pattern (e.g. @example.com): ").strip()
            if not pattern:
                print("  Cancelled.")
                return
            tag = input("  Tag (e.g. #project_tag): ").strip()
            if not tag:
                print("  Cancelled.")
                return
            self.config.add_sender_tag_rule(pattern, tag)
            print(f"  Added: {pattern} -> {tag}")

        elif rule_type == "k":
            tag = input("  Tag (e.g. #project_tag): ").strip()
            if not tag:
                print("  Cancelled.")
                return
            keywords_str = input("  Keywords (comma-separated): ").strip()
            if not keywords_str:
                print("  Cancelled.")
                return
            keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]
            if not keywords:
                print("  Cancelled.")
                return
            print("  Match mode: [a]ll  [n]any")
            match_choice = input("  > ").strip().lower()
            match_mode = "any" if match_choice == "n" else "all"
            self.config.add_keyword_tag_rule(keywords, tag, match_mode)
            print(f"  Added: [{match_mode}] ({', '.join(keywords)}) -> {tag}")

        else:
            print("  Cancelled.")

    def _tag_rules_edit(self, choice: str, combined: list[tuple[str, dict]]) -> None:
        """Edit an existing tag rule by its index."""
        parts = choice.split()
        if len(parts) < 2 or not parts[1].isdigit():
            print("  Usage: e NUMBER")
            return

        idx = int(parts[1]) - 1
        if idx < 0 or idx >= len(combined):
            print("  Invalid rule number.")
            return

        rule_type, rule = combined[idx]

        if rule_type == "sender":
            print(f"\n  Current: {rule['pattern']} -> {rule['tag']}")
            new_pattern = input(f"  Pattern [{rule['pattern']}]: ").strip()
            new_tag = input(f"  Tag [{rule['tag']}]: ").strip()

            old_pattern = rule["pattern"]
            final_pattern = new_pattern if new_pattern else old_pattern
            final_tag = new_tag if new_tag else rule["tag"]

            if final_pattern != old_pattern:
                self.config.remove_sender_tag_rule(old_pattern)
            self.config.add_sender_tag_rule(final_pattern, final_tag)
            print(f"  Updated: {final_pattern} -> {final_tag}")

        else:
            keywords_str = ", ".join(rule["keywords"])
            match_mode = rule.get("match", "all")
            print(f"\n  Current: [{match_mode}] ({keywords_str}) -> {rule['tag']}")

            new_tag = input(f"  Tag [{rule['tag']}]: ").strip()
            new_keywords = input(f"  Keywords (comma-separated) [{keywords_str}]: ").strip()
            print(f"  Match mode: [a]ll  [n]any  [{match_mode[0]}]")
            new_match = input("  > ").strip().lower()

            old_tag = rule["tag"]
            final_tag = new_tag if new_tag else old_tag
            final_keywords = (
                [k.strip() for k in new_keywords.split(",") if k.strip()]
                if new_keywords
                else rule["keywords"]
            )
            if new_match == "n":
                final_match = "any"
            elif new_match == "a":
                final_match = "all"
            else:
                final_match = match_mode

            if final_tag != old_tag:
                self.config.remove_keyword_tag_rule(old_tag)
            self.config.add_keyword_tag_rule(final_keywords, final_tag, final_match)
            print(f"  Updated: [{final_match}] ({', '.join(final_keywords)}) -> {final_tag}")

    def _tag_rules_delete(self, choice: str, combined: list[tuple[str, dict]]) -> None:
        """Delete a tag rule by its index after confirmation."""
        parts = choice.split()
        if len(parts) < 2 or not parts[1].isdigit():
            print("  Usage: d NUMBER")
            return

        idx = int(parts[1]) - 1
        if idx < 0 or idx >= len(combined):
            print("  Invalid rule number.")
            return

        rule_type, rule = combined[idx]

        if rule_type == "sender":
            label = f"{rule['pattern']} -> {rule['tag']}"
        else:
            keywords_str = ", ".join(rule["keywords"])
            match_mode = rule.get("match", "all")
            label = f"[{match_mode}] ({keywords_str}) -> {rule['tag']}"

        confirm = input(f"  Delete '{label}'? [y/N] ").strip().lower()
        if confirm == "y":
            if rule_type == "sender":
                self.config.remove_sender_tag_rule(rule["pattern"])
            else:
                self.config.remove_keyword_tag_rule(rule["tag"])
            print("  Deleted.")
        else:
            print("  Cancelled.")

    def set_add_date_calendar(self, calendar_id: str) -> None:
        """Set the default Google Calendar ID for --add-date events."""
        value = {"name": "", "id": calendar_id}
        if self.config.save_setting(["meetings", "google_calendar", "add_date_calendar"], value):
            print(f"Add-date calendar set to: {calendar_id}")
        else:
            print("Failed to save setting.")

    def _setup_add_date_calendar(self, calendars: list[dict], cal_names: dict[str, str]) -> str:
        """Step 3: Let the user pick the default calendar for --add-date events."""
        current_id = self.config.add_date_calendar_id
        current_name = cal_names.get(current_id, current_id)

        print("\nAdd-Date Calendar (default for --add-date)")
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
                new_name = selected.get("summary", "")
                self.config.save_setting(
                    ["meetings", "google_calendar", "add_date_calendar"],
                    {"name": new_name, "id": new_id},
                )
                print(f"  Saved: {new_name} ({new_id})")
                return new_id
            print("  Invalid choice. Try again.")

    def list_calendars(self) -> None:
        """List all available Google Calendars for the authenticated user."""
        from src.calendar.google_calendar_client import GoogleCalendarClient

        gcal_client = GoogleCalendarClient(
            credentials_path=self.config.google_calendar_credentials_path,
            token_path=self.config.google_calendar_token_path,
            calendar_id=self.config.accepts_meetings_calendar_id,
        )
        if not gcal_client.authenticate():
            logger.error("Failed to authenticate with Google Calendar")
            return

        calendars = gcal_client.list_calendars()
        if not calendars:
            print("No calendars found.")
            return

        configured = self.config.accepts_meetings_calendar_id
        configured_name = self.config.accepts_meetings_calendar_name
        label = f"{configured_name} ({configured})" if configured_name else configured
        print(f"\nConfigured calendar: {label}\n")
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
            calendar_id=self.config.accepts_meetings_calendar_id,
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
