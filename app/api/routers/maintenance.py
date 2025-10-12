"""Maintenance and diagnostic endpoints."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..db import get_db, get_db_info
from ..models import FileEvent, Run
from ..scheduler import cleanup_old_runs
from ..schemas import ApiResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["maintenance"])


@router.post("/maintenance/cleanup", response_model=ApiResponse)
async def cleanup_database(keep_runs: int = 100, db: Session = Depends(get_db)):
    """Clean up old run records."""
    try:
        deleted_count = cleanup_old_runs(db, keep_runs)
        return ApiResponse(
            success=True,
            message=f"Cleaned up {deleted_count} old run records",
            data={"deleted_count": deleted_count},
        )
    except Exception as exc:
        logger.error("Database cleanup failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database cleanup failed: {exc}",
        )


@router.post("/maintenance/reset", response_model=ApiResponse)
async def reset_database(db: Session = Depends(get_db)):
    """Reset database by deleting all runs and file events."""
    try:
        runs_count = db.execute(select(func.count(Run.id))).scalar() or 0
        events_count = db.execute(select(func.count(FileEvent.id))).scalar() or 0

        db.execute(delete(FileEvent))
        db.execute(delete(Run))
        db.commit()

        logger.info("Database reset: deleted %s runs and %s file events", runs_count, events_count)
        return ApiResponse(
            success=True,
            message="Database reset successfully.",
            data={
                "runs_deleted": runs_count,
                "events_deleted": events_count,
                "total_deleted": runs_count + events_count,
            },
        )
    except Exception as exc:
        logger.error("Database reset failed: %s", exc)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database reset failed: {exc}",
        )


@router.get("/debug/rclone-logs", response_model=Dict[str, Any])
async def debug_rclone_logs(limit: int = 50):
    """Debug endpoint to show recent rclone log entries."""
    try:
        log_dir = Path("/srv/mascloner/logs")
        log_files = list(log_dir.glob("sync-*.log"))

        if not log_files:
            return {"message": "No sync log files found", "logs": []}

        latest_log = max(log_files, key=lambda f: f.stat().st_mtime)
        with latest_log.open("r") as handle:
            lines = handle.readlines()
            recent_lines = lines[-limit:] if len(lines) > limit else lines

        parsed_logs = []
        start_index = len(lines) - len(recent_lines)
        for offset, line in enumerate(recent_lines):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                parsed_logs.append(
                    {
                        "line_number": start_index + offset + 1,
                        "raw": line,
                        "parsed": obj,
                        "type": "json",
                    }
                )
            except json.JSONDecodeError:
                parsed_logs.append(
                    {
                        "line_number": start_index + offset + 1,
                        "raw": line,
                        "parsed": None,
                        "type": "text",
                    }
                )

        return {
            "log_file": str(latest_log),
            "total_lines": len(lines),
            "recent_lines": len(recent_lines),
            "logs": parsed_logs,
        }
    except Exception as exc:
        logger.error("Debug log reading failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read logs: {exc}",
        )


@router.get("/database/info", response_model=Dict[str, Any])
async def get_database_info():
    """Get database information and statistics."""
    try:
        return get_db_info()
    except Exception as exc:
        logger.error("Failed to get database info: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get database info: {exc}",
        )
