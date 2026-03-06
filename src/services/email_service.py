"""Service class for email I/O operations extracted from EmailProcessor."""

from __future__ import annotations

import logging

from src.ai.openai_client import OpenAIClient
from src.browse.folder_browser import FolderBrowser
from src.config.settings import ConfigManager
from src.email.imap_client import EnhancedImapClient
from src.processors.email_inspector import EmailInspector
from src.search.cache_builder import CacheBuilder
from src.search.email_search import EmailSearch

logger = logging.getLogger(__name__)


class EmailService:
    """Handles email search, inspection, browsing, and cache operations."""

    def __init__(self, config: ConfigManager, openai_client: OpenAIClient | None = None) -> None:
        self.config = config
        self.openai_client = openai_client

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

    def inspect_folder(self, folder_name: str, use_processor_account: bool = False) -> None:
        """Inspect emails in a given IMAP folder for debugging purposes.

        Read-only: does not mark emails as read or modify anything.
        """
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

        self._update_calendar_cache()

    def _update_calendar_cache(self) -> None:
        """Fetch Google Calendar list and cache names in SQLite."""
        from src.calendar.google_calendar_client import GoogleCalendarClient
        from src.search.search_cache import SearchCache

        gcal_client = GoogleCalendarClient.from_config(self.config)
        if gcal_client is None:
            logger.info("Google Calendar not available — skipping calendar cache")
            return

        calendars = gcal_client.list_calendars()
        if not calendars:
            return

        entries = [
            {"name": c.get("summary", ""), "id": c.get("id", "")}
            for c in calendars if c.get("id")
        ]
        cache = SearchCache(self.config.search_cache_path)
        try:
            cache.save_calendars(entries)
        finally:
            cache.close()
        logger.info("Cached %d calendar names", len(entries))

    def update_calendar_cache(self) -> None:
        """Public wrapper: fetch and cache Google Calendar list."""
        self._update_calendar_cache()

    def list_cached_calendars(self) -> None:
        """Print cached Google Calendar names and IDs."""
        from src.search.search_cache import SearchCache

        cache = SearchCache(self.config.search_cache_path)
        try:
            calendars = cache.get_calendars()
        finally:
            cache.close()

        if not calendars:
            print("No cached calendars. Run --update-calendars first.")
            return

        print(f"\nCached Google Calendars ({len(calendars)}):")
        print("-" * 60)
        for cal in calendars:
            print(f"  {cal['name']}")
            print(f"    ID: {cal['id']}")
        print()

    def browse(self) -> None:
        """Interactive IMAP folder and email browser."""
        client = self._connect_main_account()
        if not client:
            return
        try:
            FolderBrowser(client, self.config, self.openai_client).browse()
        except Exception as e:
            logger.error("Error in browse: %s", e)
        finally:
            client.disconnect()
