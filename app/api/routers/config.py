"""Configuration, status, and operational endpoints."""

from __future__ import annotations

import logging
import subprocess
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..config import config
from ..db import get_db, get_db_info
from ..models import ConfigKV, FileEvent, Run
from ..rclone_runner import RcloneRunner
from ..scheduler import (
    get_scheduler,
    get_sync_config_from_db,
)
from ..schemas import (
    ApiResponse,
    ConfigRequest,
    FileEventResponse,
    RunResponse,
    ScheduleRequest,
    StatusResponse,
    TreeNodeResponse,
    TreeResponse,
)
from ..tree_builder import FileTreeBuilder

logger = logging.getLogger(__name__)

router = APIRouter(tags=["config"])


@router.get("/health", response_model=Dict[str, str])
async def health_check():
    """Simple health check used by the UI."""
    return {"status": "healthy", "service": "mascloner-api"}


@router.get("/status", response_model=StatusResponse)
async def get_status(db: Session = Depends(get_db)):
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
                "finished_at": last_run_record.finished_at.isoformat()
                if last_run_record.finished_at
                else None,
                "num_added": last_run_record.num_added,
                "num_updated": last_run_record.num_updated,
                "bytes_transferred": last_run_record.bytes_transferred,
                "errors": last_run_record.errors,
            }
            last_sync = last_run_record.started_at.isoformat()

        total_runs_count = db.execute(select(func.count(Run.id))).scalar() or 0

        scheduler = get_scheduler()
        job_info = scheduler.get_job_info()
        next_run = job_info.get("next_run_time") if job_info else None

        db_info = get_db_info()
        database_ok = db_info.get("connection_ok", False)

        remotes_configured = {"gdrive": False, "nextcloud": False}
        try:
            base_config = config.get_base_config()
            rclone_config = str(base_config["base_dir"] / base_config["rclone_conf"])

            result = subprocess.run(
                ["rclone", "--config", rclone_config, "listremotes"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                remotes_list = result.stdout.strip()
                remotes_configured["gdrive"] = "gdrive:" in remotes_list
                remotes_configured["nextcloud"] = any(
                    remote in remotes_list for remote in ["ncwebdav:", "nextcloud:", "nc:"]
                )
        except Exception as exc:  # pragma: no cover - defensive logging
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
        )


@router.get("/runs", response_model=List[RunResponse])
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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get runs: {exc}",
        )


@router.get("/runs/{run_id}/events", response_model=List[FileEventResponse])
async def get_run_events(run_id: int, limit: int = 200, db: Session = Depends(get_db)):
    """Get file events for a specific run."""
    try:
        run = db.execute(select(Run).where(Run.id == run_id)).scalars().first()
        if not run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run {run_id} not found",
            )

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
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to get run events: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get run events: {exc}",
        )


@router.get("/events", response_model=List[FileEventResponse])
async def get_events(limit: int = 200, db: Session = Depends(get_db)):
    """Get recent file events across all runs."""
    try:
        events = (
            db.execute(
                select(FileEvent)
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
    except Exception as exc:
        logger.error("Failed to get events: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get events: {exc}",
        )


@router.post("/runs", response_model=ApiResponse)
async def trigger_sync():
    """Trigger a manual sync run."""
    try:
        scheduler = get_scheduler()
        if scheduler.trigger_sync_now():
            return ApiResponse(success=True, message="Sync triggered successfully")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to trigger sync",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to trigger sync: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger sync: {exc}",
        )


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
        )


@router.post("/config", response_model=ApiResponse)
async def update_config_endpoint(config_request: ConfigRequest, db: Session = Depends(get_db)):
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
        )


@router.get("/schedule", response_model=Dict[str, Any])
async def get_schedule(db: Session = Depends(get_db)):
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

        scheduler = get_scheduler()
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
        )


@router.post("/schedule", response_model=ApiResponse)
async def update_schedule(schedule_request: ScheduleRequest, db: Session = Depends(get_db)):
    """Update sync schedule."""
    try:
        scheduler = get_scheduler()
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
        )


@router.post("/schedule/start", response_model=ApiResponse)
async def start_scheduler():
    """Start the scheduler."""
    try:
        scheduler = get_scheduler()
        scheduler.start()
        return ApiResponse(success=True, message="Scheduler started")
    except Exception as exc:
        logger.error("Failed to start scheduler: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start scheduler: {exc}",
        )


@router.post("/schedule/stop", response_model=ApiResponse)
async def stop_scheduler():
    """Stop the scheduler."""
    try:
        scheduler = get_scheduler()
        scheduler.stop()
        return ApiResponse(success=True, message="Scheduler stopped")
    except Exception as exc:
        logger.error("Failed to stop scheduler: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop scheduler: {exc}",
        )


@router.get("/browse/folders/{remote_name}", response_model=Dict[str, Any])
async def browse_remote_folders(remote_name: str, path: str = ""):
    """Browse folders in a remote."""
    try:
        runner = RcloneRunner()
        logger.info("API: browse folders request remote='%s' path='%s'", remote_name, path)
        folders = runner.list_folders(remote_name, path)
        logger.info(
            "API: browse folders response remote='%s' path='%s' count=%d",
            remote_name,
            path,
            len(folders),
        )
        return {
            "status": "success",
            "success": True,
            "folders": folders,
            "remote": remote_name,
            "path": path,
        }
    except Exception as exc:
        logger.error("Failed to browse folders: %s", exc)
        return {
            "status": "error",
            "success": False,
            "error": str(exc),
            "folders": [],
        }


@router.get("/estimate/size", response_model=Dict[str, Any])
async def estimate_sync_size(source: str, dest: str):
    """Estimate the size of a sync operation."""
    try:
        runner = RcloneRunner()
        size_info = runner.estimate_sync_size(source, dest)
        return {
            "status": "success",
            "success": True,
            "size_mb": size_info.get("size_mb", 0),
            "file_count": size_info.get("file_count", 0),
            "folder_count": size_info.get("folder_count", 0),
        }
    except Exception as exc:
        logger.error("Failed to estimate size: %s", exc)
        return {
            "status": "error",
            "success": False,
            "error": str(exc),
            "size_mb": 0,
            "file_count": 0,
            "folder_count": 0,
        }


def _convert_tree_node(node) -> TreeNodeResponse:
    return TreeNodeResponse(
        name=node.name,
        path=node.path,
        type=node.type,
        size=node.size,
        last_sync=node.last_sync,
        status=node.status,
        children=[_convert_tree_node(child) for child in node.children],
    )


@router.get("/tree", response_model=TreeResponse)
async def get_file_tree(path: str = "", db: Session = Depends(get_db)):
    """Get file tree structure with sync status."""
    try:
        events = db.execute(
            select(FileEvent).order_by(desc(FileEvent.timestamp))
        ).scalars().all()

        tree_builder = FileTreeBuilder()
        root_node = tree_builder.build_tree(events, path)
        stats = tree_builder.get_statistics(root_node)
        root_response = _convert_tree_node(root_node)

        return TreeResponse(root=root_response, total_files=stats["files"], total_folders=stats["folders"])
    except Exception as exc:
        logger.error("Failed to get file tree: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get file tree: {exc}",
        )


@router.get("/tree/status/{path:path}", response_model=Dict[str, Any])
async def get_path_status(path: str, db: Session = Depends(get_db)):
    """Get sync status for a specific path."""
    try:
        latest_event = (
            db.execute(
                select(FileEvent)
                .where(FileEvent.file_path == path)
                .order_by(desc(FileEvent.timestamp))
            )
            .scalars()
            .first()
        )

        if latest_event:
            return {
                "path": path,
                "status": latest_event.action,
                "last_sync": latest_event.timestamp.isoformat(),
                "size": latest_event.file_size,
                "message": latest_event.message,
            }

        return {
            "path": path,
            "status": "unknown",
            "last_sync": None,
            "size": 0,
            "message": "No sync history",
        }
    except Exception as exc:
        logger.error("Failed to get path status: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get path status: {exc}",
        )
