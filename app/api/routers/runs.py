"""Sync runs and file events endpoints."""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..dependencies import get_scheduler
from ..exceptions import DatabaseError, NotFoundError, SchedulerError
from ..models import FileEvent, Run
from ..scheduler import SyncScheduler
from ..schemas import ApiResponse, FileEventResponse, RunResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=List[RunResponse])
async def get_runs(limit: int = 20, db: Session = Depends(get_db)):
    """Get recent sync runs."""
    try:
        runs = (
            db.execute(select(Run).order_by(desc(Run.id)).limit(limit))
            .scalars()
            .all()
        )
        return [
            RunResponse(
                id=run.id,
                status=run.status,
                started_at=run.started_at.isoformat(),
                finished_at=run.finished_at.isoformat() if run.finished_at else None,
                num_added=run.num_added,
                num_updated=run.num_updated,
                bytes_transferred=run.bytes_transferred,
                errors=run.errors,
                log_path=run.log_path,
            )
            for run in runs
        ]
    except Exception as exc:
        logger.error("Failed to get runs: %s", exc)
        raise DatabaseError(f"Failed to get runs: {exc}", operation="get_runs")


@router.get("/{run_id}/events", response_model=List[FileEventResponse])
async def get_run_events(run_id: int, limit: int = 200, db: Session = Depends(get_db)):
    """Get file events for a specific run."""
    try:
        run = db.execute(select(Run).where(Run.id == run_id)).scalars().first()
        if not run:
            raise NotFoundError("Run", run_id)

        events = (
            db.execute(
                select(FileEvent)
                .where(FileEvent.run_id == run_id)
                .order_by(desc(FileEvent.id))
                .limit(limit)
            )
            .scalars()
            .all()
        )

        return [
            FileEventResponse(
                id=event.id,
                timestamp=event.timestamp.isoformat(),
                action=event.action,
                file_path=event.file_path,
                file_size=event.file_size,
                file_hash=event.file_hash,
                message=event.message,
            )
            for event in events
        ]
    except NotFoundError:
        raise
    except Exception as exc:
        logger.error("Failed to get run events: %s", exc)
        raise DatabaseError(f"Failed to get run events: {exc}", operation="get_run_events")


@router.post("", response_model=ApiResponse)
async def trigger_sync(scheduler: SyncScheduler = Depends(get_scheduler)):
    """Trigger a manual sync run."""
    try:
        if scheduler.trigger_sync_now():
            return ApiResponse(success=True, message="Sync triggered successfully")
        raise SchedulerError("Failed to trigger sync", operation="trigger_sync")
    except SchedulerError:
        raise
    except Exception as exc:
        logger.error("Failed to trigger sync: %s", exc)
        raise SchedulerError(f"Failed to trigger sync: {exc}", operation="trigger_sync")


# Events endpoints (without run_id prefix)
events_router = APIRouter(prefix="/events", tags=["events"])


@events_router.get("", response_model=List[FileEventResponse])
async def get_events(limit: int = 200, db: Session = Depends(get_db)):
    """Get recent file events across all runs."""
    try:
        events = (
            db.execute(select(FileEvent).order_by(desc(FileEvent.id)).limit(limit))
            .scalars()
            .all()
        )
        return [
            FileEventResponse(
                id=event.id,
                timestamp=event.timestamp.isoformat(),
                action=event.action,
                file_path=event.file_path,
                file_size=event.file_size,
                file_hash=event.file_hash,
                message=event.message,
            )
            for event in events
        ]
    except Exception as exc:
        logger.error("Failed to get events: %s", exc)
        raise DatabaseError(f"Failed to get events: {exc}", operation="get_events")

