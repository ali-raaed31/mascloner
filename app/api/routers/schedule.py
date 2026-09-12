"""Scheduler control endpoints."""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError

from ...configuration import Configuration, ScheduleSettings, ConfigurationValidationError
from ..dependencies import get_configuration, get_scheduler
from ..scheduler import SyncScheduler
from ..schemas import ApiResponse, ScheduleRequest, ScheduleResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/schedule", tags=["schedule"])


def _reconcile_and_persist_schedule(
    new_settings: ScheduleSettings,
    scheduler: SyncScheduler,
    cfg_module: Configuration,
) -> None:
    """Reconcile in-memory scheduler job state, then persist durable settings to SQLite."""
    if new_settings.enabled:
        scheduler.start()
        if not scheduler.add_sync_job(
            interval_minutes=new_settings.interval_min,
            jitter_seconds=new_settings.jitter_sec,
        ):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to register schedule in runtime scheduler",
            )
    else:
        if not scheduler.remove_sync_job():
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to remove job from runtime scheduler",
            )

    cfg_module.set_schedule(new_settings)


@router.get("", response_model=ScheduleResponse)
async def get_schedule_endpoint(
    cfg_module: Configuration = Depends(get_configuration),
    scheduler: SyncScheduler = Depends(get_scheduler),
):
    """Get current sync schedule."""
    try:
        schedule_settings = cfg_module.get_schedule()
        job_info = scheduler.get_job_info()

        if schedule_settings.enabled and job_info:
            return ScheduleResponse(
                enabled=True,
                interval_min=schedule_settings.interval_min,
                jitter_sec=schedule_settings.jitter_sec,
                interval=job_info.get("trigger", f"MasCloner Sync ({schedule_settings.interval_min}min)"),
                next_run_time=job_info.get("next_run_time"),
            )

        return ScheduleResponse(
            enabled=False,
            interval_min=schedule_settings.interval_min,
            jitter_sec=schedule_settings.jitter_sec,
            interval="Not scheduled",
            next_run_time=None,
        )
    except Exception as exc:
        logger.error("Failed to get schedule: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get schedule: {exc}",
        ) from exc


@router.post("", response_model=ApiResponse)
async def update_schedule(
    schedule_request: ScheduleRequest,
    cfg_module: Configuration = Depends(get_configuration),
    scheduler: SyncScheduler = Depends(get_scheduler),
):
    """Update sync schedule."""
    try:
        current_sched = cfg_module.get_schedule()
        new_enabled = (
            schedule_request.enabled
            if schedule_request.enabled is not None
            else current_sched.enabled
        )

        new_settings = ScheduleSettings(
            enabled=new_enabled,
            interval_min=schedule_request.interval_min,
            jitter_sec=schedule_request.jitter_sec,
        )

        _reconcile_and_persist_schedule(new_settings, scheduler, cfg_module)
        return ApiResponse(success=True, message="Schedule updated successfully")

    except HTTPException:
        raise
    except (ValidationError, ConfigurationValidationError, ValueError) as val_exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid schedule parameters: {val_exc}",
        ) from val_exc
    except Exception as exc:
        logger.error("Failed to update schedule: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update schedule: {exc}",
        ) from exc


@router.post("/start", response_model=ApiResponse)
async def start_scheduler_endpoint(
    cfg_module: Configuration = Depends(get_configuration),
    scheduler: SyncScheduler = Depends(get_scheduler),
):
    """Start/resume the scheduler."""
    try:
        current_sched = cfg_module.get_schedule()
        new_settings = ScheduleSettings(
            enabled=True,
            interval_min=current_sched.interval_min,
            jitter_sec=current_sched.jitter_sec,
        )

        _reconcile_and_persist_schedule(new_settings, scheduler, cfg_module)
        return ApiResponse(success=True, message="Scheduler started")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to start scheduler: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start scheduler: {exc}",
        ) from exc


@router.post("/stop", response_model=ApiResponse)
async def stop_scheduler_endpoint(
    cfg_module: Configuration = Depends(get_configuration),
    scheduler: SyncScheduler = Depends(get_scheduler),
):
    """Stop/pause the scheduler."""
    try:
        current_sched = cfg_module.get_schedule()
        new_settings = ScheduleSettings(
            enabled=False,
            interval_min=current_sched.interval_min,
            jitter_sec=current_sched.jitter_sec,
        )

        _reconcile_and_persist_schedule(new_settings, scheduler, cfg_module)
        return ApiResponse(success=True, message="Scheduler stopped")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to stop scheduler: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop scheduler: {exc}",
        ) from exc
