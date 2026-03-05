"""SQLite cache for email search — stores headers and body previews for fast local queries."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from dateutil import parser as dateutil_parser
from sqlalchemy import delete, func, select, text

from src.search.models import (
    CacheMetadata,
    CalendarCache,
    EmailCache,
    SalutationCache,
    create_session_factory,
)

logger = logging.getLogger(__name__)


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


_FIELD_COLUMNS: dict[str, list[str]] = {
    "from": ["from_address", "from_name"],
    "to": ["to_address", "to_name"],
    "subject": ["subject"],
    "all": ["from_address", "from_name", "to_address", "to_name", "subject"],
}


def _build_term_conditions(term: str, field: str) -> tuple[list[str], list[str]]:
    """Build SQL conditions that AND-match each word across the relevant columns.

    Each word in *term* must appear in at least one column for the given
    *field*.  Multiple words produce one condition per word, all AND'd.
    """
    columns = _FIELD_COLUMNS.get(field, _FIELD_COLUMNS["all"])
    words = term.split()
    if not words:
        return [], []

    conditions: list[str] = []
    params: list[str] = []
    for word in words:
        like = f"%{word}%"
        or_parts = " OR ".join(f"{col} LIKE ?" for col in columns)
        conditions.append(f"({or_parts})")
        params.extend([like] * len(columns))

    return conditions, params


class SearchCache:
    """SQLAlchemy-backed email search cache."""

    def __init__(self, db_path: Path) -> None:
        """Open or create the SQLite database at *db_path*."""
        self._db_path = db_path
        self._engine, self._Session = create_session_factory(str(db_path))

    def close(self) -> None:
        """Dispose the engine and release all connections."""
        self._engine.dispose()

    # ------------------------------------------------------------------
    # Cache freshness
    # ------------------------------------------------------------------

    def is_folder_fresh(self, folder: str, max_age_days: int = 30) -> bool:
        """Return True if the folder was cached within *max_age_days*."""
        with self._Session() as session:
            meta = session.get(CacheMetadata, folder)
            if not meta:
                return False
            try:
                last = datetime.fromisoformat(meta.last_updated)
                return datetime.now() - last < timedelta(days=max_age_days)
            except (ValueError, TypeError):
                return False

    def get_stale_folders(self, all_folders: list[str], max_age_days: int) -> list[str]:
        """Return folders from *all_folders* that are missing or expired."""
        return [f for f in all_folders if not self.is_folder_fresh(f, max_age_days)]

    def get_folder_message_count(self, folder: str) -> int | None:
        """Return the cached message count for a folder, or None if not cached."""
        with self._Session() as session:
            meta = session.get(CacheMetadata, folder)
            if not meta:
                return None
            return meta.message_count

    def has_any_data(self) -> bool:
        """Return True if the cache contains at least one email."""
        with self._Session() as session:
            count = session.scalar(select(func.count(EmailCache.id)))
            return bool(count and count > 0)

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def upsert_emails(self, folder: str, emails: list[dict]) -> None:
        """Bulk insert/replace emails for *folder* and update metadata."""
        now_iso = datetime.now().isoformat()
        with self._Session() as session:
            session.execute(delete(EmailCache).where(EmailCache.folder == folder))
            session.add_all([
                EmailCache(
                    message_id=e["message_id"],
                    folder=folder,
                    from_address=e.get("from_address", ""),
                    from_name=e.get("from_name", ""),
                    to_address=e.get("to_address", ""),
                    to_name=e.get("to_name", ""),
                    subject=e.get("subject", ""),
                    date_str=e.get("date_str", ""),
                    date_iso=e.get("date_iso", ""),
                    body_preview=e.get("body_preview", ""),
                    cached_at=now_iso,
                )
                for e in emails
            ])
            session.merge(CacheMetadata(
                folder=folder,
                last_updated=now_iso,
                message_count=len(emails),
            ))
            session.commit()

    def clear_folder(self, folder: str) -> None:
        """Remove all cached emails for *folder*."""
        with self._Session() as session:
            session.execute(delete(EmailCache).where(EmailCache.folder == folder))
            session.execute(delete(CacheMetadata).where(CacheMetadata.folder == folder))
            session.commit()

    def clear_folder_by_prefix(self, folder_lower: str) -> None:
        """Remove cached data for any folder whose lowercase name matches *folder_lower*."""
        with self._Session() as session:
            session.execute(
                delete(EmailCache).where(func.lower(EmailCache.folder) == folder_lower)
            )
            session.execute(
                delete(CacheMetadata).where(func.lower(CacheMetadata.folder) == folder_lower)
            )
            session.commit()

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
        """Query the cache and return up to *limit* results sorted by date desc.

        Uses raw SQL via text() for the dynamic multi-word AND-search logic.
        """
        conditions: list[str] = []
        params: dict[str, str] = {}
        param_idx = 0

        if term:
            columns = _FIELD_COLUMNS.get(field, _FIELD_COLUMNS["all"])
            words = term.split()
            for word in words:
                like = f"%{word}%"
                or_parts_list: list[str] = []
                for col in columns:
                    pname = f"p{param_idx}"
                    or_parts_list.append(f"{col} LIKE :{pname}")
                    params[pname] = like
                    param_idx += 1
                conditions.append(f"({' OR '.join(or_parts_list)})")

        if body_term:
            pname = f"p{param_idx}"
            conditions.append(f"body_preview LIKE :{pname}")
            params[pname] = f"%{body_term}%"
            param_idx += 1

        if date_exact:
            iso = parse_user_date(date_exact)
            if iso:
                pname = f"p{param_idx}"
                conditions.append(f"date_iso LIKE :{pname}")
                params[pname] = f"{iso}%"
                param_idx += 1

        if date_after:
            iso = parse_user_date(date_after)
            if iso:
                pname = f"p{param_idx}"
                conditions.append(f"date_iso >= :{pname}")
                params[pname] = iso
                param_idx += 1

        if date_before:
            iso = parse_user_date(date_before)
            if iso:
                pname = f"p{param_idx}"
                conditions.append(f"date_iso <= :{pname}")
                params[pname] = iso
                param_idx += 1

        if folder:
            pname = f"p{param_idx}"
            conditions.append(f"folder = :{pname}")
            params[pname] = folder
            param_idx += 1

        where = " AND ".join(conditions) if conditions else "1=1"
        limit_pname = f"p{param_idx}"
        params[limit_pname] = str(limit)

        sql = text(
            f"SELECT * FROM email_cache WHERE {where} ORDER BY date_iso DESC LIMIT :{limit_pname}"
        )

        with self._Session() as session:
            rows = session.execute(sql, params).mappings().all()
            return [dict(row) for row in rows]

    # ------------------------------------------------------------------
    # Folder suggestion
    # ------------------------------------------------------------------

    def suggest_folder_for_sender(self, from_address: str) -> str | None:
        """Return the most common folder for emails from this sender, excluding INBOX."""
        if not from_address:
            return None
        sql = text(
            "SELECT folder, COUNT(*) AS cnt "
            "FROM email_cache "
            "WHERE LOWER(from_address) = LOWER(:addr) "
            "  AND LOWER(folder) != 'inbox' "
            "GROUP BY folder "
            "ORDER BY cnt DESC "
            "LIMIT 1"
        )
        with self._Session() as session:
            row = session.execute(sql, {"addr": from_address}).mappings().first()
            if row:
                return row["folder"]
            return None

    # ------------------------------------------------------------------
    # Salutation cache
    # ------------------------------------------------------------------

    def get_salutation(self, email_address: str) -> dict | None:
        """Look up cached salutation for an email address. Returns dict or None."""
        with self._Session() as session:
            row = session.execute(
                select(SalutationCache).where(
                    func.lower(SalutationCache.email_address) == email_address.lower()
                )
            ).scalar_one_or_none()
            if not row:
                return None
            return {
                "salutation": row.salutation,
                "is_formal": bool(row.is_formal),
                "skip_greeting": bool(row.skip_greeting),
            }

    def save_salutation(
        self,
        email_address: str,
        salutation: str,
        *,
        is_formal: bool = True,
        skip_greeting: bool = False,
    ) -> None:
        """Insert or update salutation for an email address."""
        now_iso = datetime.now().isoformat()
        with self._Session() as session:
            existing = session.execute(
                select(SalutationCache).where(
                    func.lower(SalutationCache.email_address) == email_address.lower()
                )
            ).scalar_one_or_none()

            if existing:
                existing.salutation = salutation
                existing.is_formal = is_formal
                existing.skip_greeting = skip_greeting
                existing.updated_at = now_iso
            else:
                session.add(SalutationCache(
                    email_address=email_address.lower(),
                    salutation=salutation,
                    is_formal=is_formal,
                    skip_greeting=skip_greeting,
                    created_at=now_iso,
                    updated_at=now_iso,
                ))
            session.commit()

    # ------------------------------------------------------------------
    # Calendar cache
    # ------------------------------------------------------------------

    def save_calendars(self, calendars: list[dict]) -> None:
        """Replace all cached calendars with the given list.

        Each dict must have 'name' and 'id' keys. Entries without an 'id' are skipped.
        """
        now_iso = datetime.now().isoformat()
        with self._Session() as session:
            session.execute(delete(CalendarCache))
            session.add_all([
                CalendarCache(
                    calendar_id=c["id"],
                    name=c.get("name", ""),
                    cached_at=now_iso,
                )
                for c in calendars if c.get("id")
            ])
            session.commit()

    def get_calendars(self) -> list[dict[str, str]]:
        """Return all cached calendars as [{name, id}, ...]."""
        with self._Session() as session:
            rows = session.execute(select(CalendarCache)).scalars().all()
            return [{"name": r.name, "id": r.calendar_id} for r in rows]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> dict:
        """Return cache statistics."""
        with self._Session() as session:
            total = session.scalar(select(func.count(EmailCache.id))) or 0
            folders = session.scalar(select(func.count(CacheMetadata.folder))) or 0
            oldest = session.scalar(select(func.min(CacheMetadata.last_updated)))
            return {
                "total_emails": total,
                "total_folders": folders,
                "oldest_cache": oldest,
            }
