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
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import config, get_log_dir
from .db import get_db_session
from .models import Run, FileEvent, ConfigKV, SyncStatus
from .rclone_runner import get_runner, SyncResult

logger = logging.getLogger(__name__)

# Global scheduler instance
scheduler = BackgroundScheduler(timezone='UTC')
_sync_lock = threading.Lock()


class SyncScheduler:
    """Manages sync job scheduling and execution."""
    
    def __init__(self) -> None:
        self.scheduler = scheduler

    @property
    def runner(self):
        from .rclone_runner import get_runner
        return getattr(self, "_runner", None) or get_runner()

    @runner.setter
    def runner(self, value):
        self._runner = value
    
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
            if self.scheduler.get_job(job_id):
                self.scheduler.remove_job(job_id)
                logger.info("Sync job removed")
            return True
        except Exception as e:
            logger.error(f"Failed to remove sync job: {e}")
            return False

    def is_running(self) -> bool:
        """Check if the background scheduler engine is running."""
        return bool(self.scheduler.running)

    def is_enabled(self, job_id: str = "sync") -> bool:
        """Check if scheduler is running and the sync job is scheduled."""
        return bool(self.scheduler.running and self.scheduler.get_job(job_id) is not None)

    def has_sync_job(self, job_id: str = "sync") -> bool:
        """Check if sync job is registered in scheduler."""
        return bool(self.scheduler.get_job(job_id) is not None)
    
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
        """Trigger an immediate sync run using SyncExecutor."""
        try:
            from ..execution import SyncExecutor
            res = SyncExecutor.get_instance().trigger_manual_run()
            logger.info("Manual sync triggered via SyncExecutor: accepted=%s", res.accepted)
            return res.accepted
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


def reconcile_stale_runs(session_factory: Optional[Any] = None) -> int:
    """Startup recovery: reconcile stale non-terminal runs to failed."""
    get_session = session_factory or get_db_session
    recovered_count = 0
    with get_session() as db:
        stale_runs = db.execute(
            select(Run).where(Run.status.in_([SyncStatus.PENDING, SyncStatus.RUNNING]))
        ).scalars().all()

        now_utc = datetime.now(timezone.utc)
        for run in stale_runs:
            run.transition_to(
                SyncStatus.FAILED,
                message="Interrupted: previous process terminated while run was active (startup recovery)",
            )
            run.finished_at = now_utc
            run.errors = (run.errors or 0) + 1
            recovered_count += 1

            recovery_event = FileEvent(
                run_id=run.id,
                timestamp=now_utc,
                action="error",
                file_path="",
                file_size=0,
                message="Run recovered on startup: marked failed due to process termination",
            )
            db.add(recovery_event)

        if recovered_count > 0:
            db.commit()
            logger.warning("Startup recovery: marked %d stale run(s) as failed", recovered_count)

    return recovered_count


def sync_job(wait: bool = True) -> Any:
    """Main scheduled sync job function executing through SyncExecutor."""
    from ..execution import SyncExecutor

    logger.info("Starting scheduled sync job through SyncExecutor")
    try:
        executor = SyncExecutor.get_instance()
        result = executor.trigger_scheduled_run(wait=wait)
        if not result.accepted:
            logger.warning(
                "Scheduled sync run skipped or rejected (run %s): %s",
                result.run_id,
                result.message,
            )
        else:
            logger.info(
                "Scheduled sync run %s status: %s (%s)",
                result.run_id,
                result.status,
                result.message,
            )
        return result
    except Exception as exc:
        logger.error("Error executing scheduled sync job: %s", exc)
        return None


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


def start_scheduler(
    schedule: Optional[Any] = None,
    interval_min: Optional[int] = None,
    jitter_sec: Optional[int] = None,
    enabled: Optional[bool] = None,
    *,
    interval_minutes: Optional[int] = None,
    jitter_seconds: Optional[int] = None,
) -> bool:
    """Start the scheduler with durable configuration from SQLite."""
    try:
        from ..configuration import Configuration, ScheduleSettings
        from .db import get_db_session

        if schedule is not None:
            schedule_settings = schedule
        else:
            try:
                cfg = Configuration(session_factory=get_db_session)
                schedule_settings = cfg.get_schedule()
            except Exception as e:
                logger.warning("Could not load schedule from Configuration: %s", e)
                schedule_settings = ScheduleSettings()

        eff_interval = interval_min or interval_minutes or schedule_settings.interval_min
        eff_jitter = jitter_sec or jitter_seconds or schedule_settings.jitter_sec
        is_enabled = enabled if enabled is not None else schedule_settings.enabled

        sync_scheduler.start()

        if is_enabled:
            sync_scheduler.add_sync_job(eff_interval, eff_jitter)
            logger.info("Scheduler started with %dmin interval (±%ds jitter)", eff_interval, eff_jitter)
        else:
            sync_scheduler.remove_sync_job()
            logger.info("Scheduler started with sync job disabled")

        return True
    except Exception as e:
        logger.error("Failed to start scheduler: %s", e)
        return False


def stop_scheduler() -> bool:
    """Stop the scheduler."""
    try:
        sync_scheduler.stop()
        return True
    except Exception as e:
        logger.error(f"Failed to stop scheduler: {e}")
        return False
