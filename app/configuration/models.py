"""Typed configuration data models.

Encodes the ownership and typing contracts defined in ADR 0001, ADR 0003, and CONTEXT.md:
- .env owns bootstrap and process boundaries
- SQLite owns Schedule, sync paths, rclone performance, and retention policy
- rclone.conf owns endpoints (gdrive, ncwebdav) and token state
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
import json
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def validate_drive_chunk_size(v: Optional[str]) -> Optional[str]:
    """Validate that Google Drive chunk size is a power of 2 >= 256k."""
    if v is None:
        return None
    stripped = v.strip()
    if not stripped:
        return None
    m = re.match(r"^(\d+)(b|k|m|g|ki|mi|gi|kb|mb|gb)?$", stripped, re.IGNORECASE)
    if not m:
        raise ValueError(
            f"Invalid drive chunk size {v!r}. Must be a power of 2 >= 256k (e.g. 16M, 32M, 64M, 128M)."
        )
    num = int(m.group(1))
    unit = (m.group(2) or "").lower()
    multiplier = 1
    if unit in ("k", "ki", "kb"):
        multiplier = 1024
    elif unit in ("m", "mi", "mb"):
        multiplier = 1024 * 1024
    elif unit in ("g", "gi", "gb"):
        multiplier = 1024 * 1024 * 1024
    bytes_val = num * multiplier
    if bytes_val < 256 * 1024 or (bytes_val & (bytes_val - 1)) != 0:
        raise ValueError(
            f"Invalid drive chunk size {v!r}. Google Drive requires chunk size to be a power of 2 >= 256k (e.g. 16M, 32M, 64M, 128M)."
        )
    return stripped


class StoreType(str, Enum):
    """The authoritative storage tier for a configuration setting."""

    ENV = "env"
    SQLITE = "sqlite"
    RCLONE_CONF = "rclone_conf"


class BootstrapSettings(BaseModel):
    """Bootstrap configuration owned by .env."""

    model_config = ConfigDict(extra="ignore", arbitrary_types_allowed=True)

    base_dir: Path
    data_dir: Path
    log_dir: Path
    run_dir: Path
    config_dir: Path
    db_path: Path
    rclone_conf_path: Path
    rclone_bin_path: Path

    api_host: str = "127.0.0.1"
    api_port: int = 8787
    ui_host: str = "127.0.0.1"
    ui_port: int = 8501

    auth_enabled: bool = False
    auth_username: Optional[str] = None
    auth_password: Optional[str] = None

    cors_origins: List[str] = Field(
        default_factory=lambda: ["http://localhost:8501", "http://127.0.0.1:8501"]
    )

    def __repr__(self) -> str:
        fields = []
        for k, v in self.model_dump().items():
            if k == "auth_password" and v:
                fields.append(f"{k}='***'")
            else:
                fields.append(f"{k}={v!r}")
        return f"BootstrapSettings({', '.join(fields)})"


class ScheduleSettings(BaseModel):
    """Schedule configuration owned by SQLite."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    interval_min: int = Field(5, ge=1, le=1440)
    jitter_sec: int = Field(20, ge=0, le=300)

    @model_validator(mode="after")
    def _validate_timing(self) -> ScheduleSettings:
        if self.jitter_sec >= self.interval_min * 60:
            raise ValueError(
                f"jitter_sec ({self.jitter_sec}s) must be less than interval ({self.interval_min * 60}s)"
            )
        return self


class RclonePerformanceSettings(BaseModel):
    """Rclone performance and concurrency settings owned by SQLite."""

    model_config = ConfigDict(extra="forbid")

    transfers: int = Field(4, ge=1, le=64)
    checkers: int = Field(8, ge=1, le=128)
    tpslimit: int = Field(10, ge=1, le=1000)
    tpslimit_burst: int = Field(1, ge=0, le=1000)
    buffer_size: Optional[str] = "32Mi"
    drive_chunk_size: Optional[str] = "64M"
    drive_upload_cutoff: Optional[str] = "128M"
    fast_list: bool = False

    @field_validator("buffer_size", "drive_upload_cutoff")
    @classmethod
    def _clean_size_strings(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        stripped = v.strip()
        if not stripped:
            return None
        size_regex = re.compile(r"^\d+(\.\d+)?(b|k|m|g|t|p|ki|mi|gi|ti|pi|kb|mb|gb|tb|pb)?$", re.IGNORECASE)
        if not size_regex.match(stripped):
            raise ValueError(f"Invalid size string {v!r}. Must be a valid byte/size specification (e.g. 32Mi, 64M, 128M).")
        return stripped

    @field_validator("drive_chunk_size")
    @classmethod
    def _validate_drive_chunk_size(cls, v: Optional[str]) -> Optional[str]:
        return validate_drive_chunk_size(v)


class SyncPathsSettings(BaseModel):
    """Selected sync folder paths owned by SQLite."""

    model_config = ConfigDict(extra="forbid")

    gdrive_src: str = ""
    nc_dest_path: str = ""

    @field_validator("gdrive_src", "nc_dest_path")
    @classmethod
    def _normalize_path(cls, v: str) -> str:
        if "\0" in v:
            raise ValueError("Null bytes not allowed in folder paths")
        stripped = v.strip()
        segments = [seg for seg in stripped.replace("\\", "/").split("/") if seg]
        if ".." in segments:
            raise ValueError("Path traversal segments (..) are not allowed")
        return "/".join(segments)


class RetentionPolicySettings(BaseModel):
    """Retention policy owned by SQLite."""

    model_config = ConfigDict(extra="forbid")

    retention_days: int = Field(60, ge=1, le=3650)


class EndpointMetadata(BaseModel):
    """Metadata describing an endpoint in rclone.conf (never contains secrets)."""

    model_config = ConfigDict(extra="ignore")

    name: str
    type: str
    is_configured: bool
    details: Dict[str, str] = Field(default_factory=dict)

    def __repr__(self) -> str:
        return f"EndpointMetadata(name={self.name!r}, type={self.type!r}, is_configured={self.is_configured!r})"


class SettingDiagnostic(BaseModel):
    """Setting diagnostic entry for inspection without secret leakage."""

    model_config = ConfigDict(extra="ignore")

    key: str
    owner: StoreType
    is_valid: bool
    is_secret: bool = False
    redacted_value: Optional[str] = None
    source_location: str
    message: Optional[str] = None


class EffectiveConfiguration(BaseModel):
    """Consolidated effective runtime configuration across all stores."""

    model_config = ConfigDict(extra="ignore")

    bootstrap: BootstrapSettings
    schedule: ScheduleSettings
    performance: RclonePerformanceSettings
    paths: SyncPathsSettings
    retention: RetentionPolicySettings
    endpoints: Dict[str, EndpointMetadata]


class GoogleDriveSourceDraft(BaseModel):
    """Candidate draft for configuring the fixed GoogleDriveSource.

    Per ADR 0004: Caller cannot specify custom remote names. Remote is strictly 'gdrive'.
    """

    model_config = ConfigDict(extra="forbid")

    token: str
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    scope: str = "drive.readonly"
    team_drive: Optional[str] = None

    @field_validator("token")
    @classmethod
    def _validate_token(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Token cannot be empty")
        try:
            parsed = json.loads(v) if isinstance(v, str) else v
            if not isinstance(parsed, dict):
                raise ValueError("Token must be a JSON object")
            if "access_token" not in parsed:
                raise ValueError("Token JSON must contain an 'access_token'")
        except (json.JSONDecodeError, TypeError) as exc:
            raise ValueError(f"Token is not valid JSON: {exc}")
        return json.dumps(parsed, separators=(",", ":"))

    @field_validator("scope")
    @classmethod
    def _validate_scope(cls, v: str) -> str:
        allowed = {"drive", "drive.readonly", "drive.file", "drive.appdata", "drive.metadata.readonly"}
        if v not in allowed:
            raise ValueError(f"Invalid Google Drive scope {v!r}. Allowed: {sorted(allowed)}")
        return v

    def __repr__(self) -> str:
        cid = self.client_id[:10] + "..." if self.client_id else None
        return f"GoogleDriveSourceDraft(scope={self.scope!r}, client_id={cid!r}, client_secret='***', token='***')"


class NextcloudDestinationDraft(BaseModel):
    """Candidate draft for configuring the fixed NextcloudDestination.

    Per ADR 0004: Caller cannot specify custom remote names. Remote is strictly 'ncwebdav'.
    """

    model_config = ConfigDict(extra="forbid")

    url: str
    user: str
    password: str
    vendor: str = "nextcloud"

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("URL cannot be empty")
        v = v.strip()
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"URL scheme must be http or https, got {parsed.scheme!r}")
        if not parsed.netloc:
            raise ValueError("URL must have a valid domain or hostname")
        if parsed.username or parsed.password:
            netloc = parsed.hostname
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            parsed = parsed._replace(netloc=netloc)
            v = urlunparse(parsed)
        return v

    @field_validator("user")
    @classmethod
    def _validate_user(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("User cannot be empty")
        return v.strip()

    @field_validator("password")
    @classmethod
    def _validate_password(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Password cannot be empty")
        return v.strip()

    @field_validator("vendor")
    @classmethod
    def _validate_vendor(cls, v: str) -> str:
        if v.lower() != "nextcloud":
            raise ValueError(f"Only 'nextcloud' vendor is supported, got {v!r}")
        return "nextcloud"

    def __repr__(self) -> str:
        return f"NextcloudDestinationDraft(url={self.url!r}, user={self.user!r}, vendor={self.vendor!r}, password='***')"
