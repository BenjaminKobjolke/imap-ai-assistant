"""Presentation and interactive actions for email search results."""

from __future__ import annotations

import logging
from email.utils import parseaddr

from src.config.settings import ConfigManager
from src.constants import FOLDER_INBOX
from src.email.email_actions import email_action_loop
from src.email.imap_client import EnhancedImapClient
from src.interaction.scheduler_prompts import SchedulerChoice, scheduler_choose, send_output
from src.search.search_cache import parse_date_to_iso

logger = logging.getLogger(__name__)


class SearchResultsView:
    """Present search results and let users inspect or act on a message."""

    PAGE_SIZE = 5

    @staticmethod
    def display_results(results: list[dict]) -> None:
        """Display numbered search results."""
        line = "\u2501" * 50
        send_output(f"\n{line}")
        send_output(f"  Search Results ({len(results)})")
        send_output(line)

        for i, r in enumerate(results, 1):
            folder = r.get("folder", "")
            from_display = SearchResultsView.format_address(r.get("from_name", ""), r.get("from_address", ""))
            subject = r.get("subject", "(no subject)")
            date = r.get("date_iso", r.get("date_str", ""))
            send_output(f"  {i}. [{folder}]")
            send_output(f"     From:    {from_display}")
            send_output(f"     Subject: {subject}")
            send_output(f"     Date:    {date}")
            send_output("")

        send_output(line)


    @staticmethod
    def format_address(name: str, address: str) -> str:
        """Format name + address for display."""
        if name and address:
            return f"{name} <{address}>"
        return address or name or "(unknown)"


    @staticmethod
    def result_detail_loop(
        results: list[dict],
        client: EnhancedImapClient,
        config: ConfigManager,
    ) -> None:
        """Let the user pick a result and act on it."""
        while True:
            labels = [
                f"{i + 1}. {r.get('subject', '(no subject)')[:40]}"
                for i, r in enumerate(results)
            ]
            labels.append("Quit")
            choice = scheduler_choose("Select:", labels, default=len(labels) - 1)

            if choice >= len(results):
                return

            selected = results[choice]
            SearchResultsView.show_detail(selected)
            SearchResultsView.detail_action_loop(selected, client, config)


    @staticmethod
    def show_detail(result: dict) -> None:
        """Display detail view for a single email."""
        line = "\u2501" * 50
        from_display = SearchResultsView.format_address(result.get("from_name", ""), result.get("from_address", ""))
        to_display = SearchResultsView.format_address(result.get("to_name", ""), result.get("to_address", ""))

        send_output(f"\n{line}")
        send_output(f"  Folder:  {result.get('folder', '')}")
        send_output(f"  From:    {from_display}")
        send_output(f"  To:      {to_display}")
        send_output(f"  Subject: {result.get('subject', '')}")
        send_output(f"  Date:    {result.get('date_iso', result.get('date_str', ''))}")
        send_output(line)


    @staticmethod
    def detail_action_loop(
        result: dict,
        client: EnhancedImapClient,
        config: ConfigManager,
    ) -> None:
        """Action menu for a selected email."""
        folder = result.get("folder", FOLDER_INBOX)
        msg_id = result.get("message_id", "")
        while True:
            unhandled = email_action_loop(
                client, config, folder, msg_id,
                extra_actions=[("Copy to search-results", "copy")],
            )
            if unhandled == "copy":
                SearchResultsView.copy_to_results_folder(result, client, config)
                return
            else:
                return


    @staticmethod
    def copy_to_results_folder(
        result: dict,
        client: EnhancedImapClient,
        config: ConfigManager,
    ) -> None:
        """Copy the email to the search-results IMAP folder."""
        folder = result.get("folder", FOLDER_INBOX)
        msg_id = result.get("message_id", "")
        target = config.search_results_folder

        try:
            client.client.client.select_folder(folder)
            client.client.client.copy([int(msg_id)], target)
            send_output(f"  Copied to '{target}'.")
        except Exception as e:
            logger.error("Error copying email to %s: %s", target, e)
            send_output(f"  Error copying: {e}")


    @staticmethod
    def list_all_emails(
        client: EnhancedImapClient,
        config: ConfigManager,
        folder: str,
    ) -> None:
        """Fetch all emails from a folder and show them with pagination."""
        send_output(f"\nLoading emails from '{folder}'...")
        try:
            messages = client.client.get_all_messages(
                folder=folder, include_attachments=False,
            )
        except Exception as e:
            logger.error("Error loading emails from %s: %s", folder, e)
            send_output(f"Error loading emails: {e}")
            return

        if not messages:
            send_output("  No emails in this folder.")
            return

        results = SearchResultsView.messages_to_results(messages, folder)
        send_output(f"  {len(results)} email(s) found.\n")
        SearchResultsView.paginated_result_loop(results, client, config)


    @staticmethod
    def messages_to_results(
        messages: list[tuple],
        folder: str,
    ) -> list[dict]:
        """Convert get_all_messages output to search result dicts."""
        results: list[dict] = []
        for msg_id, email_msg in messages:
            from_raw = getattr(email_msg, "from_address", "") or ""
            from_name, from_addr = parseaddr(from_raw)
            to_raw = ""
            if hasattr(email_msg, "raw_message") and email_msg.raw_message:
                to_raw = str(email_msg.raw_message.get("To", ""))
            to_name, to_addr = parseaddr(to_raw)
            subject = getattr(email_msg, "subject", "") or ""
            date_str = getattr(email_msg, "date", "") or ""
            date_iso = parse_date_to_iso(date_str)

            results.append({
                "message_id": str(msg_id),
                "folder": folder,
                "from_address": from_addr,
                "from_name": from_name,
                "to_address": to_addr,
                "to_name": to_name,
                "subject": subject,
                "date_str": date_str,
                "date_iso": date_iso,
                "body_preview": "",
            })
        return results


    @staticmethod
    def paginated_result_loop(
        results: list[dict],
        client: EnhancedImapClient,
        config: ConfigManager,
    ) -> None:
        """Show results PAGE_SIZE at a time with navigation."""
        page = 0
        while True:
            start = page * SearchResultsView.PAGE_SIZE
            page_items = results[start : start + SearchResultsView.PAGE_SIZE]
            if not page_items:
                page = max(0, page - 1)
                continue

            line = "\u2501" * 50
            send_output(f"\n{line}")
            send_output(f"  Emails ({start + 1}-{start + len(page_items)} of {len(results)})")
            send_output(line)

            for i, r in enumerate(page_items):
                idx = start + i + 1
                from_display = SearchResultsView.format_address(
                    r.get("from_name", ""), r.get("from_address", ""),
                )
                subject = r.get("subject", "(no subject)")
                date = r.get("date_iso", r.get("date_str", ""))
                send_output(f"  {idx}. {from_display}")
                send_output(f"     {subject}")
                send_output(f"     {date}")
                send_output("")

            send_output(line)

            choices: list[tuple[str, str]] = []
            for i, r in enumerate(page_items):
                subject = r.get("subject", "(no subject)")[:40]
                choices.append((f"{start + i + 1}. {subject}", f"email_{start + i}"))

            if start + SearchResultsView.PAGE_SIZE < len(results):
                choices.append(("Next \u2192", "__next__"))
            if page > 0:
                choices.append(("\u2190 Previous", "__prev__"))
            choices.append(("Back", "__back__"))

            action = SchedulerChoice("Select:", choices).choose()

            if action == "__next__":
                page += 1
            elif action == "__prev__":
                page -= 1
            elif action in ("__back__", "abort"):
                return
            elif action.startswith("email_"):
                email_idx = int(action.removeprefix("email_"))
                selected = results[email_idx]
                SearchResultsView.show_detail(selected)
                SearchResultsView.detail_action_loop(selected, client, config)

