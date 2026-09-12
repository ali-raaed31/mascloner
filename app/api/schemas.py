"""Pydantic schemas for API requests and responses."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


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


class ConfigRequest(BaseModel):
    """Request model for updating sync configuration."""

    gdrive_remote: str
    gdrive_src: str
    nc_remote: str
    nc_dest_path: str


class ScheduleRequest(BaseModel):
    """Request model for updating schedule configuration."""

    interval_min: int = Field(..., ge=1, le=1440)
    jitter_sec: int = Field(..., ge=0, le=300)


class RunResponse(BaseModel):
    """Response model for a sync run."""

    id: int
    status: str
    started_at: str
    finished_at: Optional[str]
    num_added: int
    num_updated: int
    bytes_transferred: int
    errors: int
    log_path: Optional[str]


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
