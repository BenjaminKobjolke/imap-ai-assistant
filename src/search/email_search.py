"""Email search processor — search, wizard, and interactive results."""

from __future__ import annotations

import email as email_stdlib
import email.policy
import logging
from datetime import datetime
from email.utils import parseaddr

from src.config.settings import ConfigManager
from src.constants import (
    FOLDER_INBOX,
    SEARCH_MODE_ALL,
    SEARCH_MODE_DEFAULT,
    SEARCH_MODE_FOLDER,
    SEARCH_MODE_INBOX,
    SEARCH_MODE_SENT,
)
from src.email.email_actions import email_action_loop
from src.email.imap_client import EnhancedImapClient
from src.interaction.scheduler_prompts import (
    SchedulerChoice,
    scheduler_ask,
    scheduler_choose,
    scheduler_confirm,
    send_output,
)
from src.search.cache_builder import CacheBuilder
from src.search.folder_picker import folder_search_loop
from src.search.search_cache import SearchCache, parse_date_to_iso, parse_user_date

logger = logging.getLogger(__name__)

PAGE_SIZE = 5


# ------------------------------------------------------------------
# Helpers for live IMAP search
# ------------------------------------------------------------------


def _iso_to_imap_date(iso_date: str) -> str | None:
    """Convert ISO date (YYYY-MM-DD) to IMAP date format (DD-Mon-YYYY)."""
    try:
        dt = datetime.strptime(iso_date[:10], "%Y-%m-%d")
        return dt.strftime("%d-%b-%Y")
    except (ValueError, IndexError):
        return None


def _build_imap_criteria(
    term: str | None,
    field: str,
    body_term: str | None,
    date_exact: str | None,
    date_after: str | None,
    date_before: str | None,
) -> list:
    """Build IMAP SEARCH criteria list from search parameters."""
    criteria: list = []
    if term:
        field_map = {"from": "FROM", "to": "TO", "subject": "SUBJECT"}
        imap_field = field_map.get(field, "TEXT")
        words = term.split()
        for word in words:
            criteria.extend([imap_field, word])
    if body_term:
        criteria.extend(["BODY", body_term])
    # Only use full dates (YYYY-MM-DD) for IMAP date criteria
    if date_exact:
        iso = parse_user_date(date_exact)
        if len(iso) == 10:
            imap_date = _iso_to_imap_date(iso)
            if imap_date:
                criteria.extend(["ON", imap_date])
    if date_after:
        iso = parse_user_date(date_after)
        if len(iso) == 10:
            imap_date = _iso_to_imap_date(iso)
            if imap_date:
                criteria.extend(["SINCE", imap_date])
    if date_before:
        iso = parse_user_date(date_before)
        if len(iso) == 10:
            imap_date = _iso_to_imap_date(iso)
            if imap_date:
                criteria.extend(["BEFORE", imap_date])
    if not criteria:
        criteria = ["ALL"]
    return criteria


def _filter_results_by_date(
    results: list[dict],
    date_exact: str | None,
    date_after: str | None,
    date_before: str | None,
) -> list[dict]:
    """Post-filter results by date (handles partial dates IMAP can't filter)."""
    filtered = results
    if date_exact:
        iso = parse_user_date(date_exact)
        if iso:
            filtered = [r for r in filtered if r.get("date_iso", "").startswith(iso)]
    if date_after:
        iso = parse_user_date(date_after)
        if iso:
            filtered = [r for r in filtered if r.get("date_iso", "") >= iso]
    if date_before:
        iso = parse_user_date(date_before)
        if iso:
            filtered = [r for r in filtered if r.get("date_iso", "") <= iso]
    return filtered


class EmailSearch:
    """Static methods for email search, wizard, and cache management."""

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    @staticmethod
    def search(
        client: EnhancedImapClient,
        config: ConfigManager,
        search_term: str | None,
        body_term: str | None,
        date: str | None,
        date_after: str | None,
        date_before: str | None,
        path: str | None,
    ) -> None:
        """Run a search with explicit CLI arguments."""
        cache = SearchCache(config.search_cache_path)
        try:
            field, term = EmailSearch._parse_search_term(search_term or "")
            live_folders = config.search_live_folders
            path_is_live = path and path in live_folders

            # Search cache (skip if user explicitly targets a live folder)
            cache_results: list[dict] = []
            if not path_is_live:
                if not EmailSearch._ensure_cache(client, config, cache):
                    return
                cache_results = cache.search(
                    term=term or None,
                    field=field,
                    body_term=body_term,
                    date_exact=date,
                    date_after=date_after,
                    date_before=date_before,
                    folder=path,
                )

            # Search live folders via IMAP
            live_results = EmailSearch._search_live_folders(
                client, config, term, field, body_term,
                date, date_after, date_before, path,
            )

            # Merge and sort by date descending
            results = live_results + cache_results
            results.sort(key=lambda r: r.get("date_iso", ""), reverse=True)
            results = results[:9]

            if not results:
                send_output("No results found.")
                return

            EmailSearch._display_results(results)
            EmailSearch._result_detail_loop(results, client, config)
        finally:
            cache.close()

    @staticmethod
    def wizard(
        client: EnhancedImapClient,
        config: ConfigManager,
    ) -> None:
        """Interactive wizard when --search is used without arguments."""
        cache = SearchCache(config.search_cache_path)
        try:
            # 1. Where to search?
            mode = SchedulerChoice("Where to search?", [
                ("Default (cached + live folders)", SEARCH_MODE_DEFAULT),
                ("All IMAP folders", SEARCH_MODE_ALL),
                ("Inbox only", SEARCH_MODE_INBOX),
                ("Sent only", SEARCH_MODE_SENT),
                ("Search for a folder", SEARCH_MODE_FOLDER),
            ]).choose()

            # Resolve a specific folder when the user picks "Search for a folder"
            specific_folder: str | None = None
            if mode == SEARCH_MODE_FOLDER:
                specific_folder = EmailSearch._pick_search_folder(client)
                if not specific_folder:
                    send_output("No folder selected.")
                    return

                folder_action = SchedulerChoice("What to do?", [
                    ("Search in folder", "search"),
                    ("List all emails", "list_all"),
                ]).choose()

                if folder_action == "list_all":
                    EmailSearch._list_all_emails(client, config, specific_folder)
                    return

            # Ensure cache exists for modes that need it
            needs_cache = mode in (SEARCH_MODE_DEFAULT, SEARCH_MODE_FOLDER)
            if needs_cache and not EmailSearch._ensure_cache(client, config, cache):
                return

            # 2. Search scope
            field = SchedulerChoice("Search scope:", [
                ("All (from, to, subject)", "all"),
                ("From only", "from"),
                ("To only", "to"),
                ("Subject only", "subject"),
            ]).choose()

            # 3. Search term
            term = scheduler_ask("Search term:", default="")
            if not term:
                send_output("No search term provided.")
                return

            # 4. Body search
            body_raw = scheduler_ask("Body contains (leave empty to skip):", default="")
            body_term: str | None = body_raw if body_raw else None

            # 5. Date filter
            date_options = ["None", "Exact date", "After date", "Before date"]
            date_idx = scheduler_choose("Date filter:", date_options, default=0)

            date_exact = None
            date_after = None
            date_before = None
            if date_idx == 1:
                date_exact = scheduler_ask("Exact date (DD.MM.YYYY):", default="")
            elif date_idx == 2:
                date_after = scheduler_ask("After date (DD.MM.YYYY or YYYY):", default="")
            elif date_idx == 3:
                date_before = scheduler_ask("Before date (DD.MM.YYYY or YYYY):", default="")

            # 6. Execute — route based on selected mode
            results = EmailSearch._execute_wizard_search(
                client, config, cache,
                mode=mode,
                specific_folder=specific_folder,
                term=term,
                field=field,
                body_term=body_term,
                date_exact=date_exact or None,
                date_after=date_after or None,
                date_before=date_before or None,
            )

            if not results:
                send_output("No results found.")
                return

            EmailSearch._display_results(results)
            EmailSearch._result_detail_loop(results, client, config)
        finally:
            cache.close()

    # ------------------------------------------------------------------
    # Search term parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_search_term(raw: str) -> tuple[str, str]:
        """Parse prefix-based search terms.

        'to:foo' → ('to', 'foo')
        'from:foo' → ('from', 'foo')
        's:foo' → ('subject', 'foo')
        'foo' → ('all', 'foo')
        """
        prefixes = {"to:": "to", "from:": "from", "s:": "subject"}
        for prefix, field in prefixes.items():
            if raw.lower().startswith(prefix):
                return field, raw[len(prefix):]
        return "all", raw

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    @staticmethod
    def _display_results(results: list[dict]) -> None:
        """Display numbered search results."""
        line = "\u2501" * 50
        send_output(f"\n{line}")
        send_output(f"  Search Results ({len(results)})")
        send_output(line)

        for i, r in enumerate(results, 1):
            folder = r.get("folder", "")
            from_display = EmailSearch._format_address(r.get("from_name", ""), r.get("from_address", ""))
            subject = r.get("subject", "(no subject)")
            date = r.get("date_iso", r.get("date_str", ""))
            send_output(f"  {i}. [{folder}]")
            send_output(f"     From:    {from_display}")
            send_output(f"     Subject: {subject}")
            send_output(f"     Date:    {date}")
            send_output("")

        send_output(line)

    @staticmethod
    def _format_address(name: str, address: str) -> str:
        """Format name + address for display."""
        if name and address:
            return f"{name} <{address}>"
        return address or name or "(unknown)"

    # ------------------------------------------------------------------
    # Interactive result loop
    # ------------------------------------------------------------------

    @staticmethod
    def _result_detail_loop(
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
            EmailSearch._show_detail(selected)
            EmailSearch._detail_action_loop(selected, client, config)

    @staticmethod
    def _show_detail(result: dict) -> None:
        """Display detail view for a single email."""
        line = "\u2501" * 50
        from_display = EmailSearch._format_address(result.get("from_name", ""), result.get("from_address", ""))
        to_display = EmailSearch._format_address(result.get("to_name", ""), result.get("to_address", ""))

        send_output(f"\n{line}")
        send_output(f"  Folder:  {result.get('folder', '')}")
        send_output(f"  From:    {from_display}")
        send_output(f"  To:      {to_display}")
        send_output(f"  Subject: {result.get('subject', '')}")
        send_output(f"  Date:    {result.get('date_iso', result.get('date_str', ''))}")
        send_output(line)

    @staticmethod
    def _detail_action_loop(
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
                EmailSearch._copy_to_results_folder(result, client, config)
                return
            else:
                return

    # ------------------------------------------------------------------
    # Copy to results folder
    # ------------------------------------------------------------------

    @staticmethod
    def _copy_to_results_folder(
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

    # ------------------------------------------------------------------
    # List all emails in a folder (paginated)
    # ------------------------------------------------------------------

    @staticmethod
    def _list_all_emails(
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

        results = EmailSearch._messages_to_results(messages, folder)
        send_output(f"  {len(results)} email(s) found.\n")
        EmailSearch._paginated_result_loop(results, client, config)

    @staticmethod
    def _messages_to_results(
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
    def _paginated_result_loop(
        results: list[dict],
        client: EnhancedImapClient,
        config: ConfigManager,
    ) -> None:
        """Show results PAGE_SIZE at a time with navigation."""
        page = 0
        while True:
            start = page * PAGE_SIZE
            page_items = results[start : start + PAGE_SIZE]
            if not page_items:
                page = max(0, page - 1)
                continue

            line = "\u2501" * 50
            send_output(f"\n{line}")
            send_output(f"  Emails ({start + 1}-{start + len(page_items)} of {len(results)})")
            send_output(line)

            for i, r in enumerate(page_items):
                idx = start + i + 1
                from_display = EmailSearch._format_address(
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

            if start + PAGE_SIZE < len(results):
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
                EmailSearch._show_detail(selected)
                EmailSearch._detail_action_loop(selected, client, config)

    # ------------------------------------------------------------------
    # Live IMAP search (for folders not in cache)
    # ------------------------------------------------------------------

    @staticmethod
    def _search_live_folders(
        client: EnhancedImapClient,
        config: ConfigManager,
        term: str | None,
        field: str,
        body_term: str | None,
        date_exact: str | None,
        date_after: str | None,
        date_before: str | None,
        folder_filter: str | None,
        limit: int = 9,
    ) -> list[dict]:
        """Search live folders via IMAP SEARCH and return results."""
        live_folders = config.search_live_folders
        if not live_folders:
            return []

        # If user filtered to a specific folder, check if it's a live folder
        if folder_filter:
            if folder_filter not in live_folders:
                return []
            live_folders = [folder_filter]

        results: list[dict] = []
        for folder in live_folders:
            try:
                folder_results = EmailSearch._search_single_live_folder(
                    client, folder, term, field, body_term,
                    date_exact, date_after, date_before, limit,
                )
                results.extend(folder_results)
            except Exception as e:
                logger.error("Error searching live folder '%s': %s", folder, e)

        return results

    @staticmethod
    def _search_single_live_folder(
        client: EnhancedImapClient,
        folder: str,
        term: str | None,
        field: str,
        body_term: str | None,
        date_exact: str | None,
        date_after: str | None,
        date_before: str | None,
        limit: int,
    ) -> list[dict]:
        """Execute IMAP SEARCH on a single folder and return matching emails."""
        imap = client.client.client
        imap.select_folder(folder)

        criteria = _build_imap_criteria(term, field, body_term, date_exact, date_after, date_before)
        msg_ids = imap.search(criteria)
        if not msg_ids:
            return []

        # Most recent first (highest UIDs), limited
        msg_ids = sorted(msg_ids, reverse=True)[:limit]

        fetch_data = imap.fetch(msg_ids, [b"BODY.PEEK[HEADER]"])
        results: list[dict] = []
        for uid in msg_ids:
            if uid not in fetch_data:
                continue
            header_bytes = fetch_data[uid].get(b"BODY[HEADER]")
            if not header_bytes:
                continue

            msg = email_stdlib.message_from_bytes(header_bytes, policy=email_stdlib.policy.default)
            from_name, from_addr = parseaddr(str(msg.get("From", "")))
            to_name, to_addr = parseaddr(str(msg.get("To", "")))
            subject = str(msg.get("Subject", ""))
            date_str = str(msg.get("Date", ""))
            date_iso = parse_date_to_iso(date_str)

            results.append({
                "message_id": str(uid),
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

        # Apply date post-filtering for partial dates
        results = _filter_results_by_date(results, date_exact, date_after, date_before)
        return results

    # ------------------------------------------------------------------
    # Wizard folder selection helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _pick_search_folder(client: EnhancedImapClient) -> str | None:
        """List IMAP folders and let the user pick one via partial-name search."""
        try:
            all_folders = sorted(client.client.list_folders())
        except Exception as e:
            logger.error("Could not list folders: %s", e)
            send_output(f"  Could not list folders: {e}")
            return None

        if not all_folders:
            send_output("  No folders found.")
            return None

        return folder_search_loop(all_folders)

    @staticmethod
    def _execute_wizard_search(
        client: EnhancedImapClient,
        config: ConfigManager,
        cache: SearchCache,
        *,
        mode: str,
        specific_folder: str | None,
        term: str,
        field: str,
        body_term: str | None,
        date_exact: str | None,
        date_after: str | None,
        date_before: str | None,
    ) -> list[dict]:
        """Route the wizard search based on the selected mode."""
        if mode == SEARCH_MODE_ALL:
            return EmailSearch._search_all_imap_folders(
                client, term, field, body_term,
                date_exact, date_after, date_before,
            )

        if mode == SEARCH_MODE_INBOX:
            target = FOLDER_INBOX
            return EmailSearch._search_specific_folder(
                client, config, cache, target,
                term, field, body_term,
                date_exact, date_after, date_before,
            )

        if mode == SEARCH_MODE_SENT:
            target = config.get_sent_folder()
            return EmailSearch._search_specific_folder(
                client, config, cache, target,
                term, field, body_term,
                date_exact, date_after, date_before,
            )

        if mode == SEARCH_MODE_FOLDER and specific_folder:
            return EmailSearch._search_specific_folder(
                client, config, cache, specific_folder,
                term, field, body_term,
                date_exact, date_after, date_before,
            )

        # Default mode — search cache + live folders
        cache_results = cache.search(
            term=term,
            field=field,
            body_term=body_term,
            date_exact=date_exact,
            date_after=date_after,
            date_before=date_before,
        )
        live_results = EmailSearch._search_live_folders(
            client, config, term, field, body_term,
            date_exact, date_after, date_before, None,
        )
        results = live_results + cache_results
        results.sort(key=lambda r: r.get("date_iso", ""), reverse=True)
        return results[:9]

    @staticmethod
    def _search_all_imap_folders(
        client: EnhancedImapClient,
        term: str,
        field: str,
        body_term: str | None,
        date_exact: str | None,
        date_after: str | None,
        date_before: str | None,
        limit: int = 9,
    ) -> list[dict]:
        """Search every IMAP folder with progress output."""
        try:
            all_folders = sorted(client.client.list_folders())
        except Exception as e:
            logger.error("Could not list folders: %s", e)
            send_output(f"  Could not list folders: {e}")
            return []

        results: list[dict] = []
        for i, folder in enumerate(all_folders, 1):
            send_output(f"  Searching {i}/{len(all_folders)}: {folder}")
            try:
                folder_results = EmailSearch._search_single_live_folder(
                    client, folder, term, field, body_term,
                    date_exact, date_after, date_before, limit,
                )
                results.extend(folder_results)
            except Exception as e:
                logger.error("Error searching folder '%s': %s", folder, e)

        results.sort(key=lambda r: r.get("date_iso", ""), reverse=True)
        return results[:limit]

    @staticmethod
    def _search_specific_folder(
        client: EnhancedImapClient,
        config: ConfigManager,
        cache: SearchCache,
        folder: str,
        term: str,
        field: str,
        body_term: str | None,
        date_exact: str | None,
        date_after: str | None,
        date_before: str | None,
        limit: int = 9,
    ) -> list[dict]:
        """Search a specific folder using cache, live config, or direct IMAP."""
        live_folders = config.search_live_folders

        # If folder is a live folder, search via IMAP directly
        if folder in live_folders:
            try:
                results = EmailSearch._search_single_live_folder(
                    client, folder, term, field, body_term,
                    date_exact, date_after, date_before, limit,
                )
                results.sort(key=lambda r: r.get("date_iso", ""), reverse=True)
                return results[:limit]
            except Exception as e:
                logger.error("Error searching live folder '%s': %s", folder, e)
                return []

        # Try cache first
        cache_results = cache.search(
            term=term,
            field=field,
            body_term=body_term,
            date_exact=date_exact,
            date_after=date_after,
            date_before=date_before,
            folder=folder,
        )
        if cache_results:
            cache_results.sort(key=lambda r: r.get("date_iso", ""), reverse=True)
            return cache_results[:limit]

        # Fall back to direct IMAP search
        try:
            results = EmailSearch._search_single_live_folder(
                client, folder, term, field, body_term,
                date_exact, date_after, date_before, limit,
            )
            results.sort(key=lambda r: r.get("date_iso", ""), reverse=True)
            return results[:limit]
        except Exception as e:
            logger.error("Error searching folder '%s': %s", folder, e)
            return []

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_cache(
        client: EnhancedImapClient,
        config: ConfigManager,
        cache: SearchCache,
    ) -> bool:
        """Make sure the cache has data. Prompt to build if empty."""
        if cache.has_any_data():
            return True

        build = scheduler_confirm("Cache is empty. Build it now?", default=True)
        if not build:
            send_output("Cannot search without a cache. Run --update-cache first.")
            return False

        CacheBuilder.update_cache(client, config)
        return cache.has_any_data()
