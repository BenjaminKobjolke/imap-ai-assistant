"""Service class for meeting-related operations."""

from __future__ import annotations

import logging

from src.config.settings import ConfigManager
from src.email.imap_client import EnhancedImapClient
from src.processors.meeting_cleanup import MeetingCleanup

logger = logging.getLogger(__name__)


class MeetingService:
    """Meeting operations: list, detail, cleanup."""

    def __init__(self, config: ConfigManager) -> None:
        self.config = config

    def _connect_main_account(self) -> EnhancedImapClient | None:
        """Connect to the main IMAP account."""
        account_config = self.config.get_first_account()
        if not account_config:
            logger.error("No main account configuration found")
            return None
        client = EnhancedImapClient(account_config)
        if not client.connect():
            logger.error("Failed to connect to IMAP server")
            return None
        return client

    def _create_gcal_client(self) -> object | None:
        """Create a Google Calendar client, or None if unavailable."""
        from src.calendar.google_calendar_client import GoogleCalendarClient

        try:
            return GoogleCalendarClient.from_config(self.config)
        except Exception:
            logger.info("Google Calendar not available — showing IMAP meetings only")
            return None

    def todays_meetings(self) -> None:
        """List today's meetings."""
        client = self._connect_main_account()
        if not client:
            return

        gcal_client = self._create_gcal_client()

        try:
            MeetingCleanup.list_todays_meetings(
                client, self.config, gcal_client=gcal_client,
            )
        except Exception as e:
            logger.error(f"Error listing today's meetings: {e}")
        finally:
            client.disconnect()

    def meetings(self, date_str: str) -> None:
        """List meetings for a given date."""
        try:
            target_date = MeetingCleanup._parse_date(date_str)
        except ValueError as e:
            logger.error(str(e))
            return

        client = self._connect_main_account()
        if not client:
            return

        gcal_client = self._create_gcal_client()

        try:
            MeetingCleanup.list_todays_meetings(
                client, self.config, target_date=target_date, gcal_client=gcal_client,
            )
        except Exception as e:
            logger.error(f"Error listing meetings: {e}")
        finally:
            client.disconnect()

    def meeting_detail(self, date_str: str, meeting_id: str) -> None:
        """Show details for a specific meeting by date and ID."""
        client = self._connect_main_account()
        if not client:
            return

        gcal_client = self._create_gcal_client()

        try:
            MeetingCleanup.show_meeting_detail_by_id(
                client, self.config, date_str, meeting_id, gcal_client=gcal_client,
            )
        except Exception as e:
            logger.error(f"Error showing meeting detail: {e}")
        finally:
            client.disconnect()

    def cleanup_meetings(self) -> None:
        """Archive old meeting emails based on their ICS calendar date."""
        logger.info(
            f"Starting meeting cleanup (folder: {self.config.meetings_folder}, "
            f"age limit: {self.config.meetings_age_limit_hours}h, "
            f"archive: {self.config.meetings_archive_folder})",
        )
        client = self._connect_main_account()
        if not client:
            return
        try:
            MeetingCleanup.cleanup_old_meetings(client, self.config)
        except Exception as e:
            logger.error(f"Error during meeting cleanup: {e}")
        finally:
            client.disconnect()


