"""SQLAlchemy ORM models for MasCloner."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, List, Optional, Set, Dict

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, declarative_base, mapped_column, relationship

Base = declarative_base()

class SyncStatus(StrEnum):
    """Canonical lifecycle states for synchronization runs."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"
    SKIPPED = "skipped"

    @classmethod
    def is_terminal(cls, status: str | SyncStatus) -> bool:
        s = str(status).lower()
        return s in (cls.COMPLETED, cls.FAILED, cls.ABORTED, cls.SKIPPED)


ALLOWED_TRANSITIONS: Dict[str, Set[str]] = {
    SyncStatus.PENDING: {
        SyncStatus.RUNNING,
        SyncStatus.FAILED,
        SyncStatus.ABORTED,
        SyncStatus.SKIPPED,
    },
    SyncStatus.RUNNING: {
        SyncStatus.COMPLETED,
        SyncStatus.FAILED,
        SyncStatus.ABORTED,
    },
}


def _normalize_status(val: Any) -> str:
    if hasattr(val, "value"):
        return str(val.value).lower()
    return str(val).lower()


def validate_status_transition(current_status: str | SyncStatus, new_status: str | SyncStatus) -> str:
    """Validate lifecycle transition between run statuses."""
    curr = _normalize_status(current_status)
    nxt = _normalize_status(new_status)

    if curr == nxt:
        return nxt

    allowed = ALLOWED_TRANSITIONS.get(curr, set())
    if nxt not in allowed:
        raise ValueError(
            f"Invalid status transition from {curr!r} to {nxt!r}. "
            f"Allowed next states: {sorted(allowed) or 'none (terminal state)'}"
        )
    return nxt


def _utc_now() -> datetime:
    """Return current UTC time (timezone-aware)."""
    return datetime.now(timezone.utc)


class ConfigKV(Base):
    """Key-value configuration storage."""

    __tablename__ = "config"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utc_now)
    provenance: Mapped[Optional[str]] = mapped_column(String(50), default="user", nullable=True)


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
    # Canonical status: pending, running, completed, failed, aborted, skipped
    status: Mapped[str] = mapped_column(String(20), default=SyncStatus.PENDING)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    num_added: Mapped[int] = mapped_column(Integer, default=0)
    num_updated: Mapped[int] = mapped_column(Integer, default=0)
    bytes_transferred: Mapped[int] = mapped_column(BigInteger, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)
    log_path: Mapped[Optional[str]] = mapped_column(Text)

    def transition_to(self, new_status: str | SyncStatus, message: Optional[str] = None) -> None:
        """Transition status enforcing lifecycle state constraints."""
        target = validate_status_transition(self.status, str(new_status))
        self.status = target
        if message is not None:
            self.message = message

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
