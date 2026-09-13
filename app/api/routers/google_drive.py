"""Google Drive endpoints."""

from __future__ import annotations

import asyncio
import configparser
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, status

from ..config import config
from ...configuration import (
    Configuration,
    ConfigurationLeaseError,
    ConfigurationStoreError,
    ConfigurationValidationError,
    GoogleDriveSourceDraft,
)
from ..db import get_db_session
from ..schemas import (
    ApiResponse,
    GoogleDriveOAuthConfigRequest,
    GoogleDriveOAuthRequest,
    GoogleDriveStatusResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oauth/google-drive", tags=["google-drive"])

RCLONE_REMOTE_NAME = "gdrive"


@router.post("", response_model=ApiResponse)
async def configure_google_drive_oauth(request: GoogleDriveOAuthRequest):
    """Configure Google Drive using OAuth token from rclone authorize via safe Configuration flow."""
    try:
        cfg = Configuration(session_factory=get_db_session)
        oauth_creds = cfg.get_google_drive_oauth_credentials()
        client_id = request.client_id or oauth_creds.get("client_id")
        client_secret = request.client_secret

        try:
            draft = GoogleDriveSourceDraft(
                token=request.token,
                scope=request.scope,
                client_id=client_id,
                client_secret=client_secret,
            )
            cfg.promote_google_drive_source(draft)
        except ConfigurationLeaseError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Cannot configure Google Drive while another operation holds the lease: {exc}",
            ) from exc
        except (ConfigurationValidationError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid Google Drive configuration: {exc}",
            ) from exc
        except ConfigurationStoreError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to save Google Drive configuration: {exc}",
            ) from exc

        warnings = []
        try:
            parsed_tok = json.loads(request.token)
            if "refresh_token" not in parsed_tok:
                warnings.append("Token has no refresh_token; access may expire soon.")
        except Exception:
            pass

        return ApiResponse(
            success=True,
            message="Google Drive configured successfully",
            data={"warnings": warnings} if warnings else None,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Google Drive OAuth configuration error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to configure Google Drive: {exc}",
        )


@router.get("/oauth-config")
async def get_google_drive_oauth_config():
    """Get Google Drive OAuth configuration status without exposing secrets."""
    try:
        cfg = Configuration(session_factory=get_db_session)
        return cfg.get_google_drive_oauth_credentials()
    except Exception as exc:
        logger.error("Failed to get OAuth config: %s", exc)
        return {"client_id": None, "client_secret": None, "has_custom_oauth": False}


@router.post("/oauth-config/test")
async def test_oauth_config_endpoint(request: GoogleDriveOAuthConfigRequest):
    """Test endpoint for OAuth configuration."""
    return {
        "success": True,
        "message": "OAuth config endpoint is working",
        "received_client_id": request.client_id[:10] + "...",
        "received_client_secret": "*" * len(request.client_secret),
    }


@router.post("/oauth-config")
async def save_google_drive_oauth_config(request: GoogleDriveOAuthConfigRequest):
    """Save Google Drive OAuth configuration directly to managed rclone configuration."""
    client_id = request.client_id.strip()
    client_secret = request.client_secret.strip()

    if not client_id or not client_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Both client_id and client_secret are required",
        )

    try:
        cfg = Configuration(session_factory=get_db_session)
        cfg.save_google_drive_oauth_credentials(client_id, client_secret)
        return {"success": True, "message": "OAuth credentials saved successfully"}
    except ConfigurationLeaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot save OAuth credentials while another operation holds the lease: {exc}",
        ) from exc
    except ConfigurationValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error("Failed to save OAuth config: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save OAuth credentials: {exc}",
        )


@router.get("/status", response_model=GoogleDriveStatusResponse)
async def get_google_drive_status():
    """Get Google Drive configuration status."""
    try:
        cfg = Configuration(session_factory=get_db_session)
        meta = cfg.get_endpoint_metadata("gdrive")
        if not meta or meta.details.get("type") != "drive":
            return GoogleDriveStatusResponse(configured=False)

        scope = meta.details.get("scope")
        folders = None

        base_config = config.get_base_config()
        rclone_config = str(base_config["base_dir"] / base_config["rclone_conf"])
        try:
            folder_process = await asyncio.create_subprocess_exec(
                "rclone",
                "--config",
                rclone_config,
                "--transfers=2",
                "--checkers=2",
                "lsd",
                "gdrive:",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            folder_stdout, _ = await asyncio.wait_for(folder_process.communicate(), timeout=5)
            if folder_process.returncode == 0:
                folders = []
                for line in folder_stdout.decode().strip().split("\n"):
                    if line.strip():
                        parts = line.strip().split()
                        if len(parts) >= 5:
                            folders.append(" ".join(parts[4:]))
                folders = folders[:10]
        except Exception as inner_exc:
            logger.debug("Error getting folder list: %s", inner_exc)

        return GoogleDriveStatusResponse(
            configured=True,
            remote_name="gdrive",
            scope=scope,
            folders=folders,
        )
    except Exception as exc:
        logger.error("Google Drive status check error: %s", exc)
        return GoogleDriveStatusResponse(configured=False)


@router.post("/test", response_model=ApiResponse)
async def test_google_drive_connection():
    """Test Google Drive connection."""
    try:
        base_config = config.get_base_config()
        rclone_config = str(base_config["base_dir"] / base_config["rclone_conf"])

        cmd = [
            "rclone",
            "--config",
            rclone_config,
            "--transfers=4",
            "--checkers=8",
            "lsd",
            "gdrive:",
        ]

        rclone_config_obj = config.get_rclone_config()
        if rclone_config_obj.get("fast_list"):
            cmd.append("--fast-list")

        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return ApiResponse(success=False, message="Connection test timeout")

        if process.returncode == 0:
            folders = []
            for line in stdout.decode().strip().split("\n"):
                if line.strip():
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        folders.append(" ".join(parts[4:]))

            return ApiResponse(
                success=True,
                message="Google Drive connection successful",
                data={"folders": folders[:10]},
            )

        return ApiResponse(
            success=False,
            message=f"Connection failed: {stderr.decode() or 'Unknown error'}",
        )
    except Exception as exc:
        logger.error("Google Drive connection test error: %s", exc)
        return ApiResponse(success=False, message=f"Test error: {exc}")


@router.delete("", response_model=ApiResponse)
async def remove_google_drive_config():
    """Remove Google Drive configuration safely under lease."""
    try:
        cfg = Configuration(session_factory=get_db_session)
        with cfg.acquire_lease(holder="RemoveGoogleDriveConfig", timeout=2.0):
            rclone_path = cfg._rclone_adapter.conf_path
            if not rclone_path.exists():
                return ApiResponse(success=True, message="Google Drive configuration removed successfully")

            parser = configparser.RawConfigParser(interpolation=None)
            parser.optionxform = str
            parser.read(rclone_path, encoding="utf-8")

            if parser.has_section("gdrive"):
                parser.remove_section("gdrive")
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
                return ApiResponse(success=True, message="Google Drive configuration removed successfully")

            return ApiResponse(success=True, message="Google Drive configuration not found")
    except ConfigurationLeaseError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot remove configuration while another operation holds the lease: {exc}",
        ) from exc
    except Exception as exc:
        logger.error("Failed to remove Google Drive configuration: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to remove Google Drive configuration: {exc}",
        )
