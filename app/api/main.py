"""FastAPI application entrypoint for MasCloner API."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import config
from .db import init_db
from .routers import config as config_router
from .routers import google_drive as google_drive_router
from .routers import maintenance as maintenance_router
from .routers import nextcloud as nextcloud_router
from .scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting MasCloner API...")
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


app = FastAPI(
    title="MasCloner API",
    description="API for managing Google Drive to Nextcloud sync operations",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8501", "http://127.0.0.1:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(config_router.router)
app.include_router(google_drive_router.router)
app.include_router(nextcloud_router.router)
app.include_router(maintenance_router.router)


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
