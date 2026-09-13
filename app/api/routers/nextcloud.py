"""Nextcloud-related endpoints."""

from __future__ import annotations

import configparser
import logging
import os
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, status

from ...inspection import EndpointInspector
from ...configuration import (
    Configuration,
    ConfigurationLeaseError,
    ConfigurationStoreError,
    ConfigurationValidationError,
    NextcloudDestinationDraft,
)
from ..db import get_db_session
from ..schemas import ApiResponse, WebDAVTestRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/test/nextcloud", tags=["nextcloud"])

RCLONE_REMOTE_NAME = "ncwebdav"


@router.post("/webdav", response_model=ApiResponse)
async def test_nextcloud_webdav(request: WebDAVTestRequest):
    """Test Nextcloud WebDAV connection and promote configuration safely under lease."""
    if request.remote_name and request.remote_name != RCLONE_REMOTE_NAME:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Caller-specified remote name {request.remote_name!r} is not supported. "
            f"Only the fixed '{RCLONE_REMOTE_NAME}' remote is permitted for Nextcloud destination.",
        )

    try:
        draft = NextcloudDestinationDraft(
            url=request.url,
            user=request.user,
            password=request.pass_,
            vendor="nextcloud",
        )
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid Nextcloud configuration: {exc}",
        ) from exc

    cfg = Configuration(session_factory=get_db_session)
    try:
        cfg.promote_nextcloud_destination(draft)
        return ApiResponse(
            success=True,
            message="Nextcloud WebDAV connection successful and remote created",
            data={"remote_name": RCLONE_REMOTE_NAME},
        )
    except ConfigurationLeaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot configure Nextcloud destination while another operation holds the lease: {exc}",
        ) from exc
    except ConfigurationValidationError as exc:
        return ApiResponse(
            success=False,
            message=f"WebDAV connection failed: {exc}",
        )
    except ConfigurationStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to persist Nextcloud configuration: {exc}",
        ) from exc
    except Exception as exc:
        logger.error("WebDAV test failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"WebDAV test failed: {exc}",
        ) from exc


@router.post("", response_model=ApiResponse)
async def test_existing_nextcloud():
    """Test existing Nextcloud connection via EndpointInspector."""
    try:
        inspector = EndpointInspector()
        test_res = await inspector.test_connection("ncwebdav")
        return ApiResponse(
            success=test_res.success,
            message=test_res.message,
            data={"remote_name": RCLONE_REMOTE_NAME},
        )
    except Exception as exc:
        logger.error("Nextcloud test error: %s", exc)
        return ApiResponse(success=False, message=f"Test error: {exc}")


@router.get("/status")
async def get_nextcloud_status():
    """Get Nextcloud destination configuration status without exposing secrets."""
    try:
        cfg = Configuration(session_factory=get_db_session)
        return cfg.get_nextcloud_metadata()
    except Exception as exc:
        logger.error("Failed to get Nextcloud status: %s", exc)
        return {"configured": False, "remote_name": RCLONE_REMOTE_NAME, "url": None, "user": None}


@router.delete("/webdav", response_model=ApiResponse)
@router.delete("", response_model=ApiResponse)
async def remove_nextcloud_config():
    """Remove Nextcloud configuration safely under lease."""
    try:
        cfg = Configuration(session_factory=get_db_session)
        with cfg.acquire_lease(holder="RemoveNextcloudConfig", timeout=2.0):
            rclone_path = cfg._rclone_adapter.conf_path
            if not rclone_path.exists():
                return ApiResponse(success=True, message="Nextcloud configuration removed successfully")

            parser = configparser.RawConfigParser(interpolation=None)
            parser.optionxform = str
            parser.read(rclone_path, encoding="utf-8")

            if parser.has_section(RCLONE_REMOTE_NAME):
                parser.remove_section(RCLONE_REMOTE_NAME)
                tmp_path = None
                try:
                    with tempfile.NamedTemporaryFile(
                        "w",
                        dir=str(rclone_path.parent),
                        delete=False,
                        encoding="utf-8",
                    ) as tf:
                        parser.write(tf)
                        tf.flush()
                        os.fsync(tf.fileno())
                        tmp_path = Path(tf.name)
                    os.chmod(tmp_path, 0o600)
                    os.replace(tmp_path, rclone_path)
                    os.chmod(rclone_path, 0o600)
                finally:
                    if tmp_path and tmp_path.exists():
                        try:
                            tmp_path.unlink()
                        except Exception:
                            pass
                return ApiResponse(success=True, message="Nextcloud configuration removed successfully")

            return ApiResponse(success=True, message="Nextcloud configuration not found")
    except ConfigurationLeaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot remove configuration while another operation holds the lease: {exc}",
        ) from exc
    except Exception as exc:
        logger.error("Failed to remove Nextcloud configuration: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove Nextcloud configuration: {exc}",
        )
