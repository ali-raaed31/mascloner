"""Deep Configuration facade module.

Implements the single typed Configuration boundary required by ADR 0001, ADR 0003, and ADR 0005.
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Type, TypeVar, Union
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from .exceptions import (
    ConfigurationError,
    ConfigurationLeaseError,
    ConfigurationStoreError,
    ConfigurationValidationError,
)
from .lease import ConfigurationLease
from .models import (
    BootstrapSettings,
    EffectiveConfiguration,
    EndpointMetadata,
    RclonePerformanceSettings,
    RetentionPolicySettings,
    ScheduleSettings,
    SettingDiagnostic,
    StoreType,
    SyncPathsSettings,
)
from .stores import EnvStoreAdapter, RcloneConfStoreAdapter, SqliteStoreAdapter

logger = logging.getLogger(__name__)

M = TypeVar("M", bound=BaseModel)


def _coerce_model(model_cls: Type[M], value: Union[M, Dict[str, Any]]) -> M:
    """Coerce a dict or model instance into the typed model, raising ConfigurationValidationError on failure."""
    try:
        if isinstance(value, model_cls):
            return value
        if isinstance(value, dict):
            return model_cls(**value)
        return model_cls.model_validate(value)
    except (ValidationError, ValueError, TypeError) as exc:
        raise ConfigurationValidationError(f"Validation error for {model_cls.__name__}: {exc}") from exc


class Configuration:
    """The deep application-facing Configuration interface.

    Hides the storage formats of .env, SQLite, and rclone.conf behind a compact,
    strongly-typed boundary.
    """

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        env_path: Optional[Path] = None,
        db_session_factory: Optional[Callable[[], Session]] = None,
        rclone_conf_path: Optional[Path] = None,
        session_factory: Optional[Callable[[], Session]] = None,
    ) -> None:
        if base_dir:
            resolved_base = Path(base_dir)
        elif "MASCLONER_BASE_DIR" in os.environ:
            resolved_base = Path(os.environ["MASCLONER_BASE_DIR"])
        else:
            resolved_base = Path("/srv/mascloner")

        if env_path:
            resolved_env = Path(env_path)
        elif "MASCLONER_ENV_FILE" in os.environ:
            p = Path(os.environ["MASCLONER_ENV_FILE"])
            resolved_env = p if p.is_absolute() else (resolved_base / p).resolve()
        else:
            resolved_env = resolved_base / ".env"

        self._env_adapter = EnvStoreAdapter(env_path=resolved_env, base_dir=resolved_base)
        self._bootstrap = self._env_adapter.load_bootstrap()

        # Database session factory
        effective_session_factory = session_factory or db_session_factory
        if effective_session_factory:
            self._session_factory = effective_session_factory
        else:
            from app.api.db import SessionLocal
            self._session_factory = SessionLocal

        self._sqlite_adapter = SqliteStoreAdapter(
            session_factory=self._session_factory,
            fallback_env_adapter=self._env_adapter,
        )

        # Rclone configuration path
        resolved_rclone_conf = rclone_conf_path or self._bootstrap.rclone_conf_path
        self._rclone_adapter = RcloneConfStoreAdapter(conf_path=resolved_rclone_conf)

        # Process-wide lease
        self._lease = ConfigurationLease()

    @property
    def lease(self) -> ConfigurationLease:
        """Access the process-wide configuration lease."""
        return self._lease

    def is_lease_held(self) -> bool:
        """Return True if the configuration lease is currently held."""
        return self._lease.is_held()

    @contextmanager
    def acquire_lease(self, holder: str, timeout: float = 10.0) -> Iterator[ConfigurationLease]:
        """Acquire the process-wide configuration lease synchronously."""
        with self._lease.acquire(holder=holder, timeout=timeout) as lease:
            yield lease

    @asynccontextmanager
    async def acquire_async_lease(self, holder: str, timeout: float = 10.0):
        """Acquire the process-wide configuration lease asynchronously."""
        async with self._lease.acquire_async(holder=holder, timeout=timeout) as lease:
            yield lease

    # --- Bootstrap settings (.env) ---
    def get_bootstrap(self) -> BootstrapSettings:
        """Return immutable bootstrap settings owned by .env."""
        return self._bootstrap

    # --- Schedule settings (SQLite) ---
    def get_schedule(self) -> ScheduleSettings:
        """Return Schedule settings owned by SQLite."""
        return self._sqlite_adapter.load_schedule()

    def set_schedule(self, settings: Union[ScheduleSettings, Dict[str, Any]]) -> None:
        """Validate and persist Schedule settings to SQLite."""
        typed_settings = _coerce_model(ScheduleSettings, settings)
        self._sqlite_adapter.save_schedule(typed_settings)

    # --- Performance settings (SQLite) ---
    def get_performance(self) -> RclonePerformanceSettings:
        """Return rclone performance settings owned by SQLite."""
        return self._sqlite_adapter.load_performance()

    def set_performance(self, settings: Union[RclonePerformanceSettings, Dict[str, Any]]) -> None:
        """Validate and persist rclone performance settings to SQLite."""
        typed_settings = _coerce_model(RclonePerformanceSettings, settings)
        self._sqlite_adapter.save_performance(typed_settings)

    # --- Sync path settings (SQLite) ---
    def get_sync_paths(self) -> SyncPathsSettings:
        """Return sync folder paths owned by SQLite."""
        return self._sqlite_adapter.load_sync_paths()

    def set_sync_paths(self, settings: Union[SyncPathsSettings, Dict[str, Any]]) -> None:
        """Validate and persist sync folder paths to SQLite."""
        typed_settings = _coerce_model(SyncPathsSettings, settings)
        self._sqlite_adapter.save_sync_paths(typed_settings)

    # --- Retention policy settings (SQLite) ---
    def get_retention_policy(self) -> RetentionPolicySettings:
        """Return retention policy settings owned by SQLite."""
        return self._sqlite_adapter.load_retention_policy()

    def set_retention_policy(self, settings: Union[RetentionPolicySettings, Dict[str, Any]]) -> None:
        """Validate and persist retention policy settings to SQLite."""
        typed_settings = _coerce_model(RetentionPolicySettings, settings)
        self._sqlite_adapter.save_retention_policy(typed_settings)

    def get_provenance(self, key: str) -> Optional[str]:
        """Return the provenance of a SQLite setting key."""
        return self._sqlite_adapter.get_provenance(key)

    def create_run_snapshot(self) -> tuple[SyncPathsSettings, RclonePerformanceSettings]:
        """Create an immutable snapshot of paths and performance settings for a sync run."""
        return (self.get_sync_paths(), self.get_performance())

    # --- Endpoints metadata (rclone.conf) ---
    def get_all_endpoint_metadata(self) -> Dict[str, EndpointMetadata]:
        """Return non-secret metadata for all endpoints defined in rclone.conf."""
        return self._rclone_adapter.get_endpoints_metadata()

    def get_endpoint_metadata(self, name: str) -> Optional[EndpointMetadata]:
        """Return non-secret metadata for a specific endpoint in rclone.conf."""
        return self._rclone_adapter.get_endpoints_metadata().get(name)

    # --- Effective configuration summary ---
    def get_effective(self) -> EffectiveConfiguration:
        """Return consolidated snapshot of all runtime configuration."""
        return EffectiveConfiguration(
            bootstrap=self.get_bootstrap(),
            schedule=self.get_schedule(),
            performance=self.get_performance(),
            paths=self.get_sync_paths(),
            retention=self.get_retention_policy(),
            endpoints=self.get_all_endpoint_metadata(),
        )

    # --- Diagnostics ---
    def get_diagnostics(self) -> List[SettingDiagnostic]:
        """Return non-secret diagnostics identifying owning stores, validity, and redacted values."""
        diagnostics: List[SettingDiagnostic] = []

        # Bootstrap (.env) diagnostics
        bootstrap = self.get_bootstrap()
        diagnostics.append(
            SettingDiagnostic(
                key="MASCLONER_BASE_DIR",
                owner=StoreType.ENV,
                is_valid=bootstrap.base_dir.exists(),
                is_secret=False,
                redacted_value=str(bootstrap.base_dir),
                source_location=str(self._env_adapter.env_path),
            )
        )
        diagnostics.append(
            SettingDiagnostic(
                key="MASCLONER_AUTH_ENABLED",
                owner=StoreType.ENV,
                is_valid=True,
                is_secret=False,
                redacted_value=str(bootstrap.auth_enabled),
                source_location=str(self._env_adapter.env_path),
            )
        )
        if bootstrap.auth_password:
            diagnostics.append(
                SettingDiagnostic(
                    key="MASCLONER_AUTH_PASSWORD",
                    owner=StoreType.ENV,
                    is_valid=True,
                    is_secret=True,
                    redacted_value="***",
                    source_location=str(self._env_adapter.env_path),
                )
            )

        # SQLite diagnostics
        try:
            schedule = self.get_schedule()
            sched_valid = True
        except Exception:
            schedule = ScheduleSettings()
            sched_valid = False

        diagnostics.append(
            SettingDiagnostic(
                key="schedule_enabled",
                owner=StoreType.SQLITE,
                is_valid=sched_valid,
                is_secret=False,
                redacted_value=str(schedule.enabled),
                source_location="SQLite (config_kv)",
            )
        )
        diagnostics.append(
            SettingDiagnostic(
                key="interval_min",
                owner=StoreType.SQLITE,
                is_valid=sched_valid,
                is_secret=False,
                redacted_value=str(schedule.interval_min),
                source_location="SQLite (config_kv)",
            )
        )
        diagnostics.append(
            SettingDiagnostic(
                key="jitter_sec",
                owner=StoreType.SQLITE,
                is_valid=sched_valid,
                is_secret=False,
                redacted_value=str(schedule.jitter_sec),
                source_location="SQLite (config_kv)",
            )
        )

        try:
            paths = self.get_sync_paths()
            paths_valid = True
        except Exception:
            paths = SyncPathsSettings()
            paths_valid = False

        diagnostics.append(
            SettingDiagnostic(
                key="gdrive_src",
                owner=StoreType.SQLITE,
                is_valid=paths_valid,
                is_secret=False,
                redacted_value=paths.gdrive_src,
                source_location="SQLite (config_kv)",
            )
        )
        diagnostics.append(
            SettingDiagnostic(
                key="nc_dest_path",
                owner=StoreType.SQLITE,
                is_valid=paths_valid,
                is_secret=False,
                redacted_value=paths.nc_dest_path,
                source_location="SQLite (config_kv)",
            )
        )

        try:
            perf = self.get_performance()
            perf_valid = True
        except Exception:
            perf = RclonePerformanceSettings()
            perf_valid = False

        diagnostics.append(
            SettingDiagnostic(
                key="transfers",
                owner=StoreType.SQLITE,
                is_valid=perf_valid,
                is_secret=False,
                redacted_value=str(perf.transfers),
                source_location="SQLite (config_kv)",
            )
        )

        try:
            retention = self.get_retention_policy()
            ret_valid = True
        except Exception:
            retention = RetentionPolicySettings()
            ret_valid = False

        diagnostics.append(
            SettingDiagnostic(
                key="retention_days",
                owner=StoreType.SQLITE,
                is_valid=ret_valid,
                is_secret=False,
                redacted_value=str(retention.retention_days),
                source_location="SQLite (config_kv)",
            )
        )

        # Rclone conf diagnostics
        endpoints = self.get_all_endpoint_metadata()
        for name, meta in endpoints.items():
            diagnostics.append(
                SettingDiagnostic(
                    key=name,
                    owner=StoreType.RCLONE_CONF,
                    is_valid=meta.is_configured,
                    is_secret=True,
                    redacted_value=f"[{meta.type}] configured",
                    source_location=str(self._rclone_adapter.conf_path),
                )
            )

        return diagnostics

    # --- Shadow reads comparison ---
    def compare_with_legacy(self, legacy_config_manager: Any, session: Session) -> Dict[str, Any]:
        """Compare effective values with legacy configuration resolution."""
        from app.api.scheduler import get_sync_config_from_db

        discrepancies: List[str] = []

        if legacy_config_manager is not None:
            # Compare base dir
            legacy_base = legacy_config_manager.get_base_config()
            if self._bootstrap.base_dir != legacy_base["base_dir"]:
                discrepancies.append(
                    f"base_dir mismatch: new={self._bootstrap.base_dir}, legacy={legacy_base['base_dir']}"
                )

            # Compare rclone performance settings
            legacy_perf = legacy_config_manager.get_rclone_config()
            perf = self.get_performance()
            if perf.transfers != legacy_perf["transfers"]:
                discrepancies.append(
                    f"transfers mismatch: new={perf.transfers}, legacy={legacy_perf['transfers']}"
                )
            if perf.checkers != legacy_perf["checkers"]:
                discrepancies.append(
                    f"checkers mismatch: new={perf.checkers}, legacy={legacy_perf['checkers']}"
                )

        # Compare sync config from DB
        legacy_sync = get_sync_config_from_db(session)
        paths = self.get_sync_paths()
        if paths.gdrive_src != legacy_sync.get("gdrive_src", ""):
            discrepancies.append(
                f"gdrive_src mismatch: new={paths.gdrive_src}, legacy={legacy_sync.get('gdrive_src')}"
            )
        if paths.nc_dest_path != legacy_sync.get("nc_dest_path", ""):
            discrepancies.append(
                f"nc_dest_path mismatch: new={paths.nc_dest_path}, legacy={legacy_sync.get('nc_dest_path')}"
            )

        return {
            "matches": len(discrepancies) == 0,
            "discrepancies": discrepancies,
        }
