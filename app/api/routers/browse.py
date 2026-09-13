"""Remote folder browsing and size estimation endpoints using EndpointInspector."""

from __future__ import annotations

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, status

from ...inspection import EndpointInspector, UnsupportedEndpointError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["browse"])


@router.get("/browse/folders/{remote_name}", response_model=Dict[str, Any])
async def browse_remote_folders(
    remote_name: str,
    path: str = "",
):
    """Browse folders in a remote endpoint safely without side effects."""
    inspector = EndpointInspector()
    try:
        logger.info("API: browse folders request remote='%s' path='%s'", remote_name, path)
        res = await inspector.browse_folders(remote_name, path=path)

        if not res.success:
            return {
                "status": "error",
                "success": False,
                "error": res.error or "Unknown browsing error",
                "folders": [],
            }

        logger.info(
            "API: browse folders response remote='%s' path='%s' count=%d",
            remote_name,
            path,
            len(res.folders),
        )
        return {
            "status": "success",
            "success": True,
            "folders": res.folders,
            "remote": remote_name,
            "path": path,
            "truncated": res.truncated,
            "total_count": res.total_count,
        }
    except UnsupportedEndpointError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
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
    source: str = "",
    dest: str = "",
):
    """Estimate the size of a sync operation without mutating configuration."""
    inspector = EndpointInspector()
    try:
        res = await inspector.estimate_size(source_path=source, dest_path=dest)
        if not res.success:
            return {
                "status": "error",
                "success": False,
                "error": res.error or "Unknown estimation error",
                "size_mb": 0,
                "file_count": 0,
                "folder_count": 0,
            }
        return {
            "status": "success",
            "success": True,
            "size_mb": res.size_mb,
            "file_count": res.file_count,
            "folder_count": res.folder_count,
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
