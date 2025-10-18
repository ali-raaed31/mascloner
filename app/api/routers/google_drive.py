"""Google Drive endpoints."""

from __future__ import annotations

import json
import logging
import subprocess

from fastapi import APIRouter, HTTPException, status
from pathlib import Path
import os
try:
    from dotenv import load_dotenv
except Exception:  # optional dependency in some test envs
    def load_dotenv(*args, **kwargs):  # type: ignore
        return False

from ..config import config
from ..schemas import (
    ApiResponse,
    GoogleDriveOAuthRequest,
    GoogleDriveOAuthConfigRequest,
    GoogleDriveStatusResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oauth/google-drive", tags=["google-drive"])


@router.post("", response_model=ApiResponse)
async def configure_google_drive_oauth(request: GoogleDriveOAuthRequest):
    """Configure Google Drive using OAuth token from rclone authorize."""
    try:
        try:
            token_data = json.loads(request.token)
            if "access_token" not in token_data:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid token format: missing access_token",
                )
        except json.JSONDecodeError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid token format: not valid JSON",
            )

        base_config = config.get_base_config()
        rclone_config = str(base_config["base_dir"] / base_config["rclone_conf"])

        try:
            subprocess.run(
                ["rclone", "--config", rclone_config, "config", "delete", "gdrive"],
                capture_output=True,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            pass

        cmd = [
            "rclone",
            "--config",
            rclone_config,
            "config",
            "create",
            "gdrive",
            "drive",
            f"scope={request.scope}",
            f"token={request.token}",
        ]

        # Get custom OAuth credentials from environment (prioritized over request)
        oauth_config = config.get_gdrive_oauth_config()
        client_id = oauth_config.get("client_id") or request.client_id
        client_secret = oauth_config.get("client_secret") or request.client_secret

        if client_id and client_secret:
            cmd.extend([f"client_id={client_id}", f"client_secret={client_secret}"])
            logger.info("Using custom OAuth credentials for Google Drive configuration")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)

        if result.returncode == 0:
            logger.info("Google Drive configured successfully via OAuth.")
            # Ensure rclone.conf has strict permissions
            try:
                Path(rclone_config).parent.mkdir(parents=True, exist_ok=True)
                os.chmod(rclone_config, 0o600)
            except Exception as perm_exc:
                logger.warning("Failed to set permissions on rclone config: %s", perm_exc)

            # Warn if token lacks refresh_token (might stop working soon)
            warnings = []
            if "refresh_token" not in token_data:
                warn_msg = (
                    "Token has no refresh_token; access may expire soon. "
                    "Consider re-authorizing via rclone config with offline access or publish your OAuth app."
                )
                logger.warning(warn_msg)
                warnings.append(warn_msg)

            return ApiResponse(
                success=True,
                message="Google Drive configured successfully",
                data={"warnings": warnings} if warnings else None,
            )

        logger.error("Google Drive configuration failed: %s", result.stderr)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=result.stderr or "Failed to configure Google Drive",
        )

    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Google Drive OAuth configuration error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to configure Google Drive: {exc}",
        )


@router.get("/oauth-config")
async def get_google_drive_oauth_config():
    """Get Google Drive OAuth configuration status."""
    try:
        oauth_config = config.get_gdrive_oauth_config()
        return {
            "client_id": oauth_config.get("client_id"),
            "client_secret": "***" if oauth_config.get("client_secret") else None,
            "has_custom_oauth": bool(oauth_config.get("client_id") and oauth_config.get("client_secret"))
        }
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
        "received_client_secret": "*" * len(request.client_secret)
    }


@router.post("/oauth-config")
async def save_google_drive_oauth_config(request: GoogleDriveOAuthConfigRequest):
    """Save Google Drive OAuth configuration."""
    try:
        client_id = request.client_id.strip()
        client_secret = request.client_secret.strip()
        
        logger.info(f"Received OAuth config request: client_id={client_id[:10]}..., client_secret={'*' * len(client_secret)}")
        
        if not client_id or not client_secret:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Both client_id and client_secret are required"
            )
        
        # Encrypt the credentials
        encrypted_client_id = config.obscure_password(client_id)
        encrypted_client_secret = config.obscure_password(client_secret)
        
        # Update environment variables in .env file
        base_config = config.get_base_config()
        env_file_path = base_config["base_dir"] / ".env"
        
        logger.info(f"Updating .env file at: {env_file_path}")
        
        # Read current .env file
        env_content = ""
        if env_file_path.exists():
            try:
                with open(env_file_path, 'r') as f:
                    env_content = f.read()
            except Exception as e:
                logger.error(f"Failed to read .env file: {e}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to read .env file: {e}"
                )
        
        # Update or add OAuth variables
        lines = env_content.split('\n')
        updated_lines = []
        oauth_vars_added = {"client_id": False, "client_secret": False}
        
        for line in lines:
            if line.startswith("GDRIVE_OAUTH_CLIENT_ID="):
                updated_lines.append(f'GDRIVE_OAUTH_CLIENT_ID="{encrypted_client_id}"')
                oauth_vars_added["client_id"] = True
            elif line.startswith("GDRIVE_OAUTH_CLIENT_SECRET="):
                updated_lines.append(f'GDRIVE_OAUTH_CLIENT_SECRET="{encrypted_client_secret}"')
                oauth_vars_added["client_secret"] = True
            else:
                updated_lines.append(line)
        
        # Add missing variables
        if not oauth_vars_added["client_id"]:
            updated_lines.append(f'GDRIVE_OAUTH_CLIENT_ID="{encrypted_client_id}"')
        if not oauth_vars_added["client_secret"]:
            updated_lines.append(f'GDRIVE_OAUTH_CLIENT_SECRET="{encrypted_client_secret}"')
        
        # Write updated .env file
        try:
            with open(env_file_path, 'w') as f:
                f.write('\n'.join(updated_lines))
            
            # Set proper permissions
            import os
            os.chmod(env_file_path, 0o600)
            logger.info("Successfully updated .env file with OAuth credentials")
            # Hot-reload .env so the running process sees the new values
            try:
                load_dotenv(str(env_file_path), override=True)
                logger.info("Reloaded .env into process environment")
            except Exception as le:
                logger.warning("Failed to reload .env: %s", le)
        except Exception as e:
            logger.error(f"Failed to write .env file: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to write .env file: {e}"
            )
        
        logger.info("Google Drive OAuth credentials saved successfully")
        return {"success": True, "message": "OAuth credentials saved successfully"}
        
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to save OAuth config: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save OAuth credentials: {exc}"
        )


@router.get("/status", response_model=GoogleDriveStatusResponse)
async def get_google_drive_status():
    """Get Google Drive configuration status."""
    try:
        base_config = config.get_base_config()
        rclone_config = str(base_config["base_dir"] / base_config["rclone_conf"])

        result = subprocess.run(
            ["rclone", "--config", rclone_config, "listremotes"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        configured = result.returncode == 0 and "gdrive:" in result.stdout
        response_data = {"configured": configured, "remote_name": "gdrive"}

        if configured:
            try:
                # Read actual scope from rclone config dump if available
                try:
                    dump = subprocess.run(
                        ["rclone", "--config", rclone_config, "config", "dump"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if dump.returncode == 0:
                        cfg = json.loads(dump.stdout)
                        gdrive_cfg = cfg.get("gdrive") or cfg.get("gdrive:")
                        if isinstance(gdrive_cfg, dict):
                            response_data["scope"] = gdrive_cfg.get("scope")
                except Exception as dump_exc:
                    logger.debug("Failed to read scope from config dump: %s", dump_exc)

                folder_result = subprocess.run(
                    [
                        "rclone",
                        "--config",
                        rclone_config,
                        "--transfers=2",
                        "--checkers=2",
                        "lsd",
                        "gdrive:",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )

                if folder_result.returncode == 0:
                    folders = []
                    for line in folder_result.stdout.strip().split("\n"):
                        if line.strip():
                            parts = line.strip().split()
                            if len(parts) >= 5:
                                folder_name = " ".join(parts[4:])
                                folders.append(folder_name)

                    response_data["folders"] = folders[:10]
            except subprocess.TimeoutExpired:
                logger.warning("Google Drive folder listing timeout")

        return GoogleDriveStatusResponse(**response_data)

    except Exception as exc:  # pragma: no cover - defensive logging
        logger.error("Google Drive status check error: %s", exc)
        return GoogleDriveStatusResponse(configured=False)


@router.post("/test", response_model=ApiResponse)
async def test_google_drive_connection():
    """Test Google Drive connection."""
    try:
        base_config = config.get_base_config()
        rclone_config = str(base_config["base_dir"] / base_config["rclone_conf"])

        # Build rclone command with consistent settings
        cmd = ["rclone", "--config", rclone_config, "--transfers=4", "--checkers=8", "lsd", "gdrive:"]
        
        # Add --fast-list if enabled
        rclone_config_obj = config.get_rclone_config()
        if rclone_config_obj.get("fast_list"):
            cmd.append("--fast-list")
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            folders = []
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    parts = line.strip().split()
                    if len(parts) >= 5:
                        folder_name = " ".join(parts[4:])
                        folders.append(folder_name)

            return ApiResponse(
                success=True,
                message="Google Drive connection successful",
                data={"folders": folders[:10]},
            )

        return ApiResponse(
            success=False,
            message=f"Connection failed: {result.stderr or 'Unknown error'}",
        )

    except subprocess.TimeoutExpired:
        return ApiResponse(success=False, message="Connection test timeout")
    except Exception as exc:  # pragma: no cover
        logger.error("Google Drive connection test error: %s", exc)
        return ApiResponse(success=False, message=f"Test error: {exc}")


@router.delete("", response_model=ApiResponse)
async def remove_google_drive_config():
    """Remove Google Drive configuration."""
    try:
        base_config = config.get_base_config()
        rclone_config = str(base_config["base_dir"] / base_config["rclone_conf"])

        result = subprocess.run(
            ["rclone", "--config", rclone_config, "config", "delete", "gdrive"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            return ApiResponse(success=True, message="Google Drive configuration removed successfully")

        return ApiResponse(
            success=False,
            message=f"Failed to remove configuration: {result.stderr or 'Unknown error'}",
        )

    except Exception as exc:  # pragma: no cover
        logger.error("Google Drive config removal error: %s", exc)
        return ApiResponse(success=False, message=f"Removal error: {exc}")
