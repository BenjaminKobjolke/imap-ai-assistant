"""SQLite cache for email search — stores headers and body previews for fast local queries."""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from dateutil import parser as dateutil_parser

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS email_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL,
    folder TEXT NOT NULL,
    from_address TEXT DEFAULT '',
    from_name TEXT DEFAULT '',
    to_address TEXT DEFAULT '',
    to_name TEXT DEFAULT '',
    subject TEXT DEFAULT '',
    date_str TEXT DEFAULT '',
    date_iso TEXT DEFAULT '',
    body_preview TEXT DEFAULT '',
    cached_at TEXT NOT NULL,
    UNIQUE(folder, message_id)
);

CREATE TABLE IF NOT EXISTS cache_metadata (
    folder TEXT PRIMARY KEY,
    last_updated TEXT NOT NULL,
    message_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_email_cache_date_iso ON email_cache(date_iso);
CREATE INDEX IF NOT EXISTS idx_email_cache_folder ON email_cache(folder);
"""


def parse_date_to_iso(date_str: str) -> str:
    """Parse an email date string into ISO 8601 format (YYYY-MM-DD).

    Returns empty string if parsing fails.
    """
    if not date_str:
        return ""
    try:
        dt = dateutil_parser.parse(date_str, fuzzy=True)
        return str(dt.strftime("%Y-%m-%d"))
    except (ValueError, OverflowError):
        return ""


def parse_user_date(raw: str) -> str:
    """Parse user-supplied date (DD.MM.YYYY, MM.YYYY, YYYY) into ISO prefix.

    Returns a string suitable for SQL LIKE or comparison:
    - DD.MM.YYYY → 'YYYY-MM-DD'
    - MM.YYYY → 'YYYY-MM'
    - YYYY → 'YYYY'
    """
    raw = raw.strip()
    if not raw:
        return ""

    # DD.MM.YYYY
    m = re.match(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})$", raw)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return f"{year:04d}-{month:02d}-{day:02d}"

    # MM.YYYY
    m = re.match(r"^(\d{1,2})\.(\d{4})$", raw)
    if m:
        month, year = int(m.group(1)), int(m.group(2))
        return f"{year:04d}-{month:02d}"

    # YYYY
    m = re.match(r"^(\d{4})$", raw)
    if m:
        return m.group(1)

    return ""


class SearchCache:
    """SQLite-backed email search cache."""

    def __init__(self, db_path: Path) -> None:
        """Open or create the SQLite database at *db_path*."""
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    # ------------------------------------------------------------------
    # Cache freshness
    # ------------------------------------------------------------------

    def is_folder_fresh(self, folder: str, max_age_days: int = 30) -> bool:
        """Return True if the folder was cached within *max_age_days*."""
        row = self._conn.execute(
            "SELECT last_updated FROM cache_metadata WHERE folder = ?", (folder,)
        ).fetchone()
        if not row:
            return False
        try:
            last = datetime.fromisoformat(row["last_updated"])
            return datetime.now() - last < timedelta(days=max_age_days)
        except (ValueError, TypeError):
            return False

    def get_stale_folders(self, all_folders: list[str], max_age_days: int) -> list[str]:
        """Return folders from *all_folders* that are missing or expired."""
        return [f for f in all_folders if not self.is_folder_fresh(f, max_age_days)]

    def get_folder_message_count(self, folder: str) -> int | None:
        """Return the cached message count for a folder, or None if not cached."""
        row = self._conn.execute(
            "SELECT message_count FROM cache_metadata WHERE folder = ?", (folder,)
        ).fetchone()
        if not row:
            return None
        return row["message_count"]

    def has_any_data(self) -> bool:
        """Return True if the cache contains at least one email."""
        row = self._conn.execute("SELECT COUNT(*) AS cnt FROM email_cache").fetchone()
        return bool(row and row["cnt"] > 0)

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def upsert_emails(self, folder: str, emails: list[dict]) -> None:
        """Bulk insert/replace emails for *folder* and update metadata."""
        now_iso = datetime.now().isoformat()
        self._conn.execute("DELETE FROM email_cache WHERE folder = ?", (folder,))
        self._conn.executemany(
            """INSERT INTO email_cache
               (message_id, folder, from_address, from_name,
                to_address, to_name, subject, date_str, date_iso,
                body_preview, cached_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                (
                    e["message_id"], folder, e.get("from_address", ""),
                    e.get("from_name", ""), e.get("to_address", ""),
                    e.get("to_name", ""), e.get("subject", ""),
                    e.get("date_str", ""), e.get("date_iso", ""),
                    e.get("body_preview", ""), now_iso,
                )
                for e in emails
            ],
        )
        self._conn.execute(
            """INSERT OR REPLACE INTO cache_metadata (folder, last_updated, message_count)
               VALUES (?, ?, ?)""",
            (folder, now_iso, len(emails)),
        )
        self._conn.commit()

    def clear_folder(self, folder: str) -> None:
        """Remove all cached emails for *folder*."""
        self._conn.execute("DELETE FROM email_cache WHERE folder = ?", (folder,))
        self._conn.execute("DELETE FROM cache_metadata WHERE folder = ?", (folder,))
        self._conn.commit()

    def clear_folder_by_prefix(self, folder_lower: str) -> None:
        """Remove cached data for any folder whose lowercase name matches *folder_lower*."""
        self._conn.execute("DELETE FROM email_cache WHERE LOWER(folder) = ?", (folder_lower,))
        self._conn.execute("DELETE FROM cache_metadata WHERE LOWER(folder) = ?", (folder_lower,))
        self._conn.commit()

    # ------------------------------------------------------------------
    # Searching
    # ------------------------------------------------------------------

    def search(
        self,
        term: str | None = None,
        field: str = "all",
        body_term: str | None = None,
        date_exact: str | None = None,
        date_after: str | None = None,
        date_before: str | None = None,
        folder: str | None = None,
        limit: int = 9,
    ) -> list[dict]:
        """Query the cache and return up to *limit* results sorted by date desc."""
        conditions: list[str] = []
        params: list[str] = []

        if term:
            like = f"%{term}%"
            if field == "from":
                conditions.append("(from_address LIKE ? OR from_name LIKE ?)")
                params.extend([like, like])
            elif field == "to":
                conditions.append("(to_address LIKE ? OR to_name LIKE ?)")
                params.extend([like, like])
            elif field == "subject":
                conditions.append("subject LIKE ?")
                params.append(like)
            else:  # "all"
                conditions.append(
                    "(from_address LIKE ? OR from_name LIKE ? "
                    "OR to_address LIKE ? OR to_name LIKE ? "
                    "OR subject LIKE ?)"
                )
                params.extend([like, like, like, like, like])

        if body_term:
            conditions.append("body_preview LIKE ?")
            params.append(f"%{body_term}%")

        if date_exact:
            iso = parse_user_date(date_exact)
            if iso:
                conditions.append("date_iso LIKE ?")
                params.append(f"{iso}%")

        if date_after:
            iso = parse_user_date(date_after)
            if iso:
                conditions.append("date_iso >= ?")
                params.append(iso)

        if date_before:
            iso = parse_user_date(date_before)
            if iso:
                conditions.append("date_iso <= ?")
                params.append(iso)

        if folder:
            conditions.append("folder = ?")
            params.append(folder)

        where = " AND ".join(conditions) if conditions else "1=1"
        sql = f"SELECT * FROM email_cache WHERE {where} ORDER BY date_iso DESC LIMIT ?"
        params.append(str(limit))

        rows = self._conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Return cache statistics."""
        total = self._conn.execute("SELECT COUNT(*) AS cnt FROM email_cache").fetchone()
        folders = self._conn.execute("SELECT COUNT(*) AS cnt FROM cache_metadata").fetchone()
        oldest = self._conn.execute(
            "SELECT MIN(last_updated) AS oldest FROM cache_metadata"
        ).fetchone()
        return {
            "total_emails": total["cnt"] if total else 0,
            "total_folders": folders["cnt"] if folders else 0,
            "oldest_cache": oldest["oldest"] if oldest else None,
        }
