"""FastAPI application entrypoint for MasCloner API."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

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
from .routers import tree as tree_router
from .scheduler import start_scheduler, stop_scheduler

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
        init_db()
        logger.info("Database initialized")

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
        stop_scheduler()
        logger.info("Scheduler stopped")
    except Exception as exc:  # pragma: no cover
        logger.error("Shutdown error: %s", exc)


# Build CORS origins from environment or use defaults
def get_cors_origins() -> list[str]:
    """Get CORS allowed origins from environment or defaults."""
    origins_env = os.getenv("MASCLONER_CORS_ORIGINS")
    if origins_env:
        return [origin.strip() for origin in origins_env.split(",") if origin.strip()]
    return ["http://localhost:8501", "http://127.0.0.1:8501"]


app = FastAPI(
    title="MasCloner API",
    description="API for managing Google Drive to Nextcloud sync operations",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register custom exception handlers for consistent error responses
register_exception_handlers(app)


# Include routers with authentication dependency when enabled
# Health endpoint is always public
@app.get("/health")
async def health_check():
    """Public health check endpoint (no auth required)."""
    return {"status": "healthy", "service": "mascloner-api"}


# Apply auth dependency to all routers when auth is enabled
router_dependencies = []
if is_auth_enabled():
    router_dependencies.append(Depends(require_auth))

app.include_router(config_router.router, dependencies=router_dependencies)
app.include_router(runs_router.router, dependencies=router_dependencies)
app.include_router(runs_router.events_router, dependencies=router_dependencies)
app.include_router(schedule_router.router, dependencies=router_dependencies)
app.include_router(tree_router.router, dependencies=router_dependencies)
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
        host = "127.0.0.1"
        port = 8787

    uvicorn.run(
        "app.api.main:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )
