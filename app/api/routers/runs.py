"""Sync runs and file events endpoints."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..dependencies import get_runner, get_scheduler
from ..exceptions import DatabaseError, NotFoundError, SchedulerError
from ..models import FileEvent, Run
from ..rclone_runner import RcloneRunner
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


# Live monitoring endpoints - must be before /{run_id} patterns!
@router.get("/current")
async def get_current_run(
    db: Session = Depends(get_db),
    runner: RcloneRunner = Depends(get_runner),
) -> Optional[Dict[str, Any]]:
    """Get currently running sync if any.

    Returns run information and live monitoring data, or null if no sync running.
    """
    try:
        # First check database for running status
        current_run = (
            db.execute(
                select(Run)
                .where(Run.status == "running")
                .order_by(desc(Run.started_at))
            )
            .scalars()
            .first()
        )

        if not current_run:
            return None

        # Get additional info from runner if available
        runner_info = runner.get_current_run_info()

        return {
            "id": current_run.id,
            "status": current_run.status,
            "started_at": current_run.started_at.isoformat(),
            "num_added": current_run.num_added,
            "num_updated": current_run.num_updated,
            "bytes_transferred": current_run.bytes_transferred,
            "errors": current_run.errors,
            "log_path": current_run.log_path,
            "is_process_running": (
                runner_info.get("is_running", False) if runner_info else False
            ),
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
    runner: RcloneRunner = Depends(get_runner),
) -> Dict[str, Any]:
    """Get log lines for a running or completed sync.

    Args:
        run_id: The run ID to get logs for
        since: Line number to start reading from (for incremental polling)
        limit: Maximum number of lines to return

    Returns:
        Dict with run_id, logs list, and next_line for pagination
    """
    try:
        # Verify run exists
        run = db.execute(select(Run).where(Run.id == run_id)).scalars().first()
        if not run:
            raise NotFoundError("Run", run_id)

        # Check if this is the current run
        runner_info = runner.get_current_run_info()
        if runner_info and runner_info.get("run_id") == run_id:
            # Tail log file for live logs
            logs, next_line = runner.tail_log_file(since_line=since, limit=limit)
            return {
                "run_id": run_id,
                "logs": logs,
                "next_line": next_line,
                "is_live": True,
            }
        else:
            # For completed runs, read from log_path if available
            if run.log_path:
                import os

                if os.path.exists(run.log_path):
                    # Temporarily set log path for tailing
                    logs = []
                    try:
                        import json

                        with open(run.log_path, "r", encoding="utf-8") as f:
                            for line_num, line in enumerate(f):
                                if line_num < since:
                                    continue
                                if len(logs) >= limit:
                                    break
                                line = line.strip()
                                if not line:
                                    continue
                                try:
                                    obj = json.loads(line)
                                    logs.append({
                                        "line": line_num,
                                        "timestamp": obj.get("time", ""),
                                        "level": obj.get("level", "info"),
                                        "message": obj.get("msg", ""),
                                        "object": obj.get("object", ""),
                                        "size": obj.get("size", 0),
                                    })
                                except json.JSONDecodeError:
                                    logs.append({
                                        "line": line_num,
                                        "timestamp": "",
                                        "level": "info",
                                        "message": line,
                                        "object": "",
                                        "size": 0,
                                    })
                    except Exception as e:
                        logger.error("Error reading log file: %s", e)

                    return {
                        "run_id": run_id,
                        "logs": logs,
                        "next_line": since + len(logs),
                        "is_live": False,
                    }

            return {
                "run_id": run_id,
                "logs": [],
                "next_line": since,
                "is_live": False,
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
    runner: RcloneRunner = Depends(get_runner),
) -> Dict[str, Any]:
    """Request graceful stop of a running sync.

    Sends SIGTERM to rclone, which finishes the current file before stopping.
    """
    try:
        # Verify run exists and is running
        run = db.execute(select(Run).where(Run.id == run_id)).scalars().first()
        if not run:
            raise NotFoundError("Run", run_id)

        if run.status != "running":
            raise HTTPException(
                status_code=400,
                detail=f"Run {run_id} is not running (status: {run.status})",
            )

        # Check if this is the current run in the runner
        runner_info = runner.get_current_run_info()
        if not runner_info or runner_info.get("run_id") != run_id:
            raise HTTPException(
                status_code=400,
                detail="Run is not the currently active sync process",
            )

        # Request stop
        if runner.request_stop():
            return {
                "success": True,
                "message": "Stop requested - rclone will finish current file and exit",
                "run_id": run_id,
            }
        else:
            raise HTTPException(
                status_code=400,
                detail="No active rclone process to stop",
            )
    except (NotFoundError, HTTPException):
        raise
    except Exception as exc:
        logger.error("Failed to stop run: %s", exc)
        raise DatabaseError(f"Failed to stop run: {exc}", operation="stop_run")


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

