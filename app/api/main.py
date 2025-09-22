"""FastAPI application for MasCloner API."""

import logging
from contextlib import asynccontextmanager
from typing import List, Optional, Dict, Any

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import select, desc
from sqlalchemy.orm import Session

from .db import init_db, get_db, get_db_info
from .models import Run, FileEvent, ConfigKV
from .scheduler import start_scheduler, stop_scheduler, get_scheduler, sync_job, cleanup_old_runs
from .config import config
from .tree_builder import FileTreeBuilder

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
    next_run: Optional[str] = None
    scheduler_running: bool
    database_ok: bool


class ApiResponse(BaseModel):
    """Generic API response model."""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


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
        
        # Get next run time
        scheduler = get_scheduler()
        job_info = scheduler.get_job_info()
        next_run = job_info.get("next_run_time") if job_info else None
        
        # Check database
        db_info = get_db_info()
        database_ok = db_info.get("connection_ok", False)
        
        return StatusResponse(
            last_run=last_run,
            next_run=next_run,
            scheduler_running=scheduler.scheduler.running,
            database_ok=database_ok
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
async def get_schedule():
    """Get current sync schedule."""
    try:
        scheduler = get_scheduler()
        job_info = scheduler.get_job_info()
        
        if job_info:
            return {
                "interval": job_info.get("trigger", "Unknown"),
                "next_run": job_info.get("next_run_time"),
                "active": True
            }
        else:
            return {
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
async def update_schedule(schedule_request: ScheduleRequest):
    """Update sync schedule."""
    try:
        scheduler = get_scheduler()
        
        success = scheduler.add_sync_job(
            interval_minutes=schedule_request.interval_min,
            jitter_seconds=schedule_request.jitter_sec
        )
        
        if success:
            logger.info(f"Schedule updated: {schedule_request.interval_min}min interval")
            return ApiResponse(
                success=True,
                message=f"Schedule updated to {schedule_request.interval_min} minutes"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update schedule"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update schedule: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update schedule: {str(e)}"
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
