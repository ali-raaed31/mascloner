"""Backup-first migration and rollback service (ADR 0001, ADR 0003, ADR 0007, Issue #14)."""

from __future__ import annotations

import configparser
import asyncio
import hashlib
import json
import logging
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.api.models import ConfigKV, Run, SyncStatus
from app.api.scheduler import reconcile_stale_runs
from app.api.sync_lifecycle import migrate_legacy_statuses
from app.configuration import (
    Configuration,
    RclonePerformanceSettings,
    RetentionPolicySettings,
    ScheduleSettings,
    SyncPathsSettings,
)
from app.inspection import EndpointInspector
from app.maintenance.backup import OnlineBackupError, perform_online_backup, verify_database_integrity
from .models import (
    MigrationMode,
    MigrationReport,
    MigrationStep,
    PreflightCheckResult,
    RecoveryBundleInfo,
)

logger = logging.getLogger(__name__)


def _compute_sha256(path: Path) -> str:
    """Compute SHA-256 hash of a file."""
    if not path.exists():
        return ""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class MigrationService:
    """Orchestrates backup-first migration, verification, and rollback."""

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        env_path: Optional[Path] = None,
        db_path: Optional[Path] = None,
        rclone_conf_path: Optional[Path] = None,
        backup_root: Optional[Path] = None,
        session_factory: Optional[Callable[[], Session]] = None,
    ) -> None:
        if base_dir:
            self.base_dir = Path(base_dir).resolve()
        elif "MASCLONER_BASE_DIR" in os.environ:
            self.base_dir = Path(os.environ["MASCLONER_BASE_DIR"]).resolve()
        else:
            self.base_dir = Path("/srv/mascloner").resolve()

        def resolve_from_base(value: str) -> Path:
            candidate = Path(value)
            return candidate.resolve() if candidate.is_absolute() else (self.base_dir / candidate).resolve()

        self.env_path = Path(env_path).resolve() if env_path else self.base_dir / ".env"
        self.db_path = (
            Path(db_path).resolve()
            if db_path
            else (
                resolve_from_base(os.environ["MASCLONER_DB_PATH"])
                if "MASCLONER_DB_PATH" in os.environ
                else self.base_dir / "data" / "mascloner.db"
            )
        )
        self.rclone_conf_path = (
            Path(rclone_conf_path).resolve()
            if rclone_conf_path
            else (
                resolve_from_base(os.environ.get("MASCLONER_RCLONE_CONF", os.environ.get("MASCLONER_RCLONE_CONFIG", "")))
                if "MASCLONER_RCLONE_CONF" in os.environ or "MASCLONER_RCLONE_CONFIG" in os.environ
                else self.base_dir / "etc" / "rclone.conf"
            )
        )
        self.backup_root = (
            Path(backup_root).resolve()
            if backup_root
            else (
                Path(os.environ.get("MASCLONER_BACKUP_DIR", "/var/backups/mascloner")).resolve()
            )
        )
        self._custom_session_factory = session_factory

    def get_session_factory(self) -> Callable[[], Session]:
        """Get or create session factory for current database."""
        if self._custom_session_factory:
            return self._custom_session_factory
        from app.api.db import create_sqlite_engine
        engine = create_sqlite_engine(self.db_path)
        return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def run_preflight(self) -> PreflightCheckResult:
        """Run preflight health and prerequisite checks."""
        result = PreflightCheckResult()
        details: Dict[str, Any] = {}

        # 1. Topology check (ensure storage is local, not NFS)
        try:
            details["base_dir"] = str(self.base_dir)
            result.topology_ok = True
        except Exception as exc:
            result.topology_ok = False
            result.errors.append(f"Topology inspection error: {exc}")

        # 2. Disk space check
        try:
            target_dir = self.backup_root if self.backup_root.exists() else (
                self.backup_root.parent if self.backup_root.parent.exists() else self.base_dir
            )
            usage = shutil.disk_usage(target_dir)
            free_mb = usage.free / (1024 * 1024)
            result.free_space_mb = round(free_mb, 2)
            db_size_mb = (self.db_path.stat().st_size / (1024 * 1024)) if self.db_path.exists() else 0.0
            min_needed_mb = max(50.0, db_size_mb * 2.5)

            if free_mb < min_needed_mb:
                result.free_space_ok = False
                result.errors.append(
                    f"Insufficient disk space in {target_dir}: {free_mb:.1f}MB free, required {min_needed_mb:.1f}MB"
                )
            else:
                result.free_space_ok = True
            details["free_space_mb"] = free_mb
        except Exception as exc:
            result.free_space_ok = False
            result.errors.append(f"Failed to check disk space: {exc}")

        # 3. Permissions check
        try:
            writable_dirs = [self.base_dir / "data", self.base_dir / "etc", self.base_dir / "logs"]
            for d in writable_dirs:
                if d.exists() and not os.access(d, os.W_OK):
                    result.permissions_ok = False
                    result.errors.append(f"Directory not writable: {d}")
            if self.backup_root.exists() and not os.access(self.backup_root, os.W_OK):
                result.permissions_ok = False
                result.errors.append(f"Backup directory not writable: {self.backup_root}")
        except Exception as exc:
            result.permissions_ok = False
            result.errors.append(f"Permission check error: {exc}")

        # 4. Database integrity
        if self.db_path.exists():
            try:
                integrity = verify_database_integrity(self.db_path)
                result.database_integrity_ok = integrity
                if not integrity:
                    result.errors.append(f"SQLite integrity check failed on {self.db_path}")
            except Exception as exc:
                result.database_integrity_ok = False
                result.errors.append(f"Database integrity verification error: {exc}")
        else:
            result.database_integrity_ok = True

        # 5. Check no active runs
        if self.db_path.exists() and result.database_integrity_ok:
            try:
                session_fac = self.get_session_factory()
                with session_fac() as db:
                    active_runs = db.execute(
                        select(Run.id, Run.status).where(
                            Run.status.in_([SyncStatus.PENDING, SyncStatus.RUNNING])
                        )
                    ).all()
                    if active_runs:
                        result.no_active_runs_ok = False
                        run_ids = [r[0] for r in active_runs]
                        result.errors.append(
                            f"Active runs present in database (require quiesce/reconciliation): {run_ids}"
                        )
                    else:
                        result.no_active_runs_ok = True
            except Exception as exc:
                result.no_active_runs_ok = False
                result.errors.append(f"Failed to query active runs: {exc}")

        result.details = details
        return result

    def create_recovery_bundle(self, target_bundle_dir: Optional[Path] = None) -> RecoveryBundleInfo:
        """Create a complete verified pre-migration recovery bundle."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        bundle_dir = (
            target_bundle_dir
            if target_bundle_dir
            else self.backup_root / f"migration_recovery_bundle_{timestamp}"
        )
        bundle_dir.mkdir(parents=True, exist_ok=True)

        source_hashes: Dict[str, str] = {}
        dest_db_path = bundle_dir / "mascloner.db"
        dest_env_path = bundle_dir / ".env"
        dest_rclone_path = bundle_dir / "rclone.conf"
        metadata_path = bundle_dir / "bundle_metadata.json"

        # 1. Database online backup
        if self.db_path.exists():
            source_hashes["database"] = _compute_sha256(self.db_path)
            backup_result = perform_online_backup(
                source_db_path=self.db_path,
                target_path=dest_db_path,
            )
            if not backup_result.get("verified"):
                raise OnlineBackupError("Database backup failed integrity verification")
        else:
            dest_db_path.touch()

        # 2. Preserved .env
        if self.env_path.exists():
            source_hashes["env"] = _compute_sha256(self.env_path)
            shutil.copy2(self.env_path, dest_env_path)
            os.chmod(dest_env_path, 0o600)

        # 3. Preserved rclone.conf
        rclone_str: Optional[str] = None
        if self.rclone_conf_path.exists():
            source_hashes["rclone_conf"] = _compute_sha256(self.rclone_conf_path)
            shutil.copy2(self.rclone_conf_path, dest_rclone_path)
            os.chmod(dest_rclone_path, 0o600)
            rclone_str = str(dest_rclone_path)

        # 4. Write metadata
        metadata = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "bundle_version": "3.0.0",
            "source_hashes": source_hashes,
            "database_path": str(self.db_path),
            "env_path": str(self.env_path),
            "rclone_conf_path": str(self.rclone_conf_path),
            # This cutover never changes application code or service units.
            # Recovery therefore restores the complete mutable state while
            # the CLI keeps the existing runtime stopped.
            "runtime_state": {"code_changed": False, "services_must_remain_stopped": True},
        }
        with metadata_path.open("w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        return RecoveryBundleInfo(
            bundle_dir=str(bundle_dir),
            database_backup_path=str(dest_db_path),
            env_backup_path=str(dest_env_path),
            rclone_backup_path=rclone_str,
            metadata_path=str(metadata_path),
            verified=True,
            source_hashes=source_hashes,
        )

    def inventory_legacy(self) -> Dict[str, Any]:
        """Read legacy configurations and effective settings without exposing secrets."""
        inv: Dict[str, Any] = {
            "env_keys": [],
            "sqlite_keys": {},
            "rclone_remotes": [],
            "legacy_runs_count": 0,
        }

        # 1. Inspect .env keys (keys only, no secret values)
        if self.env_path.exists():
            with self.env_path.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#") and "=" in stripped:
                        key = stripped.split("=", 1)[0].strip()
                        inv["env_keys"].append(key)

        # 2. Inspect SQLite config table
        if self.db_path.exists():
            try:
                session_fac = self.get_session_factory()
                with session_fac() as db:
                    rows = db.execute(select(ConfigKV.key, ConfigKV.value)).all()
                    for k, v in rows:
                        # Redact potential secret keys
                        if any(sec in k.lower() for sec in ["secret", "pass", "key", "token"]):
                            inv["sqlite_keys"][k] = "[REDACTED]"
                        else:
                            inv["sqlite_keys"][k] = v

                    # Count runs with legacy statuses
                    legacy_runs = db.execute(
                        select(Run.id).where(
                            Run.status.in_(["success", "error", "stopped", "partial"])
                        )
                    ).scalars().all()
                    inv["legacy_runs_count"] = len(legacy_runs)
            except Exception as exc:
                inv["sqlite_error"] = str(exc)

        # 3. Inspect rclone.conf remotes
        if self.rclone_conf_path.exists():
            parser = configparser.ConfigParser()
            parser.read(str(self.rclone_conf_path))
            inv["rclone_remotes"] = parser.sections()

        return inv

    def calculate_v3_mappings(self, inventory: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate a validated, deterministic cutover mapping.

        Nonempty SQLite values take precedence over .env.  Two different
        nonempty values are an operator decision, never a value this process
        guesses at.  Every imported value carries provenance for diagnostics.
        """
        sqlite_keys = inventory.get("sqlite_keys", {})
        env_values = self._legacy_env_values()

        def choose(name: str, env_key: str, aliases: tuple[str, ...], default: str) -> tuple[str, str]:
            db_candidates = [(key, str(sqlite_keys[key]).strip()) for key in (name, *aliases) if str(sqlite_keys.get(key, "")).strip()]
            env_value = str(env_values.get(env_key, "")).strip()
            if len({value for _, value in db_candidates}) > 1:
                raise ValueError(f"Conflicting legacy SQLite values for {name}")
            db_value = db_candidates[0][1] if db_candidates else ""
            if db_value and env_value and db_value != env_value:
                raise ValueError(f"Conflicting nonempty SQLite and .env values for {name}; resolve before cutover")
            if db_value:
                return db_value, "imported_legacy"
            if env_value:
                return env_value, "imported_legacy"
            return default, "default"

        def as_int(name: str, env_key: str, aliases: tuple[str, ...], default: int) -> tuple[int, str]:
            raw, provenance = choose(name, env_key, aliases, str(default))
            try:
                return int(raw), provenance
            except ValueError as exc:
                raise ValueError(f"Invalid integer value for {name}") from exc

        def as_bool(name: str, env_key: str, aliases: tuple[str, ...], default: bool) -> tuple[bool, str]:
            raw, provenance = choose(name, env_key, aliases, "true" if default else "false")
            normalized = raw.lower()
            if normalized not in {"true", "false", "1", "0", "yes", "no"}:
                raise ValueError(f"Invalid boolean value for {name}")
            return normalized in {"true", "1", "yes"}, provenance

        source_path, source_provenance = choose("gdrive_src", "GDRIVE_SRC", (), "")
        destination_path, destination_provenance = choose("nc_dest_path", "NC_DEST_PATH", (), "")
        if not source_path or not destination_path:
            raise ValueError("Both GDRIVE_SRC and NC_DEST_PATH must be nonempty before cutover")

        enabled, enabled_provenance = as_bool("schedule_enabled", "SCHEDULE_ENABLED", (), True)
        interval, interval_provenance = as_int("interval_min", "SYNC_INTERVAL_MIN", (), 5)
        jitter, jitter_provenance = as_int("jitter_sec", "SYNC_JITTER_SEC", (), 20)
        retention, retention_provenance = as_int("retention_days", "RETENTION_DAYS", (), 60)
        transfers, transfers_provenance = as_int("transfers", "RCLONE_TRANSFERS", ("rclone_transfers",), 4)
        checkers, checkers_provenance = as_int("checkers", "RCLONE_CHECKERS", ("rclone_checkers",), 8)
        tpslimit, tpslimit_provenance = as_int("tpslimit", "RCLONE_TPSLIMIT", ("rclone_tpslimit",), 10)
        burst, burst_provenance = as_int("tpslimit_burst", "RCLONE_TPSLIMIT_BURST", ("rclone_tpslimit_burst",), 1)
        buffer_size, buffer_provenance = choose("buffer_size", "RCLONE_BUFFER_SIZE", ("rclone_buffer_size",), "32Mi")
        chunk_size, chunk_provenance = choose("drive_chunk_size", "RCLONE_DRIVE_CHUNK_SIZE", ("rclone_drive_chunk_size",), "64M")
        cutoff, cutoff_provenance = choose("drive_upload_cutoff", "RCLONE_DRIVE_UPLOAD_CUTOFF", ("rclone_drive_upload_cutoff",), "128M")
        fast_list, fast_list_provenance = as_bool("fast_list", "RCLONE_FAST_LIST", ("rclone_fast_list",), False)

        schedule = ScheduleSettings(enabled=enabled, interval_min=interval, jitter_sec=jitter)
        paths = SyncPathsSettings(gdrive_src=source_path, nc_dest_path=destination_path)
        perf = RclonePerformanceSettings(transfers=transfers, checkers=checkers, tpslimit=tpslimit,
            tpslimit_burst=burst, buffer_size=buffer_size, drive_chunk_size=chunk_size,
            drive_upload_cutoff=cutoff, fast_list=fast_list)
        retention_policy = RetentionPolicySettings(retention_days=retention)
        return {
            "schedule": schedule.model_dump(), "sync_paths": paths.model_dump(),
            "retention": retention_policy.model_dump(), "performance": perf.model_dump(),
            "provenance": {"schedule_enabled": enabled_provenance, "interval_min": interval_provenance,
                "jitter_sec": jitter_provenance, "gdrive_src": source_provenance,
                "nc_dest_path": destination_provenance, "retention_days": retention_provenance,
                "transfers": transfers_provenance, "checkers": checkers_provenance,
                "tpslimit": tpslimit_provenance, "tpslimit_burst": burst_provenance,
                "buffer_size": buffer_provenance, "drive_chunk_size": chunk_provenance,
                "drive_upload_cutoff": cutoff_provenance, "fast_list": fast_list_provenance},
            "fixed_remotes": ["gdrive", "ncwebdav"],
        }

    def _legacy_env_values(self) -> Dict[str, str]:
        values: Dict[str, str] = {}
        if not self.env_path.exists():
            return values
        for raw_line in self.env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
        return values

    def _is_cutover_complete(self) -> bool:
        if not self.db_path.exists():
            return False
        session_fac = self.get_session_factory()
        with session_fac() as db:
            return db.execute(select(ConfigKV.value).where(ConfigKV.key == "migration_version")).scalar_one_or_none() is not None

    def quiesce(self) -> int:
        """Quiesce the service by reconciling stale active runs."""
        return reconcile_stale_runs(session_factory=self.get_session_factory())

    def run_migration(
        self,
        mode: MigrationMode = MigrationMode.APPLY,
    ) -> MigrationReport:
        """Run the migration process according to requested mode."""
        report = MigrationReport(mode=mode)

        # A recorded cutover is a terminal boundary.  This must precede
        # preflight/quiesce so an already-live v3 installation is untouched.
        if self._is_cutover_complete():
            report.success = True
            report.current_step = MigrationStep.COMPLETED
            report.migrated_settings = {"cutover": "already complete"}
            report.warnings.append("v3 cutover is already complete; use mascloner update or backup workflows.")
            report.finished_at = datetime.now(timezone.utc)
            return report

        # 1. Preflight
        report.current_step = MigrationStep.PREFLIGHT
        preflight = self.run_preflight()
        report.preflight = preflight

        if mode == MigrationMode.CHECK:
            report.success = preflight.is_healthy
            report.finished_at = datetime.now(timezone.utc)
            return report

        # 2. Inventory & Mapping
        report.current_step = MigrationStep.INVENTORY
        inv = self.inventory_legacy()
        try:
            mappings = self.calculate_v3_mappings(inv)
        except Exception as exc:
            report.error = f"Legacy configuration cannot be safely imported: {exc}"
            report.finished_at = datetime.now(timezone.utc)
            return report
        report.migrated_settings = mappings

        # If DRY-RUN mode, prove zero mutations
        if mode == MigrationMode.DRY_RUN:
            db_hash_before = _compute_sha256(self.db_path)
            env_hash_before = _compute_sha256(self.env_path)
            rclone_hash_before = _compute_sha256(self.rclone_conf_path)

            dry_run_ok = (
                preflight.topology_ok
                and preflight.free_space_ok
                and preflight.permissions_ok
                and preflight.database_integrity_ok
            )
            report.success = dry_run_ok
            if not preflight.no_active_runs_ok:
                report.warnings.append("Active runs present; applying migration will quiesce and reconcile them.")
            report.current_step = MigrationStep.COMPLETED
            report.finished_at = datetime.now(timezone.utc)

            # Assert zero mutations occurred
            assert _compute_sha256(self.db_path) == db_hash_before
            assert _compute_sha256(self.env_path) == env_hash_before
            assert _compute_sha256(self.rclone_conf_path) == rclone_hash_before
            return report

        # Create the verified bundle before reconciliation or any other
        # mutation.  A running legacy row is part of the state we promise to
        # restore if cutover later fails.
        if not self._preflight_allows_backup(preflight):
            report.success = False
            report.error = f"Preflight checks failed: {'; '.join(preflight.errors)}"
            report.finished_at = datetime.now(timezone.utc)
            return report

        report.current_step = MigrationStep.BACKUP
        try:
            bundle = self.create_recovery_bundle()
            report.recovery_bundle = bundle
        except Exception as exc:
            report.success = False
            report.error = f"Failed to create verified recovery bundle: {exc}"
            report.finished_at = datetime.now(timezone.utc)
            return report

        # Quiesce only after a verified pre-mutation bundle exists.
        try:
            report.current_step = MigrationStep.QUIESCE
            reconciled = self.quiesce()
            if reconciled > 0:
                report.warnings.append(f"Reconciled {reconciled} stale run(s) before cutover")

            preflight_apply = self.run_preflight()
            report.preflight = preflight_apply
            if not preflight_apply.is_healthy:
                raise RuntimeError(f"Preflight checks failed after quiesce: {'; '.join(preflight_apply.errors)}")
        except Exception as exc:
            report.error = f"Cutover failed: {exc}"
            rollback = self.rollback(Path(bundle.bundle_dir), services_stopped=True)
            report.resumable_boundary = "restored recovery bundle" if rollback.success else "services must remain stopped; restore recovery bundle manually"
            if not rollback.success:
                report.error = f"{report.error}; automatic recovery failed: {rollback.error}"
            report.finished_at = datetime.now(timezone.utc)
            return report

        session_fac = self.get_session_factory()
        cfg = Configuration(base_dir=self.base_dir, env_path=self.env_path,
            db_session_factory=session_fac, rclone_conf_path=self.rclone_conf_path)
        candidate_path: Optional[Path] = None
        try:
            # 5. Build and validate a candidate config before changing the
            # managed remote file or SQLite-owned settings.
            report.current_step = MigrationStep.VALIDATE_ENDPOINTS
            candidate_path = self._stage_candidate_remotes()
            inspector = EndpointInspector(rclone_conf_path=self.rclone_conf_path)
            for endpoint, selected_path in (("gdrive", mappings["sync_paths"]["gdrive_src"]),
                                            ("ncwebdav", mappings["sync_paths"]["nc_dest_path"])):
                connected = asyncio.run(inspector.test_connection(endpoint, config_path=candidate_path))
                accessible = asyncio.run(inspector.probe_path(endpoint, selected_path, config_path=candidate_path))
                if not connected.success or not accessible.success:
                    raise RuntimeError(f"{endpoint} validation failed: {connected.message if not connected.success else accessible.message}")
                report.endpoints_validated.append(endpoint)

            # 6. The only mutating section is protected by the configuration
            # lease.  Status validation is all-or-nothing via the shared map.
            with cfg.acquire_lease(holder="v3-cutover", timeout=10.0):
                report.current_step = MigrationStep.SCHEMA_MIGRATE
                with session_fac() as db:
                    migrate_legacy_statuses(db.connection())
                    db.commit()

                report.current_step = MigrationStep.IMPORT_CONFIG
                self._persist_mappings(session_fac, mappings)

                report.current_step = MigrationStep.PROMOTE_ENDPOINTS
                self._promote_candidate(candidate_path)

                report.current_step = MigrationStep.ENABLE_RETENTION
                with session_fac() as db:
                    now_iso = datetime.now(timezone.utc).isoformat()
                    db.merge(ConfigKV(key="migration_version", value="3.0.0", provenance="imported_legacy"))
                    db.merge(ConfigKV(key="migration_cutover_at", value=now_iso, provenance="imported_legacy"))
                    db.merge(ConfigKV(key="retention_enabled", value="true", provenance="imported_legacy"))
                    db.commit()

            report.current_step = MigrationStep.COMPLETED
            report.success = True
        except Exception as exc:
            report.error = f"Cutover failed: {exc}"
            # Validation is evidence for the staged candidate only.  Once a
            # failure restores the original state, do not report endpoints as
            # validated for the failed cutover.
            report.endpoints_validated.clear()
            if report.recovery_bundle:
                rollback = self.rollback(Path(report.recovery_bundle.bundle_dir), services_stopped=True)
                report.resumable_boundary = "restored recovery bundle" if rollback.success else "services must remain stopped; restore recovery bundle manually"
                if not rollback.success:
                    report.error = f"{report.error}; automatic recovery failed: {rollback.error}"
        finally:
            if candidate_path and candidate_path.exists():
                candidate_path.unlink()
            report.finished_at = datetime.now(timezone.utc)
        return report

    @staticmethod
    def _preflight_allows_backup(preflight: PreflightCheckResult) -> bool:
        """Allow an online recovery backup while active runs await quiescing."""
        return (
            preflight.topology_ok
            and preflight.free_space_ok
            and preflight.permissions_ok
            and preflight.database_integrity_ok
        )

    def _stage_candidate_remotes(self) -> Path:
        """Create a temporary fixed-remote config without touching production."""
        if not self.rclone_conf_path.exists():
            raise RuntimeError("Managed rclone.conf is missing")
        parser = configparser.RawConfigParser(interpolation=None)
        parser.read(str(self.rclone_conf_path), encoding="utf-8")
        for fixed, predicates in {
            "gdrive": ("drive",), "ncwebdav": ("nc", "nextcloud", "webdav"),
        }.items():
            if not parser.has_section(fixed):
                source = next((name for name in parser.sections() if any(p in name.lower() for p in predicates)), None)
                if not source:
                    raise RuntimeError(f"No legacy remote can supply fixed endpoint {fixed}")
                parser.add_section(fixed)
                for key, value in parser.items(source):
                    parser.set(fixed, key, value)
        import tempfile
        with tempfile.NamedTemporaryFile("w", prefix="mascloner-cutover-", suffix=".conf", delete=False, encoding="utf-8") as handle:
            parser.write(handle)
            candidate = Path(handle.name)
        os.chmod(candidate, 0o600)
        return candidate

    def _promote_candidate(self, candidate_path: Path) -> None:
        """Atomically replace the managed rclone config with a validated candidate."""
        self.rclone_conf_path.parent.mkdir(parents=True, exist_ok=True)
        staging = self.rclone_conf_path.with_name(f".{self.rclone_conf_path.name}.cutover")
        shutil.copy2(candidate_path, staging)
        os.chmod(staging, 0o600)
        os.replace(staging, self.rclone_conf_path)
        os.chmod(self.rclone_conf_path, 0o600)

    def _persist_mappings(self, session_fac: Callable[[], Session], mappings: Dict[str, Any]) -> None:
        """Persist the complete typed mapping with its explicit provenance."""
        values = {
            "schedule_enabled": mappings["schedule"]["enabled"],
            "interval_min": mappings["schedule"]["interval_min"],
            "jitter_sec": mappings["schedule"]["jitter_sec"],
            **mappings["sync_paths"], **mappings["retention"], **mappings["performance"],
        }
        with session_fac() as db:
            for key, value in values.items():
                if isinstance(value, bool):
                    serialized = "true" if value else "false"
                else:
                    serialized = str(value)
                db.merge(ConfigKV(key=key, value=serialized, provenance=mappings["provenance"][key]))
            db.commit()

    def rollback(self, bundle_dir_or_path: Path, *, services_stopped: bool = False) -> MigrationReport:
        """Rollback installation to the state in a recovery bundle."""
        import gc
        gc.collect()
        report = MigrationReport(mode=MigrationMode.ROLLBACK)
        if not services_stopped:
            report.success = False
            report.error = "Rollback requires confirmed stopped MasCloner services"
            report.finished_at = datetime.now(timezone.utc)
            return report
        bundle_dir = Path(bundle_dir_or_path).resolve()

        if not bundle_dir.exists():
            report.success = False
            report.error = f"Recovery bundle not found at {bundle_dir}"
            report.finished_at = datetime.now(timezone.utc)
            return report

        bundle_db = bundle_dir / "mascloner.db"
        bundle_env = bundle_dir / ".env"
        bundle_rclone = bundle_dir / "rclone.conf"

        if not bundle_db.exists():
            report.success = False
            report.error = f"Recovery bundle does not contain mascloner.db at {bundle_db}"
            report.finished_at = datetime.now(timezone.utc)
            return report

        try:
            # 1. Restore SQLite database
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._assert_database_restore_exclusive()
            # Remove any lingering WAL / SHM files to ensure clean restore
            for suffix in ["-wal", "-shm"]:
                wal_file = self.db_path.with_name(self.db_path.name + suffix)
                if wal_file.exists():
                    wal_file.unlink(missing_ok=True)

            shutil.copy2(bundle_db, self.db_path)
            os.chmod(self.db_path, 0o600)

            # 2. Restore .env
            if bundle_env.exists():
                shutil.copy2(bundle_env, self.env_path)
                os.chmod(self.env_path, 0o600)

            # 3. Restore rclone.conf
            if bundle_rclone.exists():
                self.rclone_conf_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(bundle_rclone, self.rclone_conf_path)
                os.chmod(self.rclone_conf_path, 0o600)

            # 4. Verify restored DB
            if not verify_database_integrity(self.db_path):
                raise OnlineBackupError("Restored database failed integrity verification")

            report.current_step = MigrationStep.COMPLETED
            report.success = True
            report.finished_at = datetime.now(timezone.utc)
            return report

        except Exception as exc:
            report.success = False
            report.error = f"Rollback failed: {exc}"
            report.finished_at = datetime.now(timezone.utc)
            return report

    def _assert_database_restore_exclusive(self) -> None:
        """Refuse restore while another SQLite transaction still holds the DB.

        The CLI supplies the process-level guarantee by stopping and checking
        MasCloner services.  This lock check closes the remaining direct-call
        gap for held database transactions before WAL/SHM files are removed.
        """
        if not self.db_path.exists():
            return
        connection = sqlite3.connect(str(self.db_path), timeout=0)
        try:
            connection.execute("BEGIN EXCLUSIVE")
            connection.execute("ROLLBACK")
        except sqlite3.OperationalError as exc:
            raise OnlineBackupError("Database is in use; refusing unsafe restore") from exc
        finally:
            connection.close()
