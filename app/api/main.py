"""FastAPI application for MasCloner API."""

import logging
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any
from datetime import datetime

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select, desc, func
from sqlalchemy.orm import Session

from .db import init_db, get_db, get_db_info
from .models import Run, FileEvent, ConfigKV
from .scheduler import start_scheduler, stop_scheduler, get_scheduler, sync_job, cleanup_old_runs
from .config import config
from .tree_builder import FileTreeBuilder
import subprocess
import json
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Pydantic models for API
class ConfigRequest(BaseModel):
    """Request model for configuration updates."""
    gdrive_remote: str = Field(..., description="Google Drive remote name")
    gdrive_src: str = Field(..., description="Google Drive source path")
    nc_remote: str = Field(..., description="Nextcloud remote name") 
    nc_dest_path: str = Field(..., description="Nextcloud destination path")


class ScheduleRequest(BaseModel):
    """Request model for schedule updates."""
    interval_min: int = Field(ge=1, le=1440, description="Sync interval in minutes")
    jitter_sec: int = Field(ge=0, le=3600, default=20, description="Jitter in seconds")


class RunResponse(BaseModel):
    """Response model for run information."""
    id: int
    status: str
    started_at: str
    finished_at: Optional[str] = None
    num_added: int = 0
    num_updated: int = 0
    bytes_transferred: int = 0
    errors: int = 0
    log_path: Optional[str] = None


class FileEventResponse(BaseModel):
    """Response model for file events."""
    id: int
    timestamp: str
    action: str
    file_path: str
    file_size: int
    file_hash: Optional[str] = None
    message: Optional[str] = None


class StatusResponse(BaseModel):
    """Response model for system status."""
    last_run: Optional[Dict[str, Any]] = None
    last_sync: Optional[str] = None
    next_run: Optional[str] = None
    scheduler_running: bool
    database_ok: bool
    total_runs: int = 0
    config_valid: bool = False
    remotes_configured: Dict[str, bool] = {}


class ApiResponse(BaseModel):
    """Generic API response model."""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class GoogleDriveOAuthRequest(BaseModel):
    """Request model for Google Drive OAuth configuration."""
    token: str = Field(..., description="OAuth token from rclone authorize")
    scope: str = Field(default="drive.readonly", description="OAuth scope")
    client_id: Optional[str] = Field(None, description="Custom client ID (optional)")
    client_secret: Optional[str] = Field(None, description="Custom client secret (optional)")


class GoogleDriveStatusResponse(BaseModel):
    """Response model for Google Drive status."""
    configured: bool
    remote_name: str = "gdrive"
    scope: Optional[str] = None
    folders: Optional[List[str]] = None
    last_test: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    # Startup
    logger.info("Starting MasCloner API...")
    
    try:
        # Initialize database
        init_db()
        logger.info("Database initialized")
        
        # Start scheduler
        if start_scheduler():
            logger.info("Scheduler started")
        else:
            logger.warning("Failed to start scheduler")
        
        logger.info("MasCloner API startup complete")
        
    except Exception as e:
        logger.error(f"Startup failed: {e}")
        raise
    
    yield
    
    # Shutdown
    logger.info("Shutting down MasCloner API...")
    try:
        stop_scheduler()
        logger.info("Scheduler stopped")
    except Exception as e:
        logger.error(f"Shutdown error: {e}")


# Create FastAPI app
app = FastAPI(
    title="MasCloner API",
    description="API for managing Google Drive to Nextcloud sync operations",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],  # Streamlit UI
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/health", response_model=Dict[str, str])
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "mascloner-api"}


# Google Drive OAuth endpoints
@app.post("/oauth/google-drive", response_model=ApiResponse)
async def configure_google_drive_oauth(request: GoogleDriveOAuthRequest):
    """Configure Google Drive using OAuth token from rclone authorize."""
    try:
        # Validate token format
        try:
            token_data = json.loads(request.token)
            if "access_token" not in token_data:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid token format: missing access_token"
                )
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=400,
                detail="Invalid token format: not valid JSON"
            )
        
        # Prepare rclone config command
        base_config = config.get_base_config()
        rclone_config = str(base_config["base_dir"] / base_config["rclone_conf"])
        mascloner_user = "mascloner"  # Fixed user for production
        
        # Remove existing gdrive remote if it exists
        try:
            subprocess.run([
                "rclone", "--config", rclone_config,
                "config", "delete", "gdrive"
            ], capture_output=True, timeout=10)
        except subprocess.TimeoutExpired:
            pass  # Ignore if removal fails
        
        # Build config create command
        cmd = [
            "rclone", "--config", rclone_config,
            "config", "create", "gdrive", "drive",
            f"scope={request.scope}",
            f"token={request.token}"
        ]
        
        # Add custom client credentials if provided
        if request.client_id:
            cmd.extend([f"client_id={request.client_id}"])
        if request.client_secret:
            cmd.extend([f"client_secret={request.client_secret}"])
        
        # Execute rclone config create
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            logger.info("Google Drive OAuth configured successfully")
            return ApiResponse(
                success=True,
                message="Google Drive configured successfully",
                data={"remote_name": "gdrive", "scope": request.scope}
            )
        else:
            logger.error(f"rclone config failed: {result.stderr}")
            raise HTTPException(
                status_code=500,
                detail=f"Configuration failed: {result.stderr or 'Unknown error'}"
            )
            
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=500,
            detail="Configuration timeout - rclone took too long to respond"
        )
    except Exception as e:
        logger.error(f"Google Drive OAuth configuration error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Configuration error: {str(e)}"
        )


@app.get("/oauth/google-drive/status", response_model=GoogleDriveStatusResponse)
async def get_google_drive_status():
    """Get Google Drive configuration status."""
    try:
        base_config = config.get_base_config()
        rclone_config = str(base_config["base_dir"] / base_config["rclone_conf"])
        mascloner_user = "mascloner"  # Fixed user for production
        
        # Check if gdrive remote exists
        result = subprocess.run([
            "rclone", "--config", rclone_config,
            "listremotes"
        ], capture_output=True, text=True, timeout=10)
        
        configured = result.returncode == 0 and "gdrive:" in result.stdout
        
        response_data = {
            "configured": configured,
            "remote_name": "gdrive"
        }
        
        if configured:
            # Try to get some folder info
            try:
                folder_result = subprocess.run([
                    "rclone", "--config", rclone_config,
                    "--transfers=2", "--checkers=2",
                    "lsd", "gdrive:"
                ], capture_output=True, text=True, timeout=15)
                
                if folder_result.returncode == 0:
                    folders = []
                    for line in folder_result.stdout.strip().split('\n'):
                        if line.strip():
                            # Extract folder name from rclone lsd output
                            parts = line.strip().split()
                            if len(parts) >= 5:
                                folder_name = ' '.join(parts[4:])
                                folders.append(folder_name)
                    
                    response_data["folders"] = folders[:10]  # Limit to 10 folders
                    response_data["scope"] = "drive.readonly"  # Would need to parse from config
                    
            except subprocess.TimeoutExpired:
                logger.warning("Google Drive folder listing timeout")
        
        return GoogleDriveStatusResponse(**response_data)
        
    except Exception as e:
        logger.error(f"Google Drive status check error: {e}")
        return GoogleDriveStatusResponse(configured=False)


@app.post("/oauth/google-drive/test", response_model=ApiResponse)
async def test_google_drive_connection():
    """Test Google Drive connection."""
    try:
        base_config = config.get_base_config()
        rclone_config = str(base_config["base_dir"] / base_config["rclone_conf"])
        mascloner_user = "mascloner"  # Fixed user for production
        
        # Test connection with optimized settings
        result = subprocess.run([
            "rclone", "--config", rclone_config,
            "--transfers=4", "--checkers=8",
            "lsd", "gdrive:"
        ], capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            # Parse folder list
            folders = []
            for line in result.stdout.strip().split('\n'):
                if line.strip():
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        folder_name = ' '.join(parts[4:])
                        folders.append(folder_name)
            
            return ApiResponse(
                success=True,
                message="Google Drive connection successful",
                data={"folders": folders[:10]}
            )
        else:
            return ApiResponse(
                success=False,
                message=f"Connection failed: {result.stderr or 'Unknown error'}"
            )
            
    except subprocess.TimeoutExpired:
        return ApiResponse(
            success=False,
            message="Connection test timeout"
        )
    except Exception as e:
        logger.error(f"Google Drive connection test error: {e}")
        return ApiResponse(
            success=False,
            message=f"Test error: {str(e)}"
        )


@app.delete("/oauth/google-drive", response_model=ApiResponse)
async def remove_google_drive_config():
    """Remove Google Drive configuration."""
    try:
        base_config = config.get_base_config()
        rclone_config = str(base_config["base_dir"] / base_config["rclone_conf"])
        mascloner_user = "mascloner"  # Fixed user for production
        
        result = subprocess.run([
            "rclone", "--config", rclone_config,
            "config", "delete", "gdrive"
        ], capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            return ApiResponse(
                success=True,
                message="Google Drive configuration removed successfully"
            )
        else:
            return ApiResponse(
                success=False,
                message=f"Failed to remove configuration: {result.stderr or 'Unknown error'}"
            )
            
    except Exception as e:
        logger.error(f"Google Drive config removal error: {e}")
        return ApiResponse(
            success=False,
            message=f"Removal error: {str(e)}"
        )


# Status endpoint
@app.get("/status", response_model=StatusResponse)
async def get_status(db: Session = Depends(get_db)):
    """Get system status including last run and next scheduled run."""
    try:
        # Get last run
        last_run_record = db.execute(
            select(Run).order_by(desc(Run.id))
        ).scalars().first()
        
        last_run = None
        last_sync = None
        if last_run_record:
            last_run = {
                "id": last_run_record.id,
                "status": last_run_record.status,
                "started_at": last_run_record.started_at.isoformat(),
                "finished_at": last_run_record.finished_at.isoformat() if last_run_record.finished_at else None,
                "num_added": last_run_record.num_added,
                "num_updated": last_run_record.num_updated,
                "bytes_transferred": last_run_record.bytes_transferred,
                "errors": last_run_record.errors,
            }
            last_sync = last_run_record.started_at.isoformat()
        
        # Get total runs count
        total_runs_count = db.execute(
            select(func.count(Run.id))
        ).scalar() or 0
        
        # Get next run time
        scheduler = get_scheduler()
        job_info = scheduler.get_job_info()
        next_run = job_info.get("next_run_time") if job_info else None
        
        # Check database
        db_info = get_db_info()
        database_ok = db_info.get("connection_ok", False)
        
        # Check remote configurations
        remotes_configured = {"gdrive": False, "nextcloud": False}
        
        try:
            base_config = config.get_base_config()
            rclone_config = str(base_config["base_dir"] / base_config["rclone_conf"])
            
            # Check rclone remotes
            result = subprocess.run([
                "rclone", "--config", rclone_config,
                "listremotes"
            ], capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                remotes_list = result.stdout.strip()
                remotes_configured["gdrive"] = "gdrive:" in remotes_list
                remotes_configured["nextcloud"] = any(
                    remote in remotes_list for remote in ["ncwebdav:", "nextcloud:", "nc:"]
                )
        except Exception as e:
            logger.warning(f"Failed to check rclone remotes: {e}")
        
        # Check configuration validity
        sync_config = config.get_sync_config()
        config_valid = bool(
            sync_config.get("gdrive_remote") and 
            sync_config.get("gdrive_src") and 
            sync_config.get("nc_remote") and 
            sync_config.get("nc_dest_path") and
            remotes_configured["gdrive"] and 
            remotes_configured["nextcloud"]
        )
        
        return StatusResponse(
            last_run=last_run,
            last_sync=last_sync,
            next_run=next_run,
            scheduler_running=scheduler.scheduler.running,
            database_ok=database_ok,
            total_runs=total_runs_count,
            config_valid=config_valid,
            remotes_configured=remotes_configured
        )
        
    except Exception as e:
        logger.error(f"Status check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get status: {str(e)}"
        )


# Get runs
@app.get("/runs", response_model=List[RunResponse])
async def get_runs(limit: int = 20, db: Session = Depends(get_db)):
    """Get recent sync runs."""
    try:
        runs = db.execute(
            select(Run)
            .order_by(desc(Run.id))
            .limit(limit)
        ).scalars().all()
        
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
                log_path=run.log_path
            )
            for run in runs
        ]
        
    except Exception as e:
        logger.error(f"Failed to get runs: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get runs: {str(e)}"
        )


# Get run events
@app.get("/runs/{run_id}/events", response_model=List[FileEventResponse])
async def get_run_events(run_id: int, limit: int = 200, db: Session = Depends(get_db)):
    """Get file events for a specific run."""
    try:
        # Verify run exists
        run = db.execute(select(Run).where(Run.id == run_id)).scalars().first()
        if not run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run {run_id} not found"
            )
        
        # Get events
        events = db.execute(
            select(FileEvent)
            .where(FileEvent.run_id == run_id)
            .order_by(desc(FileEvent.id))
            .limit(limit)
        ).scalars().all()
        
        return [
            FileEventResponse(
                id=event.id,
                timestamp=event.timestamp.isoformat(),
                action=event.action,
                file_path=event.file_path,
                file_size=event.file_size,
                file_hash=event.file_hash,
                message=event.message
            )
            for event in events
        ]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get run events: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get run events: {str(e)}"
        )


# Trigger manual sync
@app.post("/runs", response_model=ApiResponse)
async def trigger_sync():
    """Trigger a manual sync run."""
    try:
        scheduler = get_scheduler()
        if scheduler.trigger_sync_now():
            return ApiResponse(
                success=True,
                message="Sync triggered successfully"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to trigger sync"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to trigger sync: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger sync: {str(e)}"
        )


# Configuration endpoints
@app.get("/config", response_model=Dict[str, str])
async def get_config(db: Session = Depends(get_db)):
    """Get current configuration."""
    try:
        config_items = db.execute(select(ConfigKV)).scalars().all()
        return {item.key: item.value for item in config_items}
        
    except Exception as e:
        logger.error(f"Failed to get config: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get configuration: {str(e)}"
        )


@app.post("/config", response_model=ApiResponse)
async def update_config(config_request: ConfigRequest, db: Session = Depends(get_db)):
    """Update sync configuration."""
    try:
        # Update configuration in database
        config_data = config_request.model_dump()
        
        for key, value in config_data.items():
            config_item = ConfigKV(key=key, value=value)
            db.merge(config_item)
        
        db.commit()
        
        logger.info("Configuration updated")
        return ApiResponse(
            success=True,
            message="Configuration updated successfully"
        )
        
    except Exception as e:
        logger.error(f"Failed to update config: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update configuration: {str(e)}"
        )


# Schedule endpoints
@app.get("/schedule", response_model=Dict[str, Any])
async def get_schedule(db: Session = Depends(get_db)):
    """Get current sync schedule."""
    try:
        # Get interval settings from database
        interval_config = db.execute(
            select(ConfigKV).where(ConfigKV.key == "interval_min")
        ).scalar_one_or_none()
        
        jitter_config = db.execute(
            select(ConfigKV).where(ConfigKV.key == "jitter_sec")
        ).scalar_one_or_none()
        
        # Default values if not in database
        interval_min = int(interval_config.value) if interval_config else 5
        jitter_sec = int(jitter_config.value) if jitter_config else 20
        
        # Get scheduler job info
        scheduler = get_scheduler()
        job_info = scheduler.get_job_info()
        
        if job_info:
            return {
                "interval_min": interval_min,
                "jitter_sec": jitter_sec,
                "interval": job_info.get("trigger", "Unknown"),
                "next_run": job_info.get("next_run_time"),
                "active": True
            }
        else:
            return {
                "interval_min": interval_min,
                "jitter_sec": jitter_sec,
                "interval": None,
                "next_run": None,
                "active": False
            }
            
    except Exception as e:
        logger.error(f"Failed to get schedule: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get schedule: {str(e)}"
        )


@app.post("/schedule", response_model=ApiResponse)
async def update_schedule(schedule_request: ScheduleRequest, db: Session = Depends(get_db)):
    """Update sync schedule."""
    try:
        # Save interval settings to database
        interval_config = db.execute(
            select(ConfigKV).where(ConfigKV.key == "interval_min")
        ).scalar_one_or_none()
        
        if interval_config:
            interval_config.value = str(schedule_request.interval_min)
            interval_config.updated_at = datetime.utcnow()
        else:
            interval_config = ConfigKV(
                key="interval_min",
                value=str(schedule_request.interval_min)
            )
            db.add(interval_config)
        
        jitter_config = db.execute(
            select(ConfigKV).where(ConfigKV.key == "jitter_sec")
        ).scalar_one_or_none()
        
        if jitter_config:
            jitter_config.value = str(schedule_request.jitter_sec)
            jitter_config.updated_at = datetime.utcnow()
        else:
            jitter_config = ConfigKV(
                key="jitter_sec",
                value=str(schedule_request.jitter_sec)
            )
            db.add(jitter_config)
        
        db.commit()
        
        # Update scheduler job
        scheduler = get_scheduler()
        success = scheduler.add_sync_job(
            interval_minutes=schedule_request.interval_min,
            jitter_seconds=schedule_request.jitter_sec
        )
        
        if success:
            logger.info(f"Schedule updated: {schedule_request.interval_min}min interval (saved to database)")
            return ApiResponse(
                success=True,
                message=f"Schedule updated to {schedule_request.interval_min} minutes"
            )
        else:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update schedule"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update schedule: {e}")
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update schedule: {str(e)}"
        )


@app.post("/schedule/start", response_model=ApiResponse)
async def start_scheduler_endpoint(db: Session = Depends(get_db)):
    """Start the scheduler."""
    try:
        # Get interval settings from database
        interval_config = db.execute(
            select(ConfigKV).where(ConfigKV.key == "interval_min")
        ).scalar_one_or_none()
        
        jitter_config = db.execute(
            select(ConfigKV).where(ConfigKV.key == "jitter_sec")
        ).scalar_one_or_none()
        
        # Use database values or defaults
        interval_min = int(interval_config.value) if interval_config else 5
        jitter_sec = int(jitter_config.value) if jitter_config else 20
        
        # Start scheduler with saved settings
        from .scheduler import start_scheduler
        success = start_scheduler(interval_minutes=interval_min, jitter_seconds=jitter_sec)
        
        if success:
            logger.info(f"Scheduler started via API with {interval_min}min interval")
            return ApiResponse(
                success=True,
                message="Scheduler started successfully"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to start scheduler"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start scheduler: {str(e)}"
        )


@app.post("/schedule/stop", response_model=ApiResponse)
async def stop_scheduler_endpoint():
    """Stop the scheduler."""
    try:
        from .scheduler import stop_scheduler
        success = stop_scheduler()
        
        if success:
            logger.info("Scheduler stopped via API")
            return ApiResponse(
                success=True,
                message="Scheduler stopped successfully"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to stop scheduler"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to stop scheduler: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to stop scheduler: {str(e)}"
        )


# Database maintenance
@app.post("/maintenance/cleanup", response_model=ApiResponse)
async def cleanup_database(keep_runs: int = 100, db: Session = Depends(get_db)):
    """Clean up old run records."""
    try:
        deleted_count = cleanup_old_runs(db, keep_runs)
        
        return ApiResponse(
            success=True,
            message=f"Cleaned up {deleted_count} old run records",
            data={"deleted_count": deleted_count}
        )
        
    except Exception as e:
        logger.error(f"Database cleanup failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database cleanup failed: {str(e)}"
        )


@app.post("/maintenance/reset", response_model=ApiResponse)
async def reset_database(db: Session = Depends(get_db)):
    """Reset database by deleting all runs and file events."""
    try:
        # Count existing records before deletion
        runs_count = db.execute(select(func.count(Run.id))).scalar() or 0
        events_count = db.execute(select(func.count(FileEvent.id))).scalar() or 0
        
        # Delete all file events first (due to foreign key constraint)
        from sqlalchemy import delete
        db.execute(delete(FileEvent))
        
        # Delete all runs
        db.execute(delete(Run))
        
        # Commit the changes
        db.commit()
        
        logger.info(f"Database reset: deleted {runs_count} runs and {events_count} file events")
        
        return ApiResponse(
            success=True,
            message=f"Database reset successfully. Deleted {runs_count} runs and {events_count} file events.",
            data={
                "runs_deleted": runs_count,
                "events_deleted": events_count,
                "total_deleted": runs_count + events_count
            }
        )
        
    except Exception as e:
        logger.error(f"Database reset failed: {e}")
        db.rollback()  # Rollback on error
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database reset failed: {str(e)}"
        )


@app.get("/debug/rclone-logs")
async def debug_rclone_logs(limit: int = 50):
    """Debug endpoint to show recent rclone log entries."""
    try:
        from pathlib import Path
        log_dir = Path("/srv/mascloner/logs")
        log_files = list(log_dir.glob("sync-*.log"))
        
        if not log_files:
            return {"message": "No sync log files found", "logs": []}
        
        # Get the most recent log file
        latest_log = max(log_files, key=lambda f: f.stat().st_mtime)
        
        # Read last N lines
        with open(latest_log, 'r') as f:
            lines = f.readlines()
            recent_lines = lines[-limit:] if len(lines) > limit else lines
        
        # Parse each line to see what we get
        parsed_logs = []
        for i, line in enumerate(recent_lines):
            line = line.strip()
            if not line:
                continue
                
            try:
                # Try to parse as JSON
                obj = json.loads(line)
                parsed_logs.append({
                    "line_number": len(lines) - limit + i + 1,
                    "raw": line,
                    "parsed": obj,
                    "type": "json"
                })
            except json.JSONDecodeError:
                parsed_logs.append({
                    "line_number": len(lines) - limit + i + 1,
                    "raw": line,
                    "parsed": None,
                    "type": "text"
                })
        
        return {
            "log_file": str(latest_log),
            "total_lines": len(lines),
            "recent_lines": len(recent_lines),
            "logs": parsed_logs
        }
        
    except Exception as e:
        logger.error(f"Debug log reading failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read logs: {str(e)}"
        )


@app.get("/debug/database")
async def debug_database(db: Session = Depends(get_db)):
    """Debug endpoint to check database state."""
    try:
        # Count records
        runs_count = db.execute(select(func.count(Run.id))).scalar() or 0
        events_count = db.execute(select(func.count(FileEvent.id))).scalar() or 0
        
        # Get recent runs
        recent_runs = db.execute(
            select(Run).order_by(desc(Run.started_at)).limit(5)
        ).scalars().all()
        
        # Get recent events
        recent_events = db.execute(
            select(FileEvent).order_by(desc(FileEvent.timestamp)).limit(10)
        ).scalars().all()
        
        # Convert to dict for JSON serialization
        runs_data = []
        for run in recent_runs:
            runs_data.append({
                "id": run.id,
                "started_at": run.started_at.isoformat() if run.started_at else None,
                "status": run.status,
                "num_added": run.num_added,
                "num_updated": run.num_updated,
                "bytes_transferred": run.bytes_transferred,
                "errors": run.errors
            })
        
        events_data = []
        for event in recent_events:
            events_data.append({
                "id": event.id,
                "timestamp": event.timestamp.isoformat() if event.timestamp else None,
                "action": event.action,
                "file_path": event.file_path,
                "file_size": event.file_size,
                "message": event.message
            })
        
        return {
            "database_state": {
                "total_runs": runs_count,
                "total_events": events_count,
                "recent_runs": runs_data,
                "recent_events": events_data
            }
        }
        
    except Exception as e:
        logger.error(f"Debug database check failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check database: {str(e)}"
        )


@app.post("/debug/test-parser")
async def test_parser(test_line: str):
    """Test the rclone log parser with a sample line."""
    try:
        from .rclone_runner import RcloneLogParser
        
        parser = RcloneLogParser()
        
        # Test JSON parsing
        json_result = parser.parse_line(test_line)
        
        # Test stats parsing
        stats_result = parser.parse_stats_line(test_line)
        
        return {
            "input_line": test_line,
            "json_parsed": json_result.__dict__ if json_result else None,
            "stats_parsed": stats_result,
            "is_json": test_line.strip().startswith('{'),
            "contains_transferred": "transferred" in test_line.lower(),
            "contains_files": "files" in test_line.lower()
        }
        
    except Exception as e:
        logger.error(f"Parser test failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Parser test failed: {str(e)}"
        )


@app.get("/debug/test-official-format")
async def test_official_format():
    """Test the parser with official rclone JSON log format examples."""
    try:
        from .rclone_runner import RcloneLogParser
        
        parser = RcloneLogParser()
        
        # Official rclone JSON log format examples
        test_cases = [
            # Individual file transfer
            '{"time":"2024-01-05T12:45:54.986126-05:00","level":"info","msg":"Copied (new) to: file.txt","size":12345,"object":"file.txt","objectType":"*local.Object","source":"operations/copy.go:368"}',
            
            # File replacement
            '{"time":"2024-01-05T12:45:54.986126-05:00","level":"info","msg":"Copied (replaced) to: existing_file.txt","size":54321,"object":"existing_file.txt","objectType":"*local.Object","source":"operations/copy.go:368"}',
            
            # Stats line
            '{"level":"notice","msg":"Transferred:   953.674 MiB / 953.674 MiB, 100%, 86.682 MiB/s, ETA 0s","source":"accounting/stats.go:482","stats":{"bytes":1000000000,"checks":0,"deletedDirs":0,"deletes":0,"elapsedTime":12.26351236,"errors":0,"eta":0,"fatalError":false,"renames":0,"retryError":false,"speed":90893100.62791826,"totalBytes":1000000000,"totalChecks":0,"totalTransfers":1,"transferTime":0,"transfers":1},"time":"2024-01-05T12:45:54.986126-05:00"}',
            
            # Error case
            '{"time":"2024-01-05T12:45:54.986126-05:00","level":"error","msg":"Failed to copy: error_file.txt","object":"error_file.txt","source":"operations/copy.go:368"}'
        ]
        
        results = []
        for i, test_case in enumerate(test_cases):
            json_result = parser.parse_line(test_case)
            stats_result = parser.parse_stats_line(test_case)
            
            results.append({
                "test_case": i + 1,
                "input": test_case,
                "json_parsed": json_result.__dict__ if json_result else None,
                "stats_parsed": stats_result
            })
        
        return {
            "message": "Official rclone JSON format test results",
            "test_cases": results
        }
        
    except Exception as e:
        logger.error(f"Official format test failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Official format test failed: {str(e)}"
        )


# Get all events
@app.get("/events", response_model=List[FileEventResponse])
async def get_events(limit: int = 200, db: Session = Depends(get_db)):
    """Get recent file events across all runs."""
    try:
        events = db.execute(
            select(FileEvent)
            .order_by(desc(FileEvent.id))
            .limit(limit)
        ).scalars().all()
        
        return [
            FileEventResponse(
                id=event.id,
                timestamp=event.timestamp.isoformat(),
                action=event.action,
                file_path=event.file_path,
                file_size=event.file_size,
                file_hash=event.file_hash,
                message=event.message
            )
            for event in events
        ]
        
    except Exception as e:
        logger.error(f"Failed to get events: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get events: {str(e)}"
        )


# Tree view models
class TreeNodeResponse(BaseModel):
    """Tree node for API response."""
    name: str
    path: str
    type: str  # file | folder
    size: int = 0
    last_sync: Optional[str] = None
    status: str = "unknown"  # synced | pending | error | conflict
    children: List["TreeNodeResponse"] = []


class TreeResponse(BaseModel):
    """Response model for file tree."""
    root: TreeNodeResponse
    total_files: int
    total_folders: int


def _convert_tree_node(node) -> TreeNodeResponse:
    """Convert TreeNode to TreeNodeResponse."""
    return TreeNodeResponse(
        name=node.name,
        path=node.path,
        type=node.type,
        size=node.size,
        last_sync=node.last_sync,
        status=node.status,
        children=[_convert_tree_node(child) for child in node.children]
    )


@app.get("/tree", response_model=TreeResponse)
async def get_file_tree(path: str = "", db: Session = Depends(get_db)):
    """Get file tree structure with sync status."""
    try:
        # Get all file events to build tree
        events = db.execute(
            select(FileEvent)
            .order_by(desc(FileEvent.timestamp))
        ).scalars().all()
        
        # Build tree structure
        tree_builder = FileTreeBuilder()
        root_node = tree_builder.build_tree(events, path)
        
        # Count statistics
        stats = tree_builder.get_statistics(root_node)
        
        # Convert to response model
        root_response = _convert_tree_node(root_node)
        
        return TreeResponse(
            root=root_response,
            total_files=stats["files"],
            total_folders=stats["folders"]
        )
        
    except Exception as e:
        logger.error(f"Failed to get file tree: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get file tree: {str(e)}"
        )


@app.get("/tree/status/{path:path}", response_model=Dict[str, Any])
async def get_path_status(path: str, db: Session = Depends(get_db)):
    """Get sync status for a specific path."""
    try:
        # Get most recent event for this path
        latest_event = db.execute(
            select(FileEvent)
            .where(FileEvent.file_path == path)
            .order_by(desc(FileEvent.timestamp))
        ).scalars().first()
        
        if latest_event:
            return {
                "path": path,
                "status": latest_event.action,
                "last_sync": latest_event.timestamp.isoformat(),
                "size": latest_event.file_size,
                "message": latest_event.message
            }
        else:
            return {
                "path": path,
                "status": "unknown",
                "last_sync": None,
                "size": 0,
                "message": "No sync history"
            }
            
    except Exception as e:
        logger.error(f"Failed to get path status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get path status: {str(e)}"
        )


# Enhanced remote testing and configuration
class WebDAVTestRequest(BaseModel):
    """Request model for WebDAV connection testing."""
    url: str
    user: str
    pass_: str = Field(alias="pass")
    remote_name: str


@app.post("/test/nextcloud/webdav", response_model=ApiResponse)
async def test_nextcloud_webdav(request: WebDAVTestRequest):
    """Test Nextcloud WebDAV connection and create rclone remote."""
    try:
        # Import rclone runner for testing
        from .rclone_runner import RcloneRunner
        
        runner = RcloneRunner()
        
        # Test WebDAV connection
        test_result = runner.test_webdav_connection(
            url=request.url,
            user=request.user,
            password=request.pass_,
            remote_name=request.remote_name
        )
        
        if test_result["success"]:
            return ApiResponse(
                success=True,
                message="Nextcloud WebDAV connection successful and remote created",
                data={"remote_name": request.remote_name}
            )
        else:
            return ApiResponse(
                success=False,
                message=f"WebDAV connection failed: {test_result.get('error', 'Unknown error')}"
            )
            
    except Exception as e:
        logger.error(f"WebDAV test failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"WebDAV test failed: {str(e)}"
        )


@app.get("/browse/folders/{remote_name}", response_model=Dict[str, Any])
async def browse_remote_folders(remote_name: str, path: str = ""):
    """Browse folders in a remote."""
    try:
        from .rclone_runner import RcloneRunner
        
        runner = RcloneRunner()
        folders = runner.list_folders(remote_name, path)
        
        return {
            "status": "success",
            "folders": folders,
            "remote": remote_name,
            "path": path
        }
        
    except Exception as e:
        logger.error(f"Failed to browse folders: {e}")
        return {
            "status": "error",
            "error": str(e),
            "folders": []
        }


@app.get("/estimate/size", response_model=Dict[str, Any])
async def estimate_sync_size(source: str, dest: str):
    """Estimate the size of a sync operation."""
    try:
        from .rclone_runner import RcloneRunner
        
        runner = RcloneRunner()
        size_info = runner.estimate_sync_size(source, dest)
        
        return {
            "status": "success",
            "size_mb": size_info.get("size_mb", 0),
            "file_count": size_info.get("file_count", 0),
            "folder_count": size_info.get("folder_count", 0)
        }
        
    except Exception as e:
        logger.error(f"Failed to estimate size: {e}")
        return {
            "status": "error",
            "error": str(e),
            "size_mb": 0,
            "file_count": 0
        }


# Database info
@app.get("/database/info", response_model=Dict[str, Any])
async def get_database_info():
    """Get database information and statistics."""
    try:
        return get_db_info()
        
    except Exception as e:
        logger.error(f"Failed to get database info: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get database info: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    
    # Get configuration
    if config:
        api_config = config.get_api_config()
        host = api_config["host"]
        port = api_config["port"]
    else:
        host = "127.0.0.1"
        port = 8787
    
    uvicorn.run(
        "app.api.main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info"
    )
