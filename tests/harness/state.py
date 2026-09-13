"""Process-global state reset manager for hermetic testing.

Ensures that tests can reset environment variables, configuration caches,
database engine and sessions, dependency providers, rclone runner singletons,
and background schedulers between test runs.
"""

from __future__ import annotations

from app.api.dependencies import reset_dependencies

import os
import threading
from typing import Any, Dict, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.api.config as api_config
import app.api.db as api_db
import app.api.dependencies as api_deps
import app.api.main as api_main
import app.api.rclone_runner as api_runner
import app.api.routers.config as router_config
import app.api.routers.google_drive as router_gdrive
import app.api.scheduler as api_scheduler


class ProcessStateReset:
    """Context manager and helper to reset all process-global state."""

    def __init__(self, env_overlay: Optional[Dict[str, str]] = None):
        self.env_overlay = env_overlay or {}
        self._orig_env: Dict[str, str] = {}
        self._orig_db_engine = None
        self._orig_db_sessionmaker = None
        self._orig_db_path = None

    def __enter__(self) -> ProcessStateReset:
        self.save_and_apply()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.restore()

    def save_and_apply(self) -> None:
        """Save current state and apply environment overlays."""
        self._orig_env = dict(os.environ)
        self._orig_db_engine = api_db.engine
        self._orig_db_sessionmaker = api_db.SessionLocal
        self._orig_db_path = api_db.DB_PATH

        # Apply environment overlay
        for k, v in self.env_overlay.items():
            os.environ[k] = v

        self.reset_all()

    def reset_all(self) -> None:
        """Reset all global modules to match current os.environ."""
        # 1. Reset ConfigManager
        try:
            fresh_config = api_config.ConfigManager()
            api_config.config = fresh_config
            api_runner.config = fresh_config
            api_scheduler.config = fresh_config
            api_main.config = fresh_config
            router_config.config = fresh_config
            router_gdrive.config = fresh_config
        except Exception:
            pass

        # 2. Reset Dependencies LRU caches
        api_deps.reset_dependencies()

        # 3. Reset Rclone Runner singleton
        api_runner._runner = None

        # 4. Reset Database Engine & SessionLocal
        new_db_path = os.environ.get("MASCLONER_DB_PATH", api_db.DB_PATH)
        api_db.DB_PATH = new_db_path
        if self._orig_db_engine != api_db.engine and api_db.engine is not None:
            try:
                api_db.engine.dispose()
            except Exception:
                pass

        from app.api.db import create_sqlite_engine
        new_engine = create_sqlite_engine(new_db_path)
        api_db.engine = new_engine
        api_db.SessionLocal = sessionmaker(
            bind=new_engine,
            autoflush=False,
            autocommit=False,
            future=True,
        )

        # 5. Reset Scheduler & Locks
        try:
            if api_scheduler.sync_scheduler.scheduler.running:
                api_scheduler.sync_scheduler.stop()
        except Exception:
            pass

        api_scheduler._sync_lock = threading.Lock()
        api_scheduler.scheduler = BackgroundScheduler(timezone="UTC")
        api_scheduler.sync_scheduler.scheduler = api_scheduler.scheduler
        api_scheduler.sync_scheduler.runner = api_runner.get_runner()
        reset_dependencies()

        try:
            from app.execution import SyncExecutor
            SyncExecutor.reset_instance()
        except Exception:
            pass

    def restore(self) -> None:
        """Restore original environment and references."""
        # Stop scheduler if running
        try:
            if api_scheduler.sync_scheduler.scheduler.running:
                api_scheduler.sync_scheduler.stop()
        except Exception:
            pass

        try:
            from app.execution import SyncExecutor
            SyncExecutor.reset_instance()
        except Exception:
            pass

        # Dispose temporary engine
        if api_db.engine is not None and api_db.engine != self._orig_db_engine:
            try:
                api_db.engine.dispose()
            except Exception:
                pass

        # Restore database references
        if self._orig_db_engine is not None:
            api_db.engine = self._orig_db_engine
            api_db.SessionLocal = self._orig_db_sessionmaker
            api_db.DB_PATH = self._orig_db_path

        # Restore environment
        os.environ.clear()
        os.environ.update(self._orig_env)

        reset_dependencies()
        # Re-reset config with restored env
        try:
            restored_config = api_config.ConfigManager()
            api_config.config = restored_config
            api_runner.config = restored_config
            api_scheduler.config = restored_config
            api_main.config = restored_config
            router_config.config = restored_config
            router_gdrive.config = restored_config
        except Exception:
            pass

        api_deps.reset_dependencies()
        api_runner._runner = None
        api_scheduler._sync_lock = threading.Lock()
        api_scheduler.scheduler = BackgroundScheduler(timezone="UTC")
        api_scheduler.sync_scheduler.scheduler = api_scheduler.scheduler
