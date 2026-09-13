"""Typed Configuration module for MasCloner.

Encodes the architecture and ownership contracts defined in ADR 0001, ADR 0003, and ADR 0005.
"""

from .exceptions import (
    ConfigurationError,
    ConfigurationLeaseError,
    ConfigurationStoreError,
    ConfigurationValidationError,
    MissingSettingError,
)
from .lease import ConfigurationLease
from .manager import Configuration
from .models import (
    BootstrapSettings,
    GoogleDriveSourceDraft,
    NextcloudDestinationDraft,
    EffectiveConfiguration,
    EndpointMetadata,
    RclonePerformanceSettings,
    RetentionPolicySettings,
    ScheduleSettings,
    SettingDiagnostic,
    StoreType,
    SyncPathsSettings,
)

__all__ = [
    "Configuration",
    "ConfigurationLease",
    "ConfigurationError",
    "ConfigurationValidationError",
    "ConfigurationStoreError",
    "ConfigurationLeaseError",
    "MissingSettingError",
    "StoreType",
    "BootstrapSettings",
    "GoogleDriveSourceDraft",
    "NextcloudDestinationDraft",
    "ScheduleSettings",
    "RclonePerformanceSettings",
    "SyncPathsSettings",
    "RetentionPolicySettings",
    "EndpointMetadata",
    "SettingDiagnostic",
    "EffectiveConfiguration",
]
