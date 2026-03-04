"""Email search processor — search, wizard, and interactive results."""

from __future__ import annotations

import email as email_stdlib
import email.policy
import logging
import re
from datetime import datetime
from email.utils import parseaddr

from imap_client_lib import EmailMessage

from src.config.settings import ConfigManager
from src.email.imap_client import EnhancedImapClient
from src.interaction.scheduler_prompts import (
    SchedulerChoice,
    scheduler_ask,
    scheduler_choose,
    scheduler_confirm,
    send_output,
)
from src.search.cache_builder import CacheBuilder
from src.search.search_cache import SearchCache, parse_date_to_iso, parse_user_date

logger = logging.getLogger(__name__)


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
        criteria.extend([imap_field, term])
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
            if not EmailSearch._ensure_cache(client, config, cache):
                return

            # 1. Search scope
            field = SchedulerChoice("Search scope:", [
                ("All (from, to, subject)", "all"),
                ("From only", "from"),
                ("To only", "to"),
                ("Subject only", "subject"),
            ]).choose()

            # 2. Search term
            term = scheduler_ask("Search term:", default="")
            if not term:
                send_output("No search term provided.")
                return

            # 3. Body search
            body_raw = scheduler_ask("Body contains (leave empty to skip):", default="")
            body_term: str | None = body_raw if body_raw else None

            # 4. Date filter
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

            # 5. Execute — search cache and live folders
            cache_results = cache.search(
                term=term,
                field=field,
                body_term=body_term,
                date_exact=date_exact or None,
                date_after=date_after or None,
                date_before=date_before or None,
            )

            live_results = EmailSearch._search_live_folders(
                client, config, term, field, body_term,
                date_exact or None, date_after or None,
                date_before or None, None,
            )

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
        while True:
            actions = ["Show body", "Copy to search-results", "Back to results"]
            action_idx = scheduler_choose("Action:", actions, default=2)

            if action_idx == 0:
                EmailSearch._show_body(result, client)
            elif action_idx == 1:
                EmailSearch._copy_to_results_folder(result, client, config)
                return
            else:
                return

    # ------------------------------------------------------------------
    # Body fetching
    # ------------------------------------------------------------------

    @staticmethod
    def _show_body(result: dict, client: EnhancedImapClient) -> None:
        """Fetch and display the full body from IMAP."""
        folder = result.get("folder", "INBOX")
        msg_id = result.get("message_id", "")

        try:
            client.client.client.select_folder(folder)
            raw = client.client.client.fetch([int(msg_id)], [b"BODY.PEEK[]"])
            if not raw:
                send_output("  Could not fetch email body.")
                return

            msg_data = raw[int(msg_id)][b"BODY[]"]
            email_msg = EmailMessage.from_bytes(msg_id, msg_data, include_attachments=False)
            body = email_msg.get_body("text/plain")

            if not body:
                html = email_msg.get_body("text/html")
                if html:
                    body = re.sub(r"<[^>]+>", "", html).strip()

            if body:
                send_output(f"\n{'─' * 50}")
                send_output(body)
                send_output(f"{'─' * 50}\n")
            else:
                send_output("  (empty body)")
        except Exception as e:
            logger.error("Error fetching email body: %s", e)
            send_output(f"  Error fetching body: {e}")

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
        folder = result.get("folder", "INBOX")
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
