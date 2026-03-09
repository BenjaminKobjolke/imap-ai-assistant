"""Service classes for Google Calendar configuration and event creation.

Renamed from CalendarSetup. Base class holds shared logic; Interactive and AI
child classes differ in add_date (undo prompt) and _resolve_calendar_query
(interactive picker vs auto-pick).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from src.config.settings import ConfigManager
from src.interaction.scheduler_prompts import SchedulerChoice, send_output
from src.processors.meeting_cleanup import MeetingCleanup

logger = logging.getLogger(__name__)


class CalendarService:
    """Base class for calendar operations — shared helpers live here."""

    def __init__(self, config: ConfigManager) -> None:
        self.config = config

    # -- Interactive wizard (CLI-only, never called by AI) ----------------------

    def setup_meetings(self) -> None:
        """Interactive setup for meeting calendar and conflict-check calendars."""
        from src.calendar.google_calendar_client import GoogleCalendarClient

        gcal_client = GoogleCalendarClient.from_config(self.config)
        if gcal_client is None:
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

    # -- Non-interactive setters ------------------------------------------------

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

    def set_add_date_calendar(self, calendar_id: str) -> None:
        """Set the default Google Calendar ID for --add-date events."""
        value = {"name": "", "id": calendar_id}
        if self.config.save_setting(["meetings", "google_calendar", "add_date_calendar"], value):
            print(f"Add-date calendar set to: {calendar_id}")
        else:
            print("Failed to save setting.")

    def list_calendars(self) -> None:
        """List all available Google Calendars for the authenticated user."""
        from src.calendar.google_calendar_client import GoogleCalendarClient

        gcal_client = GoogleCalendarClient.from_config(self.config)
        if gcal_client is None:
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

    # -- Shared parse helpers ---------------------------------------------------

    def _parse_add_date_args(self, raw_args: list[str]) -> tuple | None:
        """Parse --add-date arguments into (title, date, start_hour, start_minute, end_hour, end_minute, calendar_query, all_day)."""
        from datetime import date as date_type

        if not raw_args:
            send_output("Usage: --add-date TITLE [DATE] [START[-END]] [@CALENDAR] [allday]")
            return None

        title = raw_args[0]
        tokens = raw_args[1:]

        event_date: date_type = date_type.today()
        start_hour: int | None = None
        start_minute: int = 0
        end_hour: int | None = None
        end_minute: int = 0
        calendar_query: str | None = None
        all_day: bool = False

        time_re = re.compile(r"^(\d{1,2})(?::(\d{2}))?(?:-(\d{1,2})(?::(\d{2}))?)?$")

        for token in tokens:
            if token.lower() == "allday":
                all_day = True
                continue

            if token.startswith("@"):
                calendar_query = token[1:]
                continue

            m = time_re.match(token)
            if m:
                start_hour = int(m.group(1))
                start_minute = int(m.group(2)) if m.group(2) else 0
                if m.group(3):
                    end_hour = int(m.group(3))
                    end_minute = int(m.group(4)) if m.group(4) else 0
                else:
                    end_hour = start_hour + 1
                    end_minute = start_minute
                continue

            try:
                event_date = MeetingCleanup._parse_date(token)
                continue
            except ValueError:
                pass

            send_output(f"Unrecognised argument: {token}")
            return None

        if not all_day:
            now = datetime.now()
            if start_hour is None:
                start_hour = now.hour
                start_minute = 0
            if end_hour is None:
                end_hour = start_hour + 1
                end_minute = start_minute

        return title, event_date, start_hour, start_minute, end_hour, end_minute, calendar_query, all_day

    # -- Abstract methods that differ between Interactive and AI -----------------

    def add_date(self, raw_args: list[str]) -> None:
        """Create a Google Calendar event. Must be implemented by child classes."""
        raise NotImplementedError

    def _resolve_calendar_query(self, gcal_client: object, query: str) -> str | None:
        """Resolve a partial calendar name to an ID. Must be implemented by child classes."""
        raise NotImplementedError

    # -- Shared add_date core ---------------------------------------------------

    def _create_event_core(self, raw_args: list[str]) -> tuple | None:
        """Parse args, authenticate, resolve calendar, create event.

        Returns (gcal_client, event_id, title, event_date, start_hour, start_minute, end_hour, end_minute, cal_name, all_day)
        or None on failure.
        """
        parsed = self._parse_add_date_args(raw_args)
        if parsed is None:
            return None

        title, event_date, start_hour, start_minute, end_hour, end_minute, calendar_query, all_day = parsed

        from src.calendar.google_calendar_client import GoogleCalendarClient

        calendar_id = self.config.add_date_calendar_id

        gcal_client = GoogleCalendarClient.from_config(
            self.config, calendar_id=calendar_id,
        )
        if gcal_client is None:
            logger.error("Failed to authenticate with Google Calendar")
            return None

        if calendar_query:
            resolved_id = self._resolve_calendar_query(gcal_client, calendar_query)
            if resolved_id is None:
                return None
            calendar_id = resolved_id
            gcal_client.calendar_id = calendar_id

        if all_day:
            event_id = gcal_client.create_all_day_event(title, event_date)
        else:
            start_dt = datetime(event_date.year, event_date.month, event_date.day, start_hour, start_minute)
            end_dt = datetime(event_date.year, event_date.month, event_date.day, end_hour, end_minute)
            event_id = gcal_client.create_event(title, start_dt, end_dt)

        cal_name = self.config.add_date_calendar_name
        if calendar_query:
            cal_name = calendar_query

        if not event_id:
            send_output("Failed to create event.")
            return None

        return gcal_client, event_id, title, event_date, start_hour, start_minute, end_hour, end_minute, cal_name, all_day


class CalendarServiceInteractive(CalendarService):
    """Calendar service with interactive undo prompt and calendar picker."""

    def add_date(self, raw_args: list[str]) -> None:
        """Create a Google Calendar event with undo prompt."""
        result = self._create_event_core(raw_args)
        if result is None:
            return

        gcal_client, event_id, title, event_date, start_hour, start_minute, end_hour, end_minute, cal_name, all_day = result

        date_str = event_date.strftime("%d.%m.%Y")
        if all_day:
            send_output(f"Created: {title} on {date_str} (all day) ({cal_name})")
        else:
            send_output(f"Created: {title} on {date_str} {start_hour:02d}:{start_minute:02d}-{end_hour:02d}:{end_minute:02d} ({cal_name})")
        undo = SchedulerChoice(
            "", [("Keep", "keep"), ("Undo (delete event)", "undo")],
        ).choose()
        if undo == "undo":
            if gcal_client.delete_event_by_id(event_id):
                send_output("Event deleted.")
            else:
                send_output("Failed to delete event.")

    def _resolve_calendar_query(self, gcal_client: object, query: str) -> str | None:
        """Resolve a partial calendar name with interactive picker for ambiguous matches."""
        calendars = gcal_client.list_calendars()
        query_lower = query.lower()
        matches = [
            c for c in calendars
            if query_lower in c.get("summary", "").lower()
        ]

        if not matches:
            send_output(f"No calendar matching '{query}' found.")
            return None

        if len(matches) == 1:
            cal = matches[0]
            send_output(f"Calendar: {cal.get('summary', '')} ({cal.get('id', '')})")
            return cal.get("id", "")

        send_output(f"\nMultiple calendars match '{query}':\n")
        for i, cal in enumerate(matches, 1):
            send_output(f"  {i}. {cal.get('summary', '')} -- {cal.get('id', '')}")

        send_output("\nPick a number:")
        while True:
            choice = input("  > ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(matches):
                selected = matches[int(choice) - 1]
                return selected.get("id", "")
            print("  Invalid choice. Try again.")


