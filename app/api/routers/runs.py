"""Sync runs and file events endpoints."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..exceptions import DatabaseError, NotFoundError, SchedulerError
from ..models import FileEvent, Run, SyncStatus
from ..schemas import ApiResponse, FileEventResponse, RunResponse
from ...execution import SyncExecutor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("", response_model=List[RunResponse])
async def get_runs(
    limit: int = 20,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
) -> List[RunResponse]:
    """Get recent sync runs, optionally filtered by status."""
    try:
        stmt = select(Run)
        if status:
            stmt = stmt.where(Run.status == status.lower())
        runs = (
            db.execute(stmt.order_by(desc(Run.id)).limit(limit))
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
                message=getattr(run, "message", None),
            )
            for run in runs
        ]
    except Exception as exc:
        logger.error("Failed to get runs: %s", exc)
        raise DatabaseError(f"Failed to get runs: {exc}", operation="get_runs")


# Live monitoring endpoints - must be before /{run_id} patterns!
@router.get("/current")
async def get_current_run(
    db: Session = Depends(get_db),
) -> Optional[Dict[str, Any]]:
    """Get currently running sync if any.

    Returns run information and live monitoring data, or null if no sync running.
    """
    try:
        executor = SyncExecutor.get_instance()
        snapshot = executor.get_active_snapshot()
        if snapshot and snapshot.is_active:
            return {
                "id": snapshot.run_id,
                "status": snapshot.status,
                "started_at": snapshot.started_at.isoformat(),
                "num_added": snapshot.files_transferred,
                "num_updated": 0,
                "bytes_transferred": snapshot.bytes_transferred,
                "errors": snapshot.errors,
                "log_path": None,
                "is_process_running": True,
                "percentage": snapshot.percentage,
                "speed_bps": snapshot.speed_bps,
                "recent_events": snapshot.recent_events,
            }

        # Check database for running status
        current_run = (
            db.execute(
                select(Run)
                .where(Run.status == SyncStatus.RUNNING)
                .order_by(desc(Run.started_at))
            )
            .scalars()
            .first()
        )

        if not current_run:
            return None

        return {
            "id": current_run.id,
            "status": current_run.status,
            "started_at": current_run.started_at.isoformat(),
            "num_added": current_run.num_added,
            "num_updated": current_run.num_updated,
            "bytes_transferred": current_run.bytes_transferred,
            "errors": current_run.errors,
            "log_path": current_run.log_path,
            "is_process_running": False,
        }
    except Exception as exc:
        logger.error("Failed to get current run: %s", exc)
        raise DatabaseError(f"Failed to get current run: {exc}", operation="get_current_run")


@router.get("/{run_id}/logs")
async def get_run_logs(
    run_id: int,
    since: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Get log lines for a running or completed sync."""
    try:
        # Verify run exists
        run = db.execute(select(Run).where(Run.id == run_id)).scalars().first()
        if not run:
            raise NotFoundError("Run", run_id)

        executor = SyncExecutor.get_instance()
        logs, next_line, is_live = executor.tail_log_file(run_id, since_line=since, limit=limit)
        return {
            "run_id": run_id,
            "logs": logs,
            "next_line": next_line,
            "is_live": is_live,
        }
    except NotFoundError:
        raise
    except Exception as exc:
        logger.error("Failed to get run logs: %s", exc)
        raise DatabaseError(f"Failed to get run logs: {exc}", operation="get_run_logs")


@router.post("/{run_id}/stop")
async def stop_run(
    run_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Request graceful stop of a running sync."""
    try:
        # Verify run exists and is running
        run = db.execute(select(Run).where(Run.id == run_id)).scalars().first()
        if not run:
            raise NotFoundError("Run", run_id)

        if run.status != SyncStatus.RUNNING:
            raise HTTPException(
                status_code=400,
                detail=f"Run {run_id} is not running (status: {run.status})",
            )

        executor = SyncExecutor.get_instance()
        if executor.get_active_run_id() == run_id:
            abort_res = executor.request_abort(run_id)
            if abort_res.requested:
                return {
                    "success": True,
                    "message": abort_res.message,
                    "run_id": run_id,
                }
            raise HTTPException(
                status_code=400,
                detail=abort_res.message,
            )

        raise HTTPException(
            status_code=400,
            detail="Run is not the currently active sync process",
        )
    except (NotFoundError, HTTPException):
        raise
    except Exception as exc:
        logger.error("Failed to stop run: %s", exc)
        raise DatabaseError(f"Failed to stop run: {exc}", operation="stop_run")


@router.get("/{run_id}/events", response_model=List[FileEventResponse])
async def get_run_events(run_id: int, limit: int = 200, db: Session = Depends(get_db)) -> List[FileEventResponse]:
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
@router.post("/trigger", response_model=ApiResponse)
async def trigger_sync() -> ApiResponse:
    """Trigger a manual sync run using SyncExecutor."""
    try:
        executor = SyncExecutor.get_instance()
        result = executor.trigger_manual_run()
        if result.accepted:
            return ApiResponse(
                success=True,
                message=result.message,
                data={"run_id": result.run_id, "status": result.status},
            )
        else:
            return ApiResponse(
                success=False,
                message=result.message,
                data={"run_id": result.run_id, "status": result.status},
            )
    except Exception as exc:
        logger.error("Failed to trigger sync: %s", exc)
        raise SchedulerError(f"Failed to trigger sync: {exc}", operation="trigger_sync")


# Events endpoints (without run_id prefix)
events_router = APIRouter(prefix="/events", tags=["events"])


@events_router.get("", response_model=List[FileEventResponse])
async def get_events(limit: int = 200, db: Session = Depends(get_db)) -> List[FileEventResponse]:
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
