"""Remote folder browsing and size estimation endpoints."""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, Depends

from ..dependencies import get_runner
from ..rclone_runner import RcloneRunner

logger = logging.getLogger(__name__)

router = APIRouter(tags=["browse"])


@router.get("/browse/folders/{remote_name}", response_model=Dict[str, Any])
async def browse_remote_folders(
    remote_name: str,
    path: str = "",
    runner: RcloneRunner = Depends(get_runner),
):
    """Browse folders in a remote."""
    try:
        logger.info("API: browse folders request remote='%s' path='%s'", remote_name, path)

        folders = await runner.list_folders_async(remote_name, path)

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
async def estimate_sync_size(
    source: str,
    dest: str,
    runner: RcloneRunner = Depends(get_runner),
):
    """Estimate the size of a sync operation."""
    try:
        size_info = await runner.estimate_sync_size_async(source, dest)
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

