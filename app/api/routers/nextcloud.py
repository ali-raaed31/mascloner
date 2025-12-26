"""Nextcloud-related endpoints."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from ..dependencies import get_runner
from ..rclone_runner import RcloneRunner
from ..schemas import ApiResponse, WebDAVTestRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/test/nextcloud", tags=["nextcloud"])


@router.post("/webdav", response_model=ApiResponse)
async def test_nextcloud_webdav(
    request: WebDAVTestRequest,
    runner: RcloneRunner = Depends(get_runner),
):
    """Test Nextcloud WebDAV connection and create rclone remote."""
    try:
        test_result = await runner.test_webdav_connection_async(
            url=request.url,
            user=request.user,
            password=request.pass_,
            remote_name=request.remote_name,
        )

        if test_result["success"]:
            return ApiResponse(
                success=True,
                message="Nextcloud WebDAV connection successful and remote created",
                data={"remote_name": request.remote_name},
            )

        return ApiResponse(
            success=False,
            message=f"WebDAV connection failed: {test_result.get('error', 'Unknown error')}",
        )

    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("WebDAV test failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"WebDAV test failed: {exc}",
        )
