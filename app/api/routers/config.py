"""Configuration and status endpoints."""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..config import config, ConfigManager
from ..db import get_db, get_db_info
from ..dependencies import get_config, get_runner, get_scheduler
from ..models import ConfigKV, Run
from ..rclone_runner import RcloneRunner
from ..scheduler import SyncScheduler, get_sync_config_from_db
from ..schemas import ApiResponse, ConfigRequest, RcloneConfigRequest, StatusResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["config"])


def _persist_env_updates(updates: Dict[str, Optional[str]]) -> Path:
    """Write environment variable updates to the installation .env file."""
    if not config:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Configuration manager not initialised",
        )

    base_config = config.get_base_config()
    env_path = base_config["base_dir"] / ".env"

    existing_lines: List[str] = []
    if env_path.exists():
        try:
            with env_path.open("r", encoding="utf-8") as env_file:
                existing_lines = env_file.read().splitlines()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to read .env file: {exc}",
            ) from exc

    handled = {key: False for key in updates}
    updated_lines: List[str] = []

    for line in existing_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            updated_lines.append(line)
            continue

        key, sep, _remainder = line.partition("=")
        key = key.strip()
        if not sep or key not in updates:
            updated_lines.append(line)
            continue

        value = updates[key]
        handled[key] = True
        if value is None:
            continue  # Remove line when value cleared
        updated_lines.append(f"{key}={value}")

    for key, value in updates.items():
        if handled.get(key) or value is None:
            continue
        updated_lines.append(f"{key}={value}")

    env_path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(updated_lines)
    if content and not content.endswith("\n"):
        content = f"{content}\n"

    try:
        with env_path.open("w", encoding="utf-8") as env_file:
            env_file.write(content)
        os.chmod(env_path, 0o600)
        load_dotenv(str(env_path), override=True)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to write .env file: {exc}",
        ) from exc

    return env_path


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

        job_info = scheduler.get_job_info()
        next_run = job_info.get("next_run_time") if job_info else None

        db_info = get_db_info()
        database_ok = db_info.get("connection_ok", False)

        remotes_configured = {"gdrive": False, "nextcloud": False}
        try:
            base_config = cfg.get_base_config()
            rclone_config_path = str(base_config["base_dir"] / base_config["rclone_conf"])

            process = await asyncio.create_subprocess_exec(
                "rclone",
                "--config",
                rclone_config_path,
                "listremotes",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, _ = await asyncio.wait_for(process.communicate(), timeout=10)
                if process.returncode == 0:
                    remotes_list = stdout.decode().strip()
                    remotes_configured["gdrive"] = "gdrive:" in remotes_list
                    remotes_configured["nextcloud"] = any(
                        remote in remotes_list
                        for remote in ["ncwebdav:", "nextcloud:", "nc:"]
                    )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                logger.warning("Timeout checking rclone remotes")
        except Exception as exc:
            logger.warning("Failed to check rclone remotes: %s", exc)

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
            scheduler_running=scheduler.scheduler.running,
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
    config_request: ConfigRequest, db: Session = Depends(get_db)
):
    """Update sync configuration."""
    try:
        config_data = config_request.model_dump()
        for key, value in config_data.items():
            config_item = ConfigKV(key=key, value=value)
            db.merge(config_item)
        db.commit()

        logger.info("Configuration updated")
        return ApiResponse(success=True, message="Configuration updated successfully")
    except Exception as exc:
        logger.error("Failed to update config: %s", exc)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update configuration: {exc}",
        ) from exc


@router.get("/rclone/config", response_model=Dict[str, Any])
async def get_rclone_config_settings(cfg: ConfigManager = Depends(get_config)):
    """Return current rclone performance configuration."""
    return cfg.get_rclone_config()


@router.post("/rclone/config", response_model=ApiResponse)
async def update_rclone_config(
    settings: RcloneConfigRequest,
    cfg: ConfigManager = Depends(get_config),
    runner: RcloneRunner = Depends(get_runner),
):
    """Persist updated rclone performance settings."""

    def _clean(value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        return trimmed or None

    updates = {
        "RCLONE_TRANSFERS": str(settings.transfers),
        "RCLONE_CHECKERS": str(settings.checkers),
        "RCLONE_TPSLIMIT": str(settings.tpslimit),
        "RCLONE_TPSLIMIT_BURST": str(settings.tpslimit_burst),
        "RCLONE_BUFFER_SIZE": _clean(settings.buffer_size),
        "RCLONE_DRIVE_CHUNK_SIZE": _clean(settings.drive_chunk_size),
        "RCLONE_DRIVE_UPLOAD_CUTOFF": _clean(settings.drive_upload_cutoff),
        "RCLONE_FAST_LIST": "1" if settings.fast_list else "0",
    }

    _persist_env_updates(updates)

    # Refresh in-memory configuration for subsequent runs
    runner.rclone_config = cfg.get_rclone_config()

    return ApiResponse(
        success=True,
        message="Rclone performance settings updated",
    )
