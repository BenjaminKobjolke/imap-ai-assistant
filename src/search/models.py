"""SQLAlchemy ORM models for the email search cache database."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import Boolean, Index, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class EmailCache(Base):
    """Cached email header and body preview."""

    __tablename__ = "email_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[str] = mapped_column(String, nullable=False)
    folder: Mapped[str] = mapped_column(String, nullable=False)
    from_address: Mapped[str] = mapped_column(String, default="")
    from_name: Mapped[str] = mapped_column(String, default="")
    to_address: Mapped[str] = mapped_column(String, default="")
    to_name: Mapped[str] = mapped_column(String, default="")
    subject: Mapped[str] = mapped_column(String, default="")
    date_str: Mapped[str] = mapped_column(String, default="")
    date_iso: Mapped[str] = mapped_column(String, default="")
    body_preview: Mapped[str] = mapped_column(Text, default="")
    cached_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("folder", "message_id", name="uq_folder_message_id"),
        Index("idx_email_cache_date_iso", "date_iso"),
        Index("idx_email_cache_folder", "folder"),
    )


class CacheMetadata(Base):
    """Per-folder cache freshness metadata."""

    __tablename__ = "cache_metadata"

    folder: Mapped[str] = mapped_column(String, primary_key=True)
    last_updated: Mapped[str] = mapped_column(String, nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, default=0)


class SalutationCache(Base):
    """Cached salutation for an email address."""

    __tablename__ = "salutation_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email_address: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    salutation: Mapped[str] = mapped_column(String, nullable=False, default="")
    is_formal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    skip_greeting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[str] = mapped_column(String, nullable=False)
    updated_at: Mapped[str] = mapped_column(String, nullable=False)

    __table_args__ = (
        Index("idx_salutation_email", "email_address"),
    )


class CalendarCache(Base):
    """Cached Google Calendar name and ID."""

    __tablename__ = "calendar_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    calendar_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False, default="")
    cached_at: Mapped[str] = mapped_column(String, nullable=False)


def create_session_factory(db_path: str) -> tuple:
    """Create a SQLAlchemy engine and session factory for the given database path.

    For ':memory:' paths, uses StaticPool so all sessions share the same
    in-memory database.  For file paths, uses the default pool.

    Returns (engine, SessionFactory).
    """
    if db_path == ":memory:":
        engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    else:
        db_file = Path(db_path)
        db_file.parent.mkdir(parents=True, exist_ok=True)
        engine = create_engine(f"sqlite:///{db_path}")

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    return engine, session_factory
