"""Store adapters for .env, SQLite, and rclone.conf.

Encodes the ownership rules from ADR 0001:
- EnvStoreAdapter owns process bootstrap and host auth.
- SqliteStoreAdapter owns mutable application settings (schedule, paths, performance, retention).
- RcloneConfStoreAdapter owns endpoint definitions and credentials.
"""

from __future__ import annotations

import configparser
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.models import ConfigKV
from .exceptions import ConfigurationStoreError, ConfigurationValidationError
from .models import (
    BootstrapSettings,
    EndpointMetadata,
    RclonePerformanceSettings,
    RetentionPolicySettings,
    ScheduleSettings,
    StoreType,
    SyncPathsSettings,
)


class EnvStoreAdapter:
    """Private store adapter for .env and bootstrap environment variables."""

    def __init__(self, env_path: Path, base_dir: Optional[Path] = None) -> None:
        self.env_path = env_path
        self._explicit_base_dir = base_dir

    def _read_env_file_dict(self) -> Dict[str, str]:
        env_vars: Dict[str, str] = {}
        if self.env_path.exists():
            try:
                for line in self.env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, _, v = line.partition("=")
                    env_vars[k.strip()] = v.strip()
            except Exception as exc:
                raise ConfigurationStoreError(f"Failed to read .env file at {self.env_path}: {exc}") from exc
        return env_vars

    def get_val(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Read a value from .env file, falling back to process environment."""
        file_vars = self._read_env_file_dict()
        if key in file_vars:
            return file_vars[key]
        if key in os.environ:
            return os.environ[key]
        return default

    def load_bootstrap(self) -> BootstrapSettings:
        """Construct typed BootstrapSettings from environment and .env."""
        base_dir_str = self.get_val("MASCLONER_BASE_DIR")
        if self._explicit_base_dir:
            base_dir = self._explicit_base_dir
        elif base_dir_str:
            base_dir = Path(base_dir_str).resolve()
        else:
            base_dir = Path("/srv/mascloner")

        def _resolve_dir(key: str, default_sub: str) -> Path:
            val = self.get_val(key)
            if not val:
                return base_dir / default_sub
            p = Path(val)
            return p if p.is_absolute() else (base_dir / p).resolve()

        data_dir = _resolve_dir("MASCLONER_DATA_DIR", "data")
        log_dir = _resolve_dir("MASCLONER_LOG_DIR", "logs")
        run_dir = _resolve_dir("MASCLONER_RUN_DIR", "run")
        config_dir = _resolve_dir("MASCLONER_CONFIG_DIR", "etc")

        db_path_val = self.get_val("MASCLONER_DB_PATH")
        if db_path_val:
            p = Path(db_path_val)
            db_path = p if p.is_absolute() else (base_dir / p).resolve()
        else:
            db_path = data_dir / "mascloner.db"

        rclone_conf_val = self.get_val("MASCLONER_RCLONE_CONF")
        if rclone_conf_val:
            p = Path(rclone_conf_val)
            rclone_conf_path = p if p.is_absolute() else (base_dir / p).resolve()
        else:
            rclone_conf_path = config_dir / "rclone.conf"

        rclone_bin_val = self.get_val("MASCLONER_RCLONE_BIN")
        if rclone_bin_val:
            p = Path(rclone_bin_val)
            rclone_bin_path = p if p.is_absolute() else (base_dir / p).resolve()
        else:
            rclone_bin_path = base_dir / "bin" / "rclone"

        api_host = self.get_val("MASCLONER_API_HOST", "127.0.0.1") or "127.0.0.1"
        try:
            api_port = int(self.get_val("MASCLONER_API_PORT", "8787") or "8787")
        except ValueError:
            api_port = 8787

        ui_host = self.get_val("MASCLONER_UI_HOST", "127.0.0.1") or "127.0.0.1"
        try:
            ui_port = int(self.get_val("MASCLONER_UI_PORT", "8501") or "8501")
        except ValueError:
            ui_port = 8501

        auth_enabled_str = self.get_val("MASCLONER_AUTH_ENABLED", "false") or "false"
        auth_enabled = auth_enabled_str.lower() in ["true", "1", "yes"]

        auth_username = self.get_val("MASCLONER_AUTH_USERNAME")
        auth_password = self.get_val("MASCLONER_AUTH_PASSWORD")

        cors_env = self.get_val("MASCLONER_CORS_ORIGINS")
        if cors_env:
            cors_origins = [o.strip() for o in cors_env.split(",") if o.strip()]
        else:
            cors_origins = ["http://localhost:8501", "http://127.0.0.1:8501"]

        return BootstrapSettings(
            base_dir=base_dir,
            data_dir=data_dir,
            log_dir=log_dir,
            run_dir=run_dir,
            config_dir=config_dir,
            db_path=db_path,
            rclone_conf_path=rclone_conf_path,
            rclone_bin_path=rclone_bin_path,
            api_host=api_host,
            api_port=api_port,
            ui_host=ui_host,
            ui_port=ui_port,
            auth_enabled=auth_enabled,
            auth_username=auth_username,
            auth_password=auth_password,
            cors_origins=cors_origins,
        )


class SqliteStoreAdapter:
    """Private store adapter for SQLite settings (config_kv table)."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        fallback_env_adapter: Optional[EnvStoreAdapter] = None,
    ) -> None:
        self.session_factory = session_factory
        self.fallback_env_adapter = fallback_env_adapter

    def _fallback(self, key: str, default: str) -> str:
        if self.fallback_env_adapter:
            val = self.fallback_env_adapter.get_val(key)
            if val is not None:
                return val
        return os.getenv(key, default)

    def _get_kv(self, key: str, session: Session) -> Optional[str]:
        item = session.execute(select(ConfigKV).where(ConfigKV.key == key)).scalar_one_or_none()
        return item.value if item else None

    def _set_kv(self, key: str, value: str, session: Session) -> None:
        session.merge(ConfigKV(key=key, value=value))

    def load_schedule(self) -> ScheduleSettings:
        with self.session_factory() as session:
            enabled_val = self._get_kv("schedule_enabled", session)
            interval_val = self._get_kv("interval_min", session) or self._fallback("SYNC_INTERVAL_MIN", "5")
            jitter_val = self._get_kv("jitter_sec", session) or self._fallback("SYNC_JITTER_SEC", "20")

            enabled = True if enabled_val is None else (enabled_val.lower() in ["true", "1", "yes"])
            interval_min = int(interval_val) if interval_val and interval_val.isdigit() else 5
            jitter_sec = int(jitter_val) if jitter_val and jitter_val.isdigit() else 20

            return ScheduleSettings(enabled=enabled, interval_min=interval_min, jitter_sec=jitter_sec)

    def save_schedule(self, settings: ScheduleSettings) -> None:
        with self.session_factory() as session:
            try:
                self._set_kv("schedule_enabled", "true" if settings.enabled else "false", session)
                self._set_kv("interval_min", str(settings.interval_min), session)
                self._set_kv("jitter_sec", str(settings.jitter_sec), session)
                session.commit()
            except Exception as exc:
                session.rollback()
                raise ConfigurationStoreError(f"Failed to persist schedule settings: {exc}") from exc

    def load_performance(self) -> RclonePerformanceSettings:
        with self.session_factory() as session:
            transfers_val = self._get_kv("rclone_transfers", session) or self._fallback("RCLONE_TRANSFERS", "4")
            checkers_val = self._get_kv("rclone_checkers", session) or self._fallback("RCLONE_CHECKERS", "8")
            tpslimit_val = self._get_kv("rclone_tpslimit", session) or self._fallback("RCLONE_TPSLIMIT", "10")
            tpslimit_burst_val = self._get_kv("rclone_tpslimit_burst", session) or self._fallback("RCLONE_TPSLIMIT_BURST", "1")
            buffer_size_val = self._get_kv("rclone_buffer_size", session) or self._fallback("RCLONE_BUFFER_SIZE", "32Mi")
            chunk_size_val = self._get_kv("rclone_drive_chunk_size", session) or self._fallback("RCLONE_DRIVE_CHUNK_SIZE", "64M")
            cutoff_val = self._get_kv("rclone_drive_upload_cutoff", session) or self._fallback("RCLONE_DRIVE_UPLOAD_CUTOFF", "128M")
            fast_list_val = self._get_kv("rclone_fast_list", session) or self._fallback("RCLONE_FAST_LIST", "false")

            return RclonePerformanceSettings(
                transfers=int(transfers_val),
                checkers=int(checkers_val),
                tpslimit=int(tpslimit_val),
                tpslimit_burst=int(tpslimit_burst_val),
                buffer_size=buffer_size_val,
                drive_chunk_size=chunk_size_val,
                drive_upload_cutoff=cutoff_val,
                fast_list=fast_list_val.lower() in ["true", "1", "yes"],
            )

    def save_performance(self, settings: RclonePerformanceSettings) -> None:
        with self.session_factory() as session:
            try:
                self._set_kv("rclone_transfers", str(settings.transfers), session)
                self._set_kv("rclone_checkers", str(settings.checkers), session)
                self._set_kv("rclone_tpslimit", str(settings.tpslimit), session)
                self._set_kv("rclone_tpslimit_burst", str(settings.tpslimit_burst), session)
                if settings.buffer_size:
                    self._set_kv("rclone_buffer_size", settings.buffer_size, session)
                if settings.drive_chunk_size:
                    self._set_kv("rclone_drive_chunk_size", settings.drive_chunk_size, session)
                if settings.drive_upload_cutoff:
                    self._set_kv("rclone_drive_upload_cutoff", settings.drive_upload_cutoff, session)
                self._set_kv("rclone_fast_list", "true" if settings.fast_list else "false", session)
                session.commit()
            except Exception as exc:
                session.rollback()
                raise ConfigurationStoreError(f"Failed to persist performance settings: {exc}") from exc

    def load_sync_paths(self) -> SyncPathsSettings:
        with self.session_factory() as session:
            gdrive_src = self._get_kv("gdrive_src", session) or self._fallback("GDRIVE_SRC", "")
            nc_dest_path = self._get_kv("nc_dest_path", session) or self._fallback("NC_DEST_PATH", "")
            return SyncPathsSettings(gdrive_src=gdrive_src, nc_dest_path=nc_dest_path)

    def save_sync_paths(self, settings: SyncPathsSettings) -> None:
        with self.session_factory() as session:
            try:
                self._set_kv("gdrive_src", settings.gdrive_src, session)
                self._set_kv("nc_dest_path", settings.nc_dest_path, session)
                session.commit()
            except Exception as exc:
                session.rollback()
                raise ConfigurationStoreError(f"Failed to persist sync paths: {exc}") from exc

    def load_retention_policy(self) -> RetentionPolicySettings:
        with self.session_factory() as session:
            retention_val = self._get_kv("retention_days", session) or self._fallback("RETENTION_DAYS", "60")
            days = int(retention_val) if retention_val and retention_val.isdigit() else 60
            return RetentionPolicySettings(retention_days=days)

    def save_retention_policy(self, settings: RetentionPolicySettings) -> None:
        with self.session_factory() as session:
            try:
                self._set_kv("retention_days", str(settings.retention_days), session)
                session.commit()
            except Exception as exc:
                session.rollback()
                raise ConfigurationStoreError(f"Failed to persist retention policy: {exc}") from exc


class RcloneConfStoreAdapter:
    """Private store adapter for the managed rclone.conf file."""

    def __init__(self, conf_path: Path) -> None:
        self.conf_path = conf_path

    def _load_parser(self) -> configparser.RawConfigParser:
        parser = configparser.RawConfigParser()
        if self.conf_path.exists():
            try:
                parser.read(self.conf_path, encoding="utf-8")
            except Exception as exc:
                raise ConfigurationStoreError(f"Failed to parse rclone.conf at {self.conf_path}: {exc}") from exc
        return parser

    def get_endpoints_metadata(self) -> Dict[str, EndpointMetadata]:
        """Return safe, non-secret metadata for configured remotes."""
        parser = self._load_parser()
        endpoints: Dict[str, EndpointMetadata] = {}

        for section in parser.sections():
            section_type = parser.get(section, "type", fallback="unknown")
            details: Dict[str, str] = {}

            for opt in parser.options(section):
                # Filter out sensitive fields
                if opt in ["pass", "token", "client_secret"]:
                    details[f"{opt}_configured"] = "true"
                else:
                    details[opt] = parser.get(section, opt)

            endpoints[section] = EndpointMetadata(
                name=section,
                type=section_type,
                is_configured=True,
                details=details,
            )

        return endpoints
