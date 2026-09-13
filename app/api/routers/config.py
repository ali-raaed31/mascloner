"""Configuration and status endpoints."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from pydantic import ValidationError
from ...configuration import Configuration, RclonePerformanceSettings, SyncPathsSettings, ConfigurationValidationError
from ..config import config, ConfigManager
from ..db import get_db, get_db_info
from ..dependencies import get_config, get_runner, get_scheduler, get_configuration
from ..models import ConfigKV, Run
from ..rclone_runner import RcloneRunner
from ..scheduler import SyncScheduler, get_sync_config_from_db
from ..schemas import ApiResponse, ConfigRequest, RcloneConfigRequest, StatusResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["config"])


@router.get("/health", response_model=Dict[str, str])
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "mascloner-api"}


@router.get("/status", response_model=StatusResponse)
async def get_status(
    db: Session = Depends(get_db),
    scheduler: SyncScheduler = Depends(get_scheduler),
    cfg: ConfigManager = Depends(get_config),
):
    """Get system status including last run and next scheduled run."""
    try:
        last_run_record = db.execute(select(Run).order_by(desc(Run.id))).scalars().first()
        last_run: Optional[Dict[str, Any]] = None
        last_sync: Optional[str] = None

        if last_run_record:
            last_run = {
                "id": last_run_record.id,
                "status": last_run_record.status,
                "started_at": last_run_record.started_at.isoformat(),
                "finished_at": (
                    last_run_record.finished_at.isoformat()
                    if last_run_record.finished_at
                    else None
                ),
                "num_added": last_run_record.num_added,
                "num_updated": last_run_record.num_updated,
                "bytes_transferred": last_run_record.bytes_transferred,
                "errors": last_run_record.errors,
            }
            last_sync = last_run_record.started_at.isoformat()

        total_runs_count = db.execute(select(func.count(Run.id))).scalar() or 0

        scheduler_running = scheduler.is_enabled() if hasattr(scheduler, "is_enabled") else False
        job_info = scheduler.get_job_info() if scheduler_running else None
        next_run = job_info.get("next_run_time") if job_info else None

        db_info = get_db_info()
        database_ok = db_info.get("connection_ok", False)

        remotes_configured = {"gdrive": False, "nextcloud": False}
        try:
            from ...configuration import Configuration
            typed_cfg = Configuration(session_factory=lambda: db)
            gdrive_meta = typed_cfg.get_endpoint_metadata("gdrive")
            nc_meta = typed_cfg.get_endpoint_metadata("ncwebdav")
            remotes_configured["gdrive"] = bool(gdrive_meta and gdrive_meta.is_configured)
            remotes_configured["nextcloud"] = bool(nc_meta and nc_meta.is_configured)
        except Exception as exc:
            logger.warning("Failed to check remotes configuration: %s", exc)

        sync_config = get_sync_config_from_db(db)
        config_valid = bool(
            sync_config.get("gdrive_remote")
            and sync_config.get("gdrive_src")
            and sync_config.get("nc_remote")
            and sync_config.get("nc_dest_path")
            and remotes_configured["gdrive"]
            and remotes_configured["nextcloud"]
        )

        return StatusResponse(
            last_run=last_run,
            last_sync=last_sync,
            next_run=next_run,
            scheduler_running=scheduler_running,
            database_ok=database_ok,
            total_runs=total_runs_count,
            config_valid=config_valid,
            remotes_configured=remotes_configured,
        )

    except Exception as exc:
        logger.error("Status check failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get status: {exc}",
        ) from exc


@router.get("/config", response_model=Dict[str, str])
async def get_config_endpoint(db: Session = Depends(get_db)):
    """Get current configuration from database."""
    try:
        config_items = db.execute(select(ConfigKV)).scalars().all()
        return {item.key: item.value for item in config_items}
    except Exception as exc:
        logger.error("Failed to get config: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get configuration: {exc}",
        ) from exc


@router.post("/config", response_model=ApiResponse)
async def update_config_endpoint(
    config_request: ConfigRequest,
    db: Session = Depends(get_db),
    cfg_module: Configuration = Depends(get_configuration),
):
    """Update sync configuration in SQLite."""
    try:
        config_data = config_request.model_dump()

        # Normalize and persist paths if present
        paths = SyncPathsSettings(
            gdrive_src=config_data.get("gdrive_src", ""),
            nc_dest_path=config_data.get("nc_dest_path", ""),
        )
        cfg_module.set_sync_paths(paths)

        # Store remotes in ConfigKV for compatibility until Issue #6
        if "gdrive_remote" in config_data and config_data["gdrive_remote"] is not None:
            db.merge(
                ConfigKV(
                    key="gdrive_remote",
                    value=config_data["gdrive_remote"],
                    provenance="user",
                )
            )
        if "nc_remote" in config_data and config_data["nc_remote"] is not None:
            db.merge(
                ConfigKV(
                    key="nc_remote",
                    value=config_data["nc_remote"],
                    provenance="user",
                )
            )
        db.commit()

        logger.info("Configuration updated")
        return ApiResponse(success=True, message="Configuration updated successfully")
    except (ValidationError, ConfigurationValidationError) as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error("Failed to update config: %s", exc)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update configuration: {exc}",
        ) from exc


@router.get("/config/paths", response_model=SyncPathsSettings)
async def get_sync_paths_endpoint(
    cfg_module: Configuration = Depends(get_configuration),
):
    """Get current sync folder paths from SQLite."""
    return cfg_module.get_sync_paths()


@router.post("/config/paths", response_model=ApiResponse)
async def update_sync_paths_endpoint(
    paths: SyncPathsSettings,
    cfg_module: Configuration = Depends(get_configuration),
):
    """Update sync folder paths in SQLite."""
    try:
        cfg_module.set_sync_paths(paths)
        return ApiResponse(
            success=True,
            message="Sync paths updated successfully",
            data=paths.model_dump(),
        )
    except (ValidationError, ConfigurationValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error("Failed to update sync paths: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update sync paths: {exc}",
        ) from exc


@router.get("/rclone/config", response_model=Dict[str, Any])
async def get_rclone_config_settings(
    cfg_module: Configuration = Depends(get_configuration),
):
    """Return current rclone performance configuration from SQLite."""
    perf = cfg_module.get_performance()
    return perf.model_dump()


@router.post("/rclone/config", response_model=ApiResponse)
async def update_rclone_config(
    settings: RcloneConfigRequest,
    cfg_module: Configuration = Depends(get_configuration),
    runner: RcloneRunner = Depends(get_runner),
):
    """Persist updated rclone performance settings to SQLite without writing to .env."""
    try:
        perf_settings = RclonePerformanceSettings(
            transfers=settings.transfers,
            checkers=settings.checkers,
            tpslimit=settings.tpslimit,
            tpslimit_burst=settings.tpslimit_burst,
            buffer_size=settings.buffer_size,
            drive_chunk_size=settings.drive_chunk_size,
            drive_upload_cutoff=settings.drive_upload_cutoff,
            fast_list=settings.fast_list,
        )
        cfg_module.set_performance(perf_settings)

        # Refresh in-memory runner configuration for subsequent runs
        runner.rclone_config.update(perf_settings.model_dump())

        return ApiResponse(
            success=True,
            message="Rclone performance settings updated",
        )
    except (ValidationError, ConfigurationValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error("Failed to update rclone performance settings: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update rclone performance settings: {exc}",
        ) from exc
