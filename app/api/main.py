"""FastAPI main application module."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import List

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .auth import is_auth_enabled, require_auth
from .config import config
from .db import init_db
from .exceptions import register_exception_handlers
from .routers import browse as browse_router
from .routers import config as config_router
from .routers import google_drive as google_drive_router
from .routers import maintenance as maintenance_router
from .routers import nextcloud as nextcloud_router
from .routers import runs as runs_router
from .routers import schedule as schedule_router
from .scheduler import start_scheduler, stop_scheduler, reconcile_stale_runs

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting MasCloner API...")

    # Log authentication status
    if is_auth_enabled():
        logger.info("Authentication is ENABLED")
    else:
        logger.warning(
            "Authentication is DISABLED. Set MASCLONER_AUTH_ENABLED=1 "
            "with MASCLONER_AUTH_USERNAME and MASCLONER_AUTH_PASSWORD for production."
        )

    try:
        from ..execution import SyncExecutor
        from ..retention import RetentionService
        SyncExecutor.reset_instance()
        RetentionService.reset_instance()
        init_db()
        logger.info("Database initialized")

        reconciled = reconcile_stale_runs()
        if reconciled > 0:
            logger.info("Reconciled %d stale run(s) on startup", reconciled)

        if start_scheduler():
            logger.info("Scheduler started")
        else:
            logger.warning("Failed to start scheduler")
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Startup failed: %s", exc)
        raise

    yield

    logger.info("Shutting down MasCloner API...")
    try:
        if stop_scheduler():
            logger.info("Scheduler stopped")
        else:
            logger.warning("Failed to stop scheduler cleanly")
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Shutdown error: %s", exc)

    try:
        from ..execution import SyncExecutor
        executor = SyncExecutor.get_instance()
        executor.shutdown(timeout=10.0)
        SyncExecutor.reset_instance()
        from ..retention import RetentionService
        RetentionService.reset_instance()
        logger.info("SyncExecutor shutdown completed")
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("SyncExecutor shutdown error: %s", exc)


app = FastAPI(
    title="MasCloner API",
    description="REST API for MasCloner Google Drive to Nextcloud sync service",
    version="3.0.0",
    lifespan=lifespan,
)

# Register custom exception handlers for standard error responses
register_exception_handlers(app)

# Configure CORS for local frontend access
allowed_origins = [
    "http://localhost:8501",  # Streamlit default
    "http://127.0.0.1:8501",
]

# Allow dynamic configuration of CORS origins
if config:
    ui_config = config.get_ui_config()
    ui_host = ui_config["host"]
    ui_port = ui_config["port"]

    if ui_host not in ["localhost", "127.0.0.1"]:
        allowed_origins.extend([
            f"http://{ui_host}:{ui_port}",
            f"https://{ui_host}:{ui_port}",
        ])

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers with authentication if enabled
router_dependencies: List[Depends] = []
if is_auth_enabled():
    router_dependencies.append(Depends(require_auth))

app.include_router(config_router.router, dependencies=router_dependencies)
app.include_router(runs_router.router, dependencies=router_dependencies)
app.include_router(runs_router.events_router, dependencies=router_dependencies)
app.include_router(schedule_router.router, dependencies=router_dependencies)
app.include_router(browse_router.router, dependencies=router_dependencies)
app.include_router(google_drive_router.router, dependencies=router_dependencies)
app.include_router(nextcloud_router.router, dependencies=router_dependencies)
app.include_router(maintenance_router.router, dependencies=router_dependencies)


if __name__ == "__main__":  # pragma: no cover
    import uvicorn

    if config:
        api_config = config.get_api_config()
        host = api_config["host"]
        port = api_config["port"]
    else:
        host = "0.0.0.0"
        port = 8000

    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )
