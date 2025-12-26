"""Scheduler control endpoints."""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..dependencies import get_scheduler
from ..models import ConfigKV
from ..scheduler import SyncScheduler
from ..schemas import ApiResponse, ScheduleRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schedule", tags=["schedule"])


@router.get("", response_model=Dict[str, Any])
async def get_schedule_endpoint(
    db: Session = Depends(get_db),
    scheduler: SyncScheduler = Depends(get_scheduler),
):
    """Get current sync schedule."""
    try:
        interval_config = db.execute(
            select(ConfigKV).where(ConfigKV.key == "interval_min")
        ).scalar_one_or_none()
        jitter_config = db.execute(
            select(ConfigKV).where(ConfigKV.key == "jitter_sec")
        ).scalar_one_or_none()

        interval_min = int(interval_config.value) if interval_config else 5
        jitter_sec = int(jitter_config.value) if jitter_config else 20

        job_info = scheduler.get_job_info()

        if job_info:
            return {
                "interval_min": interval_min,
                "jitter_sec": jitter_sec,
                "interval": job_info.get("trigger", "Unknown"),
                "next_run_time": job_info.get("next_run_time"),
            }

        return {
            "interval_min": interval_min,
            "jitter_sec": jitter_sec,
            "interval": "Not scheduled",
            "next_run_time": None,
        }
    except Exception as exc:
        logger.error("Failed to get schedule: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get schedule: {exc}",
        ) from exc


@router.post("", response_model=ApiResponse)
async def update_schedule(
    schedule_request: ScheduleRequest,
    db: Session = Depends(get_db),
    scheduler: SyncScheduler = Depends(get_scheduler),
):
    """Update sync schedule."""
    try:
        if scheduler.add_sync_job(
            interval_minutes=schedule_request.interval_min,
            jitter_seconds=schedule_request.jitter_sec,
        ):
            db.merge(ConfigKV(key="interval_min", value=str(schedule_request.interval_min)))
            db.merge(ConfigKV(key="jitter_sec", value=str(schedule_request.jitter_sec)))
            db.commit()
            return ApiResponse(success=True, message="Schedule updated successfully")

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update schedule",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to update schedule: %s", exc)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update schedule: {exc}",
        ) from exc


@router.post("/start", response_model=ApiResponse)
async def start_scheduler_endpoint(scheduler: SyncScheduler = Depends(get_scheduler)):
    """Start the scheduler."""
    try:
        scheduler.start()
        return ApiResponse(success=True, message="Scheduler started")
    except Exception as exc:
        logger.error("Failed to start scheduler: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start scheduler: {exc}",
        ) from exc


@router.post("/stop", response_model=ApiResponse)
async def stop_scheduler_endpoint(scheduler: SyncScheduler = Depends(get_scheduler)):
    """Stop the scheduler."""
    try:
        scheduler.stop()
        return ApiResponse(success=True, message="Scheduler stopped")
    except Exception as exc:
        logger.error("Failed to stop scheduler: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop scheduler: {exc}",
        ) from exc

