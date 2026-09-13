"""Models for history retention policy and execution reports (ADR 0008)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RetentionReport(BaseModel):
    """Structured report of a retention operation pass."""

    model_config = ConfigDict(frozen=True)

    started_at: datetime = Field(default_factory=_utc_now)
    finished_at: datetime = Field(default_factory=_utc_now)
    cutoff_utc: datetime
    retention_days: int
    runs_evaluated: int = 0
    runs_deleted: int = 0
    events_deleted: int = 0
    logs_deleted: int = 0
    log_deletion_failures: List[str] = Field(default_factory=list)
    is_dry_run: bool = False
    success: bool = True
    error: Optional[str] = None

    @property
    def duration_seconds(self) -> float:
        return max(0.0, (self.finished_at - self.started_at).total_seconds())
