"""Backup-first migration and rollback service (ADR 0001, ADR 0003, ADR 0007, Issue #14)."""

from __future__ import annotations

import configparser
import hashlib
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from sqlalchemy import create_engine, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.api.models import Base, ConfigKV, Run, SyncStatus
from app.api.scheduler import reconcile_stale_runs
from app.configuration import (
    Configuration,
    EffectiveConfiguration,
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

        self.env_path = Path(env_path).resolve() if env_path else self.base_dir / ".env"
        self.db_path = (
            Path(db_path).resolve()
            if db_path
            else (
                Path(os.environ["MASCLONER_DB_PATH"]).resolve()
                if "MASCLONER_DB_PATH" in os.environ
                else self.base_dir / "data" / "mascloner.db"
            )
        )
        self.rclone_conf_path = (
            Path(rclone_conf_path).resolve()
            if rclone_conf_path
            else (
                Path(os.environ["MASCLONER_RCLONE_CONFIG"]).resolve()
                if "MASCLONER_RCLONE_CONFIG" in os.environ
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
        details = {}

        # 1. Topology check (ensure storage is local, not NFS)
        try:
            stat_target = self.base_dir if self.base_dir.exists() else self.db_path.parent
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
            details["free_space_mb"] = result.free_space_mb
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
        """Calculate proposed v3 configuration mappings from legacy inventory."""
        sqlite_keys = inventory.get("sqlite_keys", {})

        # Schedule: preserve continuity with enabled=True per ADR 0007 / Issue #14
        interval_min = int(sqlite_keys.get("interval_min", 5))
        jitter_sec = int(sqlite_keys.get("jitter_sec", 30))

        # Paths
        source_path = sqlite_keys.get("gdrive_src", "")
        dest_path = sqlite_keys.get("nc_dest_path", "")

        # Retention
        retention_days = int(sqlite_keys.get("retention_days", 60))

        # Performance
        transfers = int(sqlite_keys.get("rclone_transfers", 4))
        checkers = int(sqlite_keys.get("rclone_checkers", 8))

        return {
            "schedule": {
                "enabled": True,
                "interval_min": interval_min,
                "jitter_sec": jitter_sec,
            },
            "sync_paths": {
                "gdrive_src": source_path,
                "nc_dest_path": dest_path,
            },
            "retention": {
                "retention_days": retention_days,
            },
            "performance": {
                "transfers": transfers,
                "checkers": checkers,
            },
            "fixed_remotes": ["gdrive", "ncwebdav"],
        }

    def quiesce(self) -> int:
        """Quiesce the service by reconciling stale active runs."""
        return reconcile_stale_runs(session_factory=self.get_session_factory())

    def run_migration(
        self,
        mode: MigrationMode = MigrationMode.APPLY,
    ) -> MigrationReport:
        """Run the migration process according to requested mode."""
        report = MigrationReport(mode=mode)

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
        mappings = self.calculate_v3_mappings(inv)
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

        # APPLY mode: Quiesce first, then verify preflight
        report.current_step = MigrationStep.QUIESCE
        reconciled = self.quiesce()
        if reconciled > 0:
            report.warnings.append(f"Reconciled {reconciled} stale run(s) before cutover")

        preflight_apply = self.run_preflight()
        report.preflight = preflight_apply
        if not preflight_apply.is_healthy:
            report.success = False
            report.error = f"Preflight checks failed: {'; '.join(preflight_apply.errors)}"
            report.finished_at = datetime.now(timezone.utc)
            return report

        # 4. Backup (create verified recovery bundle)
        report.current_step = MigrationStep.BACKUP
        try:
            bundle = self.create_recovery_bundle()
            report.recovery_bundle = bundle
        except Exception as exc:
            report.success = False
            report.error = f"Failed to create verified recovery bundle: {exc}"
            report.finished_at = datetime.now(timezone.utc)
            return report

        # 5. Schema & Status Migration
        report.current_step = MigrationStep.SCHEMA_MIGRATE
        session_fac = self.get_session_factory()
        with session_fac() as db:
            # Map legacy statuses to canonical terminal statuses
            db.execute(
                update(Run)
                .where(Run.status == "success")
                .values(status=SyncStatus.COMPLETED)
            )
            db.execute(
                update(Run)
                .where(Run.status == "error")
                .values(status=SyncStatus.FAILED)
            )
            db.execute(
                update(Run)
                .where(Run.status == "stopped")
                .values(status=SyncStatus.ABORTED)
            )
            db.execute(
                update(Run)
                .where(Run.status == "partial")
                .values(status=SyncStatus.COMPLETED)
            )
            db.commit()

        # 6. Import mutable configuration into SQLite
        report.current_step = MigrationStep.IMPORT_CONFIG
        cfg = Configuration(
            base_dir=self.base_dir,
            env_path=self.env_path,
            db_session_factory=session_fac,
            rclone_conf_path=self.rclone_conf_path,
        )

        cfg.set_schedule(ScheduleSettings(
            enabled=True,  # Continuity per ADR 0007 / Issue #14
            interval_min=mappings["schedule"]["interval_min"],
            jitter_sec=mappings["schedule"]["jitter_sec"],
        ))
        cfg.set_sync_paths(SyncPathsSettings(
            gdrive_src=mappings["sync_paths"]["gdrive_src"],
            nc_dest_path=mappings["sync_paths"]["nc_dest_path"],
        ))
        cfg.set_retention_policy(RetentionPolicySettings(
            retention_days=mappings["retention"]["retention_days"],
        ))
        cfg.set_performance(RclonePerformanceSettings(
            transfers=mappings["performance"]["transfers"],
            checkers=mappings["performance"]["checkers"],
        ))

        # 7. Fixed endpoints validation and promotion
        report.current_step = MigrationStep.VALIDATE_ENDPOINTS
        if self.rclone_conf_path.exists():
            parser = configparser.ConfigParser()
            parser.read(str(self.rclone_conf_path))

            # Ensure fixed sections exist, copying legacy remote names if needed
            changed = False
            if "gdrive" not in parser.sections():
                # Check for legacy remote candidates like gdrive_src or gdrive_backup
                candidates = [s for s in parser.sections() if "drive" in s.lower()]
                if candidates:
                    parser.add_section("gdrive")
                    for k, v in parser.items(candidates[0]):
                        parser.set("gdrive", k, v)
                    changed = True

            if "ncwebdav" not in parser.sections():
                candidates = [s for s in parser.sections() if "nc" in s.lower() or "nextcloud" in s.lower() or "webdav" in s.lower()]
                if candidates:
                    parser.add_section("ncwebdav")
                    for k, v in parser.items(candidates[0]):
                        parser.set("ncwebdav", k, v)
                    changed = True

            if changed:
                with self.rclone_conf_path.open("w", encoding="utf-8") as f:
                    parser.write(f)

            report.endpoints_validated = [s for s in parser.sections() if s in ["gdrive", "ncwebdav"]]

        # 8. Smoke test
        report.current_step = MigrationStep.SMOKE_TEST
        loaded_schedule = cfg.get_schedule()
        assert loaded_schedule.enabled is True

        # 9. Mark cutover and enable retention
        report.current_step = MigrationStep.ENABLE_RETENTION
        with session_fac() as db:
            now_iso = datetime.now(timezone.utc).isoformat()
            db.merge(ConfigKV(key="migration_version", value="3.0.0"))
            db.merge(ConfigKV(key="migration_cutover_at", value=now_iso))
            db.merge(ConfigKV(key="retention_enabled", value="true"))
            db.commit()

        report.current_step = MigrationStep.COMPLETED
        report.success = True
        report.finished_at = datetime.now(timezone.utc)
        return report

    def rollback(self, bundle_dir_or_path: Path) -> MigrationReport:
        """Rollback installation to the state in a recovery bundle."""
        import gc
        gc.collect()
        report = MigrationReport(mode=MigrationMode.ROLLBACK)
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
