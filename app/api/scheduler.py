"""APScheduler integration for MasCloner sync jobs."""

from __future__ import annotations

import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import config, get_log_dir
from .db import get_db_session
from .models import Run, FileEvent, ConfigKV
from .rclone_runner import get_runner, SyncResult

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = BackgroundScheduler(timezone='UTC')
_sync_lock = threading.Lock()


class SyncScheduler:
    """Manages sync job scheduling and execution."""
    
    def __init__(self):
        self.scheduler = scheduler
        self.runner = get_runner()
    
    def start(self) -> None:
        """Start the scheduler."""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Sync scheduler started")
        else:
            logger.info("Sync scheduler already running")
    
    def stop(self) -> None:
        """Stop the scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Sync scheduler stopped")
        else:
            logger.info("Sync scheduler not running")
    
    def add_sync_job(
        self,
        interval_minutes: int = 5,
        jitter_seconds: int = 20,
        job_id: str = "sync"
    ) -> bool:
        """Add or update the sync job with specified interval."""
        try:
            trigger = IntervalTrigger(
                minutes=interval_minutes,
                jitter=jitter_seconds
            )
            
            self.scheduler.add_job(
                func=sync_job,
                trigger=trigger,
                id=job_id,
                replace_existing=True,
                max_instances=1,  # Prevent overlapping runs
                name=f"MasCloner Sync ({interval_minutes}min)"
            )
            
            logger.info(f"Sync job scheduled: every {interval_minutes} minutes (±{jitter_seconds}s jitter)")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add sync job: {e}")
            return False
    
    def remove_sync_job(self, job_id: str = "sync") -> bool:
        """Remove the sync job."""
        try:
            self.scheduler.remove_job(job_id)
            logger.info("Sync job removed")
            return True
        except Exception as e:
            logger.error(f"Failed to remove sync job: {e}")
            return False
    
    def get_job_info(self, job_id: str = "sync") -> Optional[Dict[str, Any]]:
        """Get information about the sync job."""
        try:
            job = self.scheduler.get_job(job_id)
            if job:
                return {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                    "trigger": str(job.trigger),
                    "max_instances": job.max_instances,
                }
            else:
                return None
        except Exception as e:
            logger.error(f"Failed to get job info: {e}")
            return None
    
    def trigger_sync_now(self) -> bool:
        """Trigger an immediate sync run."""
        try:
            # Run sync job in a separate thread to avoid blocking
            sync_thread = threading.Thread(target=sync_job, daemon=True)
            sync_thread.start()
            logger.info("Manual sync triggered")
            return True
        except Exception as e:
            logger.error("Failed to trigger manual sync: %s", e)
            return False


def get_sync_config_from_db(db: Session) -> Dict[str, str]:
    """Get sync configuration from database and environment."""
    # Get config from database
    db_config = {}
    config_items = db.execute(select(ConfigKV)).scalars().all()
    for item in config_items:
        db_config[item.key] = item.value
    
    # Get sync configuration with database override
    if config:
        sync_config = config.get_sync_config()
    else:
        # Fallback defaults
        sync_config = {
            "gdrive_remote": "gdrive",
            "gdrive_src": "",
            "nc_remote": "ncwebdav", 
            "nc_dest_path": "",
            "nc_webdav_url": "",
            "nc_user": "",
            "nc_pass_obscured": "",
        }
    
    # Override with database values
    for key in sync_config:
        if key in db_config:
            sync_config[key] = db_config[key]
    
    return sync_config


def validate_sync_config(sync_config: Dict[str, str]) -> tuple[bool, list[str]]:
    """Validate sync configuration."""
    errors = []
    
    required_fields = [
        "gdrive_remote",
        "gdrive_src", 
        "nc_remote",
        "nc_dest_path"
    ]
    
    for field in required_fields:
        if not sync_config.get(field):
            errors.append(f"Missing required configuration: {field}")
    
    return len(errors) == 0, errors


def sync_job() -> None:
    """Main sync job function."""
    # Acquire lock to prevent concurrent runs
    if not _sync_lock.acquire(blocking=False):
        logger.warning("Sync job already running, skipping this execution")
        return
    
    db: Optional[Session] = None
    run: Optional[Run] = None
    
    try:
        logger.info("Starting sync job")
        
        # Get database session
        db = get_db_session()
        
        # Get sync configuration
        sync_config = get_sync_config_from_db(db)
        
        # Validate configuration
        config_valid, config_errors = validate_sync_config(sync_config)
        if not config_valid:
            logger.error(f"Invalid sync configuration: {config_errors}")
            return
        
        # Create run record
        log_dir = get_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        log_filename = f"sync-{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.log"
        log_path = log_dir / log_filename
        
        run = Run(
            status="running",
            log_path=str(log_path)
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        
        logger.info(f"Created sync run {run.id}")
        
        # Execute sync
        runner = get_runner()
        
        # Set current run info for live monitoring
        runner.set_current_run(run.id, str(log_path))
        
        try:
            result = runner.run_sync(
                gdrive_remote=sync_config["gdrive_remote"],
                gdrive_src=sync_config["gdrive_src"],
                nc_remote=sync_config["nc_remote"],
                nc_dest_path=sync_config["nc_dest_path"],
                dry_run=False
            )
        finally:
            # Clear current run info when done
            runner.clear_current_run()
        
        # Update run with results
        run.status = result.status
        run.num_added = result.num_added
        run.num_updated = result.num_updated
        run.bytes_transferred = result.bytes_transferred
        run.errors = result.errors
        run.finished_at = datetime.now(timezone.utc)
        
        # Add file events unless lightweight mode is enabled
        lightweight_events = os.getenv("MASCLONER_LIGHTWEIGHT_EVENTS", "0").lower() in ("1", "true", "yes", "on")
        if not lightweight_events:
            for event in result.events:
                file_event = FileEvent(
                    run_id=run.id,
                    timestamp=event.timestamp,
                    action=event.action,
                    file_path=event.file_path,
                    file_size=event.file_size,
                    file_hash=event.file_hash,
                    message=event.message
                )
                db.add(file_event)
        
        db.commit()
        
        logger.info(f"Sync job completed: {result.status}")
        logger.info(f"Files: {result.num_added} added, {result.num_updated} updated")
        logger.info(f"Bytes transferred: {result.bytes_transferred}")
        logger.info(f"Errors: {result.errors}")
        
    except Exception as e:
        logger.error(f"Sync job failed: {e}")
        
        # Update run status if we have a run record
        if run and db:
            try:
                run.status = "error"
                run.finished_at = datetime.now(timezone.utc)
                
                # Add error event
                error_event = FileEvent(
                    run_id=run.id,
                    timestamp=datetime.now(timezone.utc),
                    action="error",
                    file_path="",
                    file_size=0,
                    message=f"Sync job error: {str(e)}"
                )
                db.add(error_event)
                db.commit()
            except Exception as commit_error:
                logger.error(f"Failed to update run status: {commit_error}")
    
    finally:
        # Clean up
        if db:
            db.close()
        _sync_lock.release()
        logger.info("Sync job finished")


def cleanup_old_runs(db: Session, keep_runs: int = 100) -> int:
    """Clean up old run records, keeping the most recent ones."""
    try:
        # Get runs older than the keep_runs threshold
        runs_to_keep = db.execute(
            select(Run.id)
            .order_by(Run.started_at.desc())
            .limit(keep_runs)
        ).scalars().all()
        
        if len(runs_to_keep) < keep_runs:
            return 0  # Not enough runs to clean up
        
        # Delete runs not in the keep list
        from sqlalchemy import delete
        deleted = db.execute(
            delete(Run).where(Run.id.notin_(runs_to_keep))
        )
        
        db.commit()
        deleted_count = deleted.rowcount
        
        logger.info(f"Cleaned up {deleted_count} old run records")
        return deleted_count
        
    except Exception as e:
        logger.error(f"Failed to clean up old runs: {e}")
        db.rollback()
        return 0


# Global scheduler instance
sync_scheduler = SyncScheduler()


def get_scheduler() -> SyncScheduler:
    """Get the global sync scheduler instance."""
    return sync_scheduler


def start_scheduler(interval_minutes: Optional[int] = None, jitter_seconds: Optional[int] = None) -> bool:
    """Start the scheduler with configuration from environment/database."""
    try:
        # If no explicit values provided, try to load from database first
        if interval_minutes is None or jitter_seconds is None:
            try:
                db = get_db_session()
                
                # Try to load from database
                interval_config = db.execute(
                    select(ConfigKV).where(ConfigKV.key == "interval_min")
                ).scalar_one_or_none()
                
                jitter_config = db.execute(
                    select(ConfigKV).where(ConfigKV.key == "jitter_sec")
                ).scalar_one_or_none()
                
                # Use database values if available
                interval = interval_minutes or (int(interval_config.value) if interval_config else None)
                jitter = jitter_seconds or (int(jitter_config.value) if jitter_config else None)
                
                db.close()
            except Exception as e:
                logger.warning(f"Could not load schedule from database: {e}")
                interval = interval_minutes
                jitter = jitter_seconds
        else:
            interval = interval_minutes
            jitter = jitter_seconds
        
        # Fall back to config/environment defaults if still None
        if interval is None or jitter is None:
            if config:
                scheduler_config = config.get_scheduler_config()
                interval = interval or scheduler_config["interval_min"]
                jitter = jitter or scheduler_config["jitter_sec"]
            else:
                interval = interval or 5
                jitter = jitter or 20
        
        # Start scheduler
        sync_scheduler.start()
        
        # Add sync job
        sync_scheduler.add_sync_job(interval, jitter)
        
        logger.info(f"Scheduler started with {interval}min interval")
        return True
        
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")
        return False


def stop_scheduler() -> bool:
    """Stop the scheduler."""
    try:
        sync_scheduler.stop()
        return True
    except Exception as e:
        logger.error(f"Failed to stop scheduler: {e}")
        return False
