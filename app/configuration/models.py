"""Typed configuration data models.

Encodes the ownership and typing contracts defined in ADR 0001, ADR 0003, and CONTEXT.md:
- .env owns bootstrap and process boundaries
- SQLite owns Schedule, sync paths, rclone performance, and retention policy
- rclone.conf owns endpoints (gdrive, ncwebdav) and token state
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


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

    @field_validator("buffer_size", "drive_chunk_size", "drive_upload_cutoff")
    @classmethod
    def _clean_size_strings(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        stripped = v.strip()
        return stripped if stripped else None


class SyncPathsSettings(BaseModel):
    """Selected sync folder paths owned by SQLite."""

    model_config = ConfigDict(extra="forbid")

    gdrive_src: str = ""
    nc_dest_path: str = ""

    @field_validator("gdrive_src", "nc_dest_path")
    @classmethod
    def _normalize_path(cls, v: str) -> str:
        stripped = v.strip()
        # Normalize leading and trailing slashes for consistency across cloud providers
        return stripped.strip("/")


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
