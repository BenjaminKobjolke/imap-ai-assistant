"""Live IMAP search helpers and folder search operations."""

from __future__ import annotations

import email as email_stdlib
import email.policy
import logging
from datetime import datetime
from email.utils import parseaddr

from src.config.settings import ConfigManager
from src.email.imap_client import EnhancedImapClient
from src.interaction.scheduler_prompts import send_output
from src.search.search_cache import SearchCache, parse_date_to_iso, parse_user_date

logger = logging.getLogger(__name__)


def _iso_to_imap_date(iso_date: str) -> str | None:
    """Convert ISO date (YYYY-MM-DD) to IMAP date format (DD-Mon-YYYY)."""
    try:
        dt = datetime.strptime(iso_date[:10], "%Y-%m-%d")
        return dt.strftime("%d-%b-%Y")
    except (ValueError, IndexError):
        return None


def build_imap_criteria(
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


def filter_results_by_date(
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



class LiveImapSearch:
    """Search live IMAP folders separately from cached search presentation."""

    @staticmethod
    def search_live_folders(
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
                folder_results = LiveImapSearch.search_single_live_folder(
                    client, folder, term, field, body_term,
                    date_exact, date_after, date_before, limit,
                )
                results.extend(folder_results)
            except Exception as e:
                logger.error("Error searching live folder '%s': %s", folder, e)

        return results


    @staticmethod
    def search_single_live_folder(
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

        criteria = build_imap_criteria(term, field, body_term, date_exact, date_after, date_before)
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
        results = filter_results_by_date(results, date_exact, date_after, date_before)
        return results


    @staticmethod
    def search_all_imap_folders(
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
                folder_results = LiveImapSearch.search_single_live_folder(
                    client, folder, term, field, body_term,
                    date_exact, date_after, date_before, limit,
                )
                results.extend(folder_results)
            except Exception as e:
                logger.error("Error searching folder '%s': %s", folder, e)

        results.sort(key=lambda r: r.get("date_iso", ""), reverse=True)
        return results[:limit]


    @staticmethod
    def search_specific_folder(
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
                results = LiveImapSearch.search_single_live_folder(
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
            results = LiveImapSearch.search_single_live_folder(
                client, folder, term, field, body_term,
                date_exact, date_after, date_before, limit,
            )
            results.sort(key=lambda r: r.get("date_iso", ""), reverse=True)
            return results[:limit]
        except Exception as e:
            logger.error("Error searching folder '%s': %s", folder, e)
            return []

