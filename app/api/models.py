"""SQLAlchemy ORM models for MasCloner."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, relationship

Base = declarative_base()


def _utc_now() -> datetime:
    """Return current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


class ConfigKV(Base):
    """Key-value configuration storage."""

    __tablename__ = "config"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)


class Run(Base):
    """Sync run execution record."""

    __tablename__ = "runs"
    __table_args__ = (
        Index("idx_runs_started_at", "started_at"),
        Index("idx_runs_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime)
    # Valid status values: running, success, error, skipped, stopped, partial
    status: Mapped[str] = mapped_column(String(20))
    num_added: Mapped[int] = mapped_column(Integer, default=0)
    num_updated: Mapped[int] = mapped_column(Integer, default=0)
    bytes_transferred: Mapped[int] = mapped_column(BigInteger, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    log_path: Mapped[Optional[str]] = mapped_column(Text)

    # Relationship
    events: Mapped[List["FileEvent"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class FileEvent(Base):
    """Individual file operation event."""

    __tablename__ = "file_events"
    __table_args__ = (
        Index("idx_file_events_run_id", "run_id"),
        Index("idx_file_events_timestamp", "timestamp"),
        Index("idx_file_events_action", "action"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(Integer, ForeignKey("runs.id"))
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    action: Mapped[str] = mapped_column(String(20))  # added|updated|skipped|error|conflict
    file_path: Mapped[str] = mapped_column(Text)
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    file_hash: Mapped[Optional[str]] = mapped_column(String(128))
    message: Mapped[Optional[str]] = mapped_column(Text)

    # Relationship
    run: Mapped[Run] = relationship(back_populates="events")
