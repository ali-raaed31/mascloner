"""Store adapters for .env, SQLite, and rclone.conf.

Encodes the ownership rules from ADR 0001:
- EnvStoreAdapter owns process bootstrap and host auth.
- SqliteStoreAdapter owns mutable application settings (schedule, paths, performance, retention).
- RcloneConfStoreAdapter owns endpoint definitions and credentials.
"""

from __future__ import annotations

import configparser
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence
from sqlalchemy import select
from sqlalchemy.orm import Session

import json
from typing import Iterable
from app.api.models import ConfigKV

def redact_secrets(text: str, secrets: Iterable[Optional[str]]) -> str:
    """Replace occurrences of sensitive secrets with '***'."""
    if not text:
        return text
    result = text
    for sec in secrets:
        if not sec or not isinstance(sec, str):
            continue
        cleaned = sec.strip()
        if len(cleaned) >= 4:
            result = result.replace(cleaned, "***")
            if cleaned.startswith("{") and cleaned.endswith("}"):
                try:
                    parsed = json.loads(cleaned)
                    if isinstance(parsed, dict):
                        for v in parsed.values():
                            if isinstance(v, str) and len(v) >= 4:
                                result = result.replace(v, "***")
                except Exception:
                    pass
    return result
from .exceptions import ConfigurationStoreError, ConfigurationValidationError
from .models import (
    BootstrapSettings,
    GoogleDriveSourceDraft,
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

    def _get_kv_row(self, key: str, session: Session) -> Optional[ConfigKV]:
        return session.execute(select(ConfigKV).where(ConfigKV.key == key)).scalar_one_or_none()

    def _get_kv(self, key: str, session: Session) -> Optional[str]:
        item = self._get_kv_row(key, session)
        return item.value if item else None

    def _set_kv(self, key: str, value: str, session: Session, provenance: str = "user") -> None:
        session.merge(ConfigKV(key=key, value=value, provenance=provenance))

    def get_provenance(self, key: str) -> Optional[str]:
        with self.session_factory() as session:
            item = self._get_kv_row(key, session)
            return item.provenance if item else None

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
            transfers_val = self._get_kv("transfers", session) or self._get_kv("rclone_transfers", session) or self._fallback("RCLONE_TRANSFERS", "4")
            checkers_val = self._get_kv("checkers", session) or self._get_kv("rclone_checkers", session) or self._fallback("RCLONE_CHECKERS", "8")
            tpslimit_val = self._get_kv("tpslimit", session) or self._get_kv("rclone_tpslimit", session) or self._fallback("RCLONE_TPSLIMIT", "10")
            tpslimit_burst_val = self._get_kv("tpslimit_burst", session) or self._get_kv("rclone_tpslimit_burst", session) or self._fallback("RCLONE_TPSLIMIT_BURST", "1")
            buffer_size_val = self._get_kv("buffer_size", session) or self._get_kv("rclone_buffer_size", session) or self._fallback("RCLONE_BUFFER_SIZE", "32Mi")
            chunk_size_val = self._get_kv("drive_chunk_size", session) or self._get_kv("rclone_drive_chunk_size", session) or self._fallback("RCLONE_DRIVE_CHUNK_SIZE", "64M")
            cutoff_val = self._get_kv("drive_upload_cutoff", session) or self._get_kv("rclone_drive_upload_cutoff", session) or self._fallback("RCLONE_DRIVE_UPLOAD_CUTOFF", "128M")
            fast_list_val = self._get_kv("fast_list", session) or self._get_kv("rclone_fast_list", session) or self._fallback("RCLONE_FAST_LIST", "false")

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

    def save_performance(self, settings: RclonePerformanceSettings, provenance: str = "user") -> None:
        with self.session_factory() as session:
            try:
                self._set_kv("transfers", str(settings.transfers), session, provenance)
                self._set_kv("checkers", str(settings.checkers), session, provenance)
                self._set_kv("tpslimit", str(settings.tpslimit), session, provenance)
                self._set_kv("tpslimit_burst", str(settings.tpslimit_burst), session, provenance)
                if settings.buffer_size:
                    self._set_kv("buffer_size", settings.buffer_size, session, provenance)
                if settings.drive_chunk_size:
                    self._set_kv("drive_chunk_size", settings.drive_chunk_size, session, provenance)
                if settings.drive_upload_cutoff:
                    self._set_kv("drive_upload_cutoff", settings.drive_upload_cutoff, session, provenance)
                self._set_kv("fast_list", "true" if settings.fast_list else "false", session, provenance)
                session.commit()
            except Exception as exc:
                session.rollback()
                raise ConfigurationStoreError(f"Failed to persist performance settings: {exc}") from exc

    def load_sync_paths(self) -> SyncPathsSettings:
        with self.session_factory() as session:
            gdrive_src = self._get_kv("gdrive_src", session) or self._fallback("GDRIVE_SRC", "")
            nc_dest_path = self._get_kv("nc_dest_path", session) or self._fallback("NC_DEST_PATH", "")
            return SyncPathsSettings(gdrive_src=gdrive_src, nc_dest_path=nc_dest_path)

    def save_sync_paths(self, settings: SyncPathsSettings, provenance: str = "user") -> None:
        with self.session_factory() as session:
            try:
                self._set_kv("gdrive_src", settings.gdrive_src, session, provenance)
                self._set_kv("nc_dest_path", settings.nc_dest_path, session, provenance)
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



    def validate_draft(
        self, draft: GoogleDriveSourceDraft, rclone_bin: Path | str = "rclone"
    ) -> bool:
        """Validate candidate draft in an isolated temporary rclone config file.

        The live configuration at self.conf_path is never mutated or opened for writing.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_conf_path = Path(tmpdir) / "rclone.conf"
            cp = configparser.RawConfigParser(interpolation=None)
            cp.optionxform = str
            cp.add_section("gdrive")
            cp.set("gdrive", "type", "drive")
            cp.set("gdrive", "scope", draft.scope)
            cp.set("gdrive", "token", draft.token)

            existing_client_id = None
            existing_client_secret = None
            if self.conf_path.exists():
                try:
                    live_cp = configparser.RawConfigParser(interpolation=None)
                    live_cp.optionxform = str
                    live_cp.read(self.conf_path, encoding="utf-8")
                    if live_cp.has_section("gdrive"):
                        existing_client_id = live_cp.get("gdrive", "client_id", fallback=None)
                        existing_client_secret = live_cp.get("gdrive", "client_secret", fallback=None)
                except Exception:
                    pass

            eff_client_id = draft.client_id or existing_client_id
            eff_client_secret = draft.client_secret or existing_client_secret

            if eff_client_id:
                cp.set("gdrive", "client_id", eff_client_id)
            if eff_client_secret:
                cp.set("gdrive", "client_secret", eff_client_secret)
            if draft.team_drive:
                cp.set("gdrive", "team_drive", draft.team_drive)

            with open(tmp_conf_path, "w", encoding="utf-8") as f:
                cp.write(f)
            os.chmod(tmp_conf_path, 0o600)

            cmd = [str(rclone_bin), "about", "gdrive:", f"--config={tmp_conf_path}"]
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=15,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                raise ConfigurationValidationError("Google Drive draft validation timed out after 15s")
            except FileNotFoundError:
                raise ConfigurationValidationError(f"rclone binary not found at {rclone_bin}")

            if proc.returncode != 0:
                raw_err = proc.stderr or proc.stdout or f"exit code {proc.returncode}"
                redacted = redact_secrets(
                    raw_err, [draft.token, draft.client_secret, draft.client_id]
                )
                raise ConfigurationValidationError(
                    f"Google Drive credentials validation failed: {redacted.strip()}"
                )

        return True

    def promote_draft(self, draft: GoogleDriveSourceDraft) -> None:
        """Atomically promote validated draft to managed rclone.conf with 0600 permissions.

        Preserves any existing non-gdrive sections (e.g. ncwebdav).
        """
        self.conf_path.parent.mkdir(parents=True, exist_ok=True)
        parser = configparser.RawConfigParser(interpolation=None)
        parser.optionxform = str

        if self.conf_path.exists():
            try:
                with open(self.conf_path, "r", encoding="utf-8") as f:
                    parser.read_file(f)
            except Exception as exc:
                raise ConfigurationStoreError(f"Failed to read existing rclone.conf: {exc}") from exc

        if not parser.has_section("gdrive"):
            parser.add_section("gdrive")

        parser.set("gdrive", "type", "drive")
        parser.set("gdrive", "scope", draft.scope)
        parser.set("gdrive", "token", draft.token)

        eff_client_id = draft.client_id or (parser.get("gdrive", "client_id", fallback=None) if parser.has_option("gdrive", "client_id") else None)
        eff_client_secret = draft.client_secret or (parser.get("gdrive", "client_secret", fallback=None) if parser.has_option("gdrive", "client_secret") else None)

        if eff_client_id:
            parser.set("gdrive", "client_id", eff_client_id)
        elif parser.has_option("gdrive", "client_id"):
            parser.remove_option("gdrive", "client_id")

        if eff_client_secret:
            parser.set("gdrive", "client_secret", eff_client_secret)
        elif parser.has_option("gdrive", "client_secret"):
            parser.remove_option("gdrive", "client_secret")

        if draft.team_drive:
            parser.set("gdrive", "team_drive", draft.team_drive)
        elif parser.has_option("gdrive", "team_drive"):
            parser.remove_option("gdrive", "team_drive")

        orig_content = self.conf_path.read_bytes() if self.conf_path.exists() else None
        tmp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                dir=str(self.conf_path.parent),
                delete=False,
                encoding="utf-8",
            ) as tf:
                parser.write(tf)
                tf.flush()
                os.fsync(tf.fileno())
                tmp_path = Path(tf.name)

            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, self.conf_path)
            os.chmod(self.conf_path, 0o600)
        except Exception as exc:
            if orig_content is not None:
                try:
                    self.conf_path.write_bytes(orig_content)
                    os.chmod(self.conf_path, 0o600)
                except Exception:
                    pass
            raise ConfigurationStoreError(f"Failed to atomically promote rclone.conf: {exc}") from exc
        finally:
            if tmp_path and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except Exception:
                    pass
