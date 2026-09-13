"""Pydantic schemas for API requests and responses."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from app.api.models import SyncStatus

import re
from pydantic import BaseModel, Field, field_validator, model_validator


class StatusResponse(BaseModel):
    """Response model for system status."""

    last_run: Optional[Dict[str, Any]]
    last_sync: Optional[str]
    next_run: Optional[str]
    scheduler_running: bool
    database_ok: bool
    total_runs: int
    config_valid: bool
    remotes_configured: Dict[str, bool]


SIZE_REGEX = re.compile(r"^\d+(\.\d+)?(b|k|m|g|t|p|ki|mi|gi|ti|pi|kb|mb|gb|tb|pb)?$", re.IGNORECASE)

class ConfigRequest(BaseModel):
    """Request model for updating sync configuration (fixed endpoints per ADR 0004)."""

    gdrive_remote: Optional[str] = "gdrive"
    gdrive_src: str
    nc_remote: Optional[str] = "ncwebdav"
    nc_dest_path: str

    @field_validator("gdrive_remote")
    @classmethod
    def _validate_gdrive_remote(cls, v: Optional[str]) -> str:
        if v and v != "gdrive":
            raise ValueError(
                f"Arbitrary remote names are not allowed. Google Drive remote must be 'gdrive', got '{v}'"
            )
        return "gdrive"

    @field_validator("nc_remote")
    @classmethod
    def _validate_nc_remote(cls, v: Optional[str]) -> str:
        if v and v != "ncwebdav":
            raise ValueError(
                f"Arbitrary remote names are not allowed. Nextcloud remote must be 'ncwebdav', got '{v}'"
            )
        return "ncwebdav" 

    @field_validator("gdrive_src", "nc_dest_path")
    @classmethod
    def _validate_paths(cls, v: str) -> str:
        if "\0" in v:
            raise ValueError("Null bytes not allowed in folder paths")
        stripped = v.strip()
        segments = [seg for seg in stripped.replace("\\", "/").split("/") if seg]
        if ".." in segments:
            raise ValueError("Path traversal segments (..) are not allowed")
        return "/".join(segments)


class ScheduleRequest(BaseModel):
    """Request model for updating schedule configuration."""

    interval_min: int = Field(..., ge=1, le=1440)
    jitter_sec: int = Field(..., ge=0, le=300)
    enabled: Optional[bool] = None

    @model_validator(mode="after")
    def _validate_timing(self) -> ScheduleRequest:
        if self.jitter_sec >= self.interval_min * 60:
            raise ValueError(
                f"jitter_sec ({self.jitter_sec}s) must be less than interval ({self.interval_min * 60}s)"
            )
        return self


class ScheduleResponse(BaseModel):
    """Response model for schedule configuration and runtime status."""

    enabled: bool
    interval_min: int
    jitter_sec: int
    interval: str
    next_run_time: Optional[str] = None


class RunResponse(BaseModel):
    """Response model for a sync run."""

    id: int
    status: SyncStatus
    started_at: str
    finished_at: Optional[str] = None
    num_added: int
    num_updated: int
    bytes_transferred: int
    errors: int
    log_path: Optional[str] = None
    message: Optional[str] = None


class FileEventResponse(BaseModel):
    """Response model for a file event."""

    id: int
    timestamp: str
    action: str
    file_path: str
    file_size: int
    file_hash: Optional[str]
    message: Optional[str]


class ApiResponse(BaseModel):
    """Generic API response model."""

    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


class RcloneConfigRequest(BaseModel):
    """Request model for updating rclone performance settings."""

    transfers: int = Field(..., ge=1, le=64, description="Number of parallel file transfers")
    checkers: int = Field(..., ge=1, le=128, description="Number of parallel checkers")
    tpslimit: int = Field(..., ge=1, le=1000, description="Transaction limit per second")
    tpslimit_burst: int = Field(..., ge=0, le=1000, description="Transaction limit burst")
    buffer_size: Optional[str] = Field(None, description="Buffer size per transfer (e.g. 32Mi)")
    drive_chunk_size: Optional[str] = Field(None, description="Google Drive chunk size (e.g. 64M)")
    drive_upload_cutoff: Optional[str] = Field(None, description="Threshold for chunked uploads (e.g. 128M)")
    fast_list: bool = Field(False, description="Toggle rclone --fast-list optimisation")

    @field_validator("buffer_size", "drive_upload_cutoff")
    @classmethod
    def _validate_size_strings(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            return None
        if not SIZE_REGEX.match(stripped):
            raise ValueError(f"Invalid size string {v!r}. Must be a valid byte/size specification (e.g. 32Mi, 64M, 128M).")
        return stripped

    @field_validator("drive_chunk_size")
    @classmethod
    def _validate_drive_chunk_size(cls, v: Optional[str]) -> Optional[str]:
        from ..configuration.models import validate_drive_chunk_size
        return validate_drive_chunk_size(v)


class GoogleDriveOAuthRequest(BaseModel):
    """Request model for Google Drive OAuth configuration."""

    token: str = Field(..., description="OAuth token from rclone authorize")
    scope: str = Field(default="drive.readonly", description="OAuth scope")
    client_id: Optional[str] = Field(None, description="Custom client ID (optional)")
    client_secret: Optional[str] = Field(None, description="Custom client secret (optional)")


class GoogleDriveStatusResponse(BaseModel):
    """Response model for Google Drive status."""

    configured: bool
    remote_name: str = "gdrive"
    scope: Optional[str] = None
    folders: Optional[List[str]] = None
    last_test: Optional[str] = None


class WebDAVTestRequest(BaseModel):
    """Request model for WebDAV connection testing."""

    url: str
    user: str
    pass_: str = Field(alias="pass")
    remote_name: str


class GoogleDriveOAuthConfigRequest(BaseModel):
    """Request model for Google Drive OAuth configuration."""

    client_id: str = Field(..., description="Google OAuth Client ID")
    client_secret: str = Field(..., description="Google OAuth Client Secret")
