"""Pydantic data models for the MasCloner API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ConfigRequest(BaseModel):
    """Request model for configuration updates."""

    gdrive_remote: str = Field(..., description="Google Drive remote name")
    gdrive_src: str = Field(..., description="Google Drive source path")
    gdrive_shared_with_me: Optional[bool] = Field(
        default=False, 
        description="Restrict to 'Shared with me' folder only (default: False = access both My Drive and Shared)"
    )
    nc_remote: str = Field(..., description="Nextcloud remote name")
    nc_dest_path: str = Field(..., description="Nextcloud destination path")


class ScheduleRequest(BaseModel):
    """Request model for schedule updates."""

    interval_min: int = Field(ge=1, le=1440, description="Sync interval in minutes")
    jitter_sec: int = Field(ge=0, le=3600, default=20, description="Jitter in seconds")


class RunResponse(BaseModel):
    """Response model for run information."""

    id: int
    status: str
    started_at: str
    finished_at: Optional[str] = None
    num_added: int = 0
    num_updated: int = 0
    bytes_transferred: int = 0
    errors: int = 0
    log_path: Optional[str] = None


class FileEventResponse(BaseModel):
    """Response model for file events."""

    id: int
    timestamp: str
    action: str
    file_path: str
    file_size: int
    file_hash: Optional[str] = None
    message: Optional[str] = None


class StatusResponse(BaseModel):
    """Response model for system status."""

    last_run: Optional[Dict[str, Any]] = None
    last_sync: Optional[str] = None
    next_run: Optional[str] = None
    scheduler_running: bool
    database_ok: bool
    total_runs: int = 0
    config_valid: bool = False
    remotes_configured: Dict[str, bool] = {}


class ApiResponse(BaseModel):
    """Generic API response model."""

    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


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


class TreeNodeResponse(BaseModel):
    """Response model for a single tree node within the file tree."""

    path: str
    name: str
    type: str
    size: Optional[int] = None
    children: Optional[List["TreeNodeResponse"]] = None


class TreeResponse(BaseModel):
    """Response model for the entire file tree."""

    root: TreeNodeResponse


class WebDAVTestRequest(BaseModel):
    """Request model for WebDAV connection testing."""

    url: str
    user: str
    pass_: str = Field(alias="pass")
    remote_name: str


try:  # Pydantic v2
    TreeNodeResponse.model_rebuild()
except AttributeError:  # Pydantic v1 fallback
    TreeNodeResponse.update_forward_refs()
