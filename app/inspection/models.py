"""Domain models and results for side-effect-free EndpointInspector."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class EndpointConcept(str, Enum):
    """The two fixed storage endpoints supported by the system."""

    SOURCE = "gdrive"
    DESTINATION = "ncwebdav"


class FolderEntry(BaseModel):
    """A directory entry discovered during endpoint browsing."""

    name: str
    path: str
    is_dir: bool = True


class BrowseResult(BaseModel):
    """Result of directory browsing on an endpoint."""

    success: bool
    endpoint: str
    path: str = ""
    folders: List[str] = Field(default_factory=list)
    entries: List[FolderEntry] = Field(default_factory=list)
    truncated: bool = False
    total_count: int = 0
    error: Optional[str] = None
    duration_ms: Optional[float] = None


class ConnectionTestResult(BaseModel):
    """Result of a connection test against an endpoint or draft."""

    success: bool
    endpoint: str
    message: str
    duration_ms: Optional[float] = None
    error_category: Optional[str] = None


class EndpointStatusResult(BaseModel):
    """Status summary for a configured endpoint."""

    configured: bool
    endpoint: str
    remote_name: str
    scope: Optional[str] = None
    user: Optional[str] = None
    url: Optional[str] = None
    folders: Optional[List[str]] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class SizeEstimationResult(BaseModel):
    """Result of estimating data volume and file count."""

    success: bool
    size_mb: float = 0.0
    file_count: int = 0
    folder_count: int = 0
    error: Optional[str] = None
    duration_ms: Optional[float] = None
