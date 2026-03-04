"""Cache builder — fetches emails from IMAP and populates the SQLite search cache."""

from __future__ import annotations

import logging
import re
from email.utils import parseaddr

from imap_client_lib import EmailMessage

from src.config.settings import ConfigManager
from src.constants import MIME_TEXT_HTML, MIME_TEXT_PLAIN
from src.email.imap_client import EnhancedImapClient
from src.interaction.scheduler_prompts import send_output
from src.search.search_cache import SearchCache, parse_date_to_iso

logger = logging.getLogger(__name__)


class CacheBuilder:
    """Builds and refreshes the SQLite email search cache from IMAP."""

    @staticmethod
    def update_cache(
        client: EnhancedImapClient,
        config: ConfigManager,
        folders_filter: str | None = None,
        *,
        fast: bool = False,
    ) -> None:
        """Build or rebuild the SQLite cache from IMAP.

        When *fast* is True, folders whose IMAP message count matches the
        cached count are skipped entirely.
        """
        cache = SearchCache(config.search_cache_path)
        try:
            if folders_filter:
                target_folders = [f.strip() for f in folders_filter.split(";") if f.strip()]
            else:
                target_folders = client.client.list_folders()
                if not target_folders:
                    send_output("Could not list IMAP folders.")
                    return

            exclude = [e.lower() for e in config.search_exclude_folders]
            # Also exclude live-search folders — they're searched via IMAP directly
            live = [f.lower() for f in config.search_live_folders]
            exclude = list(set(exclude + live))
            if exclude:
                before = len(target_folders)
                target_folders = [f for f in target_folders if f.lower() not in exclude]
                skipped = before - len(target_folders)
                if skipped:
                    send_output(f"Skipping {skipped} excluded folder(s).")

                # Purge stale data for excluded folders from the cache
                for folder_lower in exclude:
                    cache.clear_folder_by_prefix(folder_lower)

            send_output(f"Caching {len(target_folders)} folder(s)...")
            total = 0
            unchanged = 0
            for folder in target_folders:
                if fast:
                    imap_count = client.client.get_folder_message_count(folder)
                    cached_count = cache.get_folder_message_count(folder)
                    if imap_count is not None and imap_count == cached_count:
                        send_output(f"  {folder}: unchanged ({imap_count})")
                        total += imap_count
                        unchanged += 1
                        continue

                send_output(f"  {folder}: fetching...")
                count = CacheBuilder._cache_folder(client, cache, folder)
                total += count
                send_output(f"  {folder}: {count} email(s)")

            if fast and unchanged:
                send_output(f"\n{unchanged} folder(s) unchanged, skipped.")

            stats = cache.get_stats()
            send_output(
                f"\nCache complete: {stats['total_emails']} emails "
                f"in {stats['total_folders']} folder(s)"
            )
        finally:
            cache.close()

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

        total = len(messages)
        rows: list[dict] = []
        for i, (msg_id, email_msg) in enumerate(messages, 1):
            send_output(f"  {folder}: processing email {i}/{total}")
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


def _extract_body_preview(email_msg: EmailMessage) -> str:
    """Extract first 2000 characters of the email body."""
    try:
        body = email_msg.get_body(MIME_TEXT_PLAIN)
        if not body:
            html = email_msg.get_body(MIME_TEXT_HTML)
            if html:
                body = re.sub(r"<[^>]+>", "", html).strip()
        return (body or "")[:2000]
    except Exception:
        return ""
