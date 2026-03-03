"""Email search processor — search, wizard, cache update, and interactive results."""

from __future__ import annotations

import logging
import re
from email.utils import parseaddr

from imap_client_lib import EmailMessage

from src.config.settings import ConfigManager
from src.email.imap_client import EnhancedImapClient
from src.interaction.scheduler_prompts import (
    scheduler_ask,
    scheduler_choose,
    scheduler_confirm,
    send_output,
)
from src.search.search_cache import SearchCache, parse_date_to_iso

logger = logging.getLogger(__name__)


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
            if not EmailSearch._ensure_cache(client, config, cache):
                return

            field, term = EmailSearch._parse_search_term(search_term or "")
            results = cache.search(
                term=term or None,
                field=field,
                body_term=body_term,
                date_exact=date,
                date_after=date_after,
                date_before=date_before,
                folder=path,
            )

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
            scope_options = [
                "All (from, to, subject)",
                "From only",
                "To only",
                "Subject only",
            ]
            scope_idx = scheduler_choose("Search scope:", scope_options, default=0)
            field_map = ["all", "from", "to", "subject"]
            field = field_map[scope_idx]

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

            # 5. Execute
            results = cache.search(
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

    @staticmethod
    def update_cache(
        client: EnhancedImapClient,
        config: ConfigManager,
        folders_filter: str | None = None,
    ) -> None:
        """Build or rebuild the SQLite cache from IMAP."""
        cache = SearchCache(config.search_cache_path)
        try:
            if folders_filter:
                target_folders = [f.strip() for f in folders_filter.split(";") if f.strip()]
            else:
                target_folders = client.client.list_folders()
                if not target_folders:
                    send_output("Could not list IMAP folders.")
                    return

            send_output(f"Caching {len(target_folders)} folder(s)...")
            total = 0
            for folder in target_folders:
                count = EmailSearch._cache_folder(client, cache, folder)
                total += count
                send_output(f"  {folder}: {count} email(s)")

            stats = cache.get_stats()
            send_output(
                f"\nCache complete: {stats['total_emails']} emails "
                f"in {stats['total_folders']} folder(s)"
            )
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
    # Cache helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_folder(
        client: EnhancedImapClient,
        cache: SearchCache,
        folder: str,
    ) -> int:
        """Cache all emails in one IMAP folder. Returns the count."""
        try:
            messages = client.client.get_all_messages(
                folder=folder, limit=None, include_attachments=False,
            )
        except Exception as e:
            logger.warning("Could not fetch folder '%s': %s", folder, e)
            return 0

        if not messages:
            cache.upsert_emails(folder, [])
            return 0

        rows: list[dict] = []
        for msg_id, email_msg in messages:
            from_name, from_addr = parseaddr(email_msg.from_address or "")
            to_raw = email_msg.raw_message.get("To", "") if email_msg.raw_message else ""
            to_name, to_addr = parseaddr(to_raw)

            body = _extract_body_preview(email_msg)
            date_iso = parse_date_to_iso(email_msg.date or "")

            rows.append({
                "message_id": str(msg_id),
                "from_address": from_addr,
                "from_name": from_name,
                "to_address": to_addr,
                "to_name": to_name,
                "subject": email_msg.subject or "",
                "date_str": email_msg.date or "",
                "date_iso": date_iso,
                "body_preview": body,
            })

        cache.upsert_emails(folder, rows)
        return len(rows)

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

        EmailSearch.update_cache(client, config)
        return cache.has_any_data()


def _extract_body_preview(email_msg: EmailMessage) -> str:
    """Extract first 2000 characters of the email body."""
    try:
        body = email_msg.get_body("text/plain")
        if not body:
            html = email_msg.get_body("text/html")
            if html:
                body = re.sub(r"<[^>]+>", "", html).strip()
        return (body or "")[:2000]
    except Exception:
        return ""
