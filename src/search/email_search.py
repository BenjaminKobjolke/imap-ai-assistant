"""Email search processor — search, wizard, and interactive results."""

from __future__ import annotations

import logging

from src.config.settings import ConfigManager
from src.constants import (
    FOLDER_INBOX,
    SEARCH_MODE_ALL,
    SEARCH_MODE_DEFAULT,
    SEARCH_MODE_FOLDER,
    SEARCH_MODE_INBOX,
    SEARCH_MODE_SENT,
)
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
from src.search.live_imap_search import LiveImapSearch
from src.search.search_cache import SearchCache
from src.search.search_results_view import SearchResultsView

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
            live_results = LiveImapSearch.search_live_folders(
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

            SearchResultsView.display_results(results)
            SearchResultsView.result_detail_loop(results, client, config)
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
                    SearchResultsView.list_all_emails(client, config, specific_folder)
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

            SearchResultsView.display_results(results)
            SearchResultsView.result_detail_loop(results, client, config)
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
            return LiveImapSearch.search_all_imap_folders(
                client, term, field, body_term,
                date_exact, date_after, date_before,
            )

        if mode == SEARCH_MODE_INBOX:
            target = FOLDER_INBOX
            return LiveImapSearch.search_specific_folder(
                client, config, cache, target,
                term, field, body_term,
                date_exact, date_after, date_before,
            )

        if mode == SEARCH_MODE_SENT:
            target = config.get_sent_folder()
            return LiveImapSearch.search_specific_folder(
                client, config, cache, target,
                term, field, body_term,
                date_exact, date_after, date_before,
            )

        if mode == SEARCH_MODE_FOLDER and specific_folder:
            return LiveImapSearch.search_specific_folder(
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
        live_results = LiveImapSearch.search_live_folders(
            client, config, term, field, body_term,
            date_exact, date_after, date_before, None,
        )
        results = live_results + cache_results
        results.sort(key=lambda r: r.get("date_iso", ""), reverse=True)
        return results[:9]



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
