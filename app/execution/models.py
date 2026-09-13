"""Domain models for the SyncExecutor module (ADR 0005, ADR 0007)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class FileEventEntry(BaseModel):
    """File operation event produced during sync execution."""

    model_config = ConfigDict(frozen=True)

    action: str
    file_path: str
    file_size: int = 0
    timestamp: datetime
    file_hash: Optional[str] = None
    message: Optional[str] = None


class ActiveRunSnapshot(BaseModel):
    """Real-time consolidated summary of an active or recent sync run."""

    model_config = ConfigDict(frozen=True)

    run_id: int
    status: str
    started_at: datetime
    is_active: bool = True
    bytes_transferred: int = 0
    total_bytes: Optional[int] = None
    percentage: Optional[float] = None
    speed_bps: Optional[int] = None
    current_file: Optional[str] = None
    files_transferred: int = 0
    total_files: Optional[int] = None
    eta_seconds: Optional[int] = None
    errors: int = 0
    recent_events: List[Dict[str, Any]] = Field(default_factory=list)
    message: Optional[str] = None


class TriggerResult(BaseModel):
    """Outcome of attempting to trigger a SyncRun."""

    model_config = ConfigDict(frozen=True)

    accepted: bool
    run_id: Optional[int] = None
    status: str
    message: str


class AbortResult(BaseModel):
    """Outcome of requesting an abort on an active SyncRun."""

    model_config = ConfigDict(frozen=True)

    requested: bool
    run_id: Optional[int] = None
    message: str
