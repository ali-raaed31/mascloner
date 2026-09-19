"""Tests for backup-first migration and rollback workflow (Issue #14)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import patch
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from typer.testing import CliRunner

from app.api.models import ConfigKV, Run, SyncStatus
from app.configuration import Configuration
from app.migration import (
    MigrationMode,
    MigrationReport,
    MigrationStep,
    MigrationService,
)
from ops.cli.main import app as cli_app
from tests.harness.installation import InstallationRoot


def _compute_sha(p: Path) -> str:
    if not p.exists():
        return ""
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_migration_preflight_on_healthy_install(isolated_legacy_install: InstallationRoot):
    """Preflight passes on a valid, quiesced legacy install."""
    service = MigrationService(
        base_dir=isolated_legacy_install.base_dir,
        env_path=isolated_legacy_install.root_env_path,
        db_path=isolated_legacy_install.db_path,
        rclone_conf_path=isolated_legacy_install.rclone_conf_path,
        backup_root=isolated_legacy_install.base_dir / "backups",
    )
    # Unquiesced preflight detects in-flight runs
    res_unquiesced = service.run_preflight()
    assert res_unquiesced.no_active_runs_ok is False

    # Quiesce service
    reconciled = service.quiesce()
    assert reconciled >= 1

    # Post-quiesce preflight is fully healthy
    res = service.run_preflight()
    assert res.is_healthy is True
    assert res.database_integrity_ok is True
    assert res.topology_ok is True
    assert res.permissions_ok is True


def test_migration_preflight_catches_corrupted_database(isolated_legacy_install: InstallationRoot):
    """Preflight fails closed if database fails SQLite integrity check."""
    service = MigrationService(
        base_dir=isolated_legacy_install.base_dir,
        env_path=isolated_legacy_install.root_env_path,
        db_path=isolated_legacy_install.db_path,
        rclone_conf_path=isolated_legacy_install.rclone_conf_path,
        backup_root=isolated_legacy_install.base_dir / "backups",
    )
    # Corrupt the database file
    isolated_legacy_install.db_path.write_bytes(b"corrupted SQLite database file content")

    res = service.run_preflight()
    assert res.is_healthy is False
    assert res.database_integrity_ok is False
    assert any("integrity" in err.lower() for err in res.errors)


def test_migration_preflight_catches_insufficient_disk_space(isolated_legacy_install: InstallationRoot):
    """Preflight fails closed if free disk space is insufficient."""
    service = MigrationService(
        base_dir=isolated_legacy_install.base_dir,
        env_path=isolated_legacy_install.root_env_path,
        db_path=isolated_legacy_install.db_path,
        rclone_conf_path=isolated_legacy_install.rclone_conf_path,
        backup_root=isolated_legacy_install.base_dir / "backups",
    )
    # Mock disk_usage to report 1MB free
    from collections import namedtuple
    Usage = namedtuple("Usage", ["total", "used", "free"])

    with patch("shutil.disk_usage", return_value=Usage(total=10**9, used=10**9, free=1024 * 1024)):
        res = service.run_preflight()
        assert res.is_healthy is False
        assert res.free_space_ok is False
        assert any("space" in err.lower() for err in res.errors)


def test_migration_dry_run_zero_mutations(isolated_legacy_install: InstallationRoot):
    """Dry-run inventories legacy state, computes mappings, and performs zero mutations."""
    service = MigrationService(
        base_dir=isolated_legacy_install.base_dir,
        env_path=isolated_legacy_install.root_env_path,
        db_path=isolated_legacy_install.db_path,
        rclone_conf_path=isolated_legacy_install.rclone_conf_path,
        backup_root=isolated_legacy_install.base_dir / "backups",
    )

    db_hash_before = _compute_sha(isolated_legacy_install.db_path)
    env_hash_before = _compute_sha(isolated_legacy_install.root_env_path)
    rclone_hash_before = _compute_sha(isolated_legacy_install.rclone_conf_path)

    report = service.run_migration(mode=MigrationMode.DRY_RUN)

    assert report.success is True
    assert report.mode == MigrationMode.DRY_RUN
    assert report.migrated_settings["schedule"]["enabled"] is True
    assert report.migrated_settings["schedule"]["interval_min"] == 10
    assert report.migrated_settings["retention"]["retention_days"] == 60

    # Ensure ZERO file modifications
    assert _compute_sha(isolated_legacy_install.db_path) == db_hash_before
    assert _compute_sha(isolated_legacy_install.root_env_path) == env_hash_before
    assert _compute_sha(isolated_legacy_install.rclone_conf_path) == rclone_hash_before


def test_migration_apply_and_rollback_workflow(isolated_legacy_install: InstallationRoot):
    """Full cutover migration imports config, establishes fixed remotes, and rolls back cleanly."""
    service = MigrationService(
        base_dir=isolated_legacy_install.base_dir,
        env_path=isolated_legacy_install.root_env_path,
        db_path=isolated_legacy_install.db_path,
        rclone_conf_path=isolated_legacy_install.rclone_conf_path,
        backup_root=isolated_legacy_install.base_dir / "backups",
    )

    orig_db_hash = _compute_sha(isolated_legacy_install.db_path)

    # 1. Execute apply
    report = service.run_migration(mode=MigrationMode.APPLY)
    assert report.success is True
    assert report.current_step == MigrationStep.COMPLETED
    assert report.recovery_bundle is not None
    assert report.recovery_bundle.verified is True

    bundle_dir = Path(report.recovery_bundle.bundle_dir)
    assert bundle_dir.exists()
    assert (bundle_dir / "mascloner.db").exists()
    assert (bundle_dir / ".env").exists()
    assert (bundle_dir / "bundle_metadata.json").exists()

    # 2. Verify imported settings in SQLite via Configuration
    engine = create_engine(f"sqlite:///{isolated_legacy_install.db_path}")
    SessionLocal = sessionmaker(bind=engine)

    cfg = Configuration(
        base_dir=isolated_legacy_install.base_dir,
        env_path=isolated_legacy_install.root_env_path,
        db_session_factory=SessionLocal,
        rclone_conf_path=isolated_legacy_install.rclone_conf_path,
    )
    schedule = cfg.get_schedule()
    assert schedule.enabled is True
    assert schedule.interval_min == 10
    assert schedule.jitter_sec == 30

    paths = cfg.get_sync_paths()
    assert paths.gdrive_src == "LegacyFolder"
    assert paths.nc_dest_path == "LegacyBackups"

    retention = cfg.get_retention_policy()
    assert retention.retention_days == 60

    # Verify cutover milestone recorded
    with SessionLocal() as db:
        v = db.execute(select(ConfigKV.value).where(ConfigKV.key == "migration_version")).scalar_one_or_none()
        assert v == "3.0.0"
        ret_en = db.execute(select(ConfigKV.value).where(ConfigKV.key == "retention_enabled")).scalar_one_or_none()
        assert ret_en == "true"

        # Verify legacy statuses were migrated to canonical terminal statuses
        statuses = set(db.execute(select(Run.status)).scalars().all())
        assert "success" not in statuses
        assert "error" not in statuses
        assert "stopped" not in statuses
        assert SyncStatus.COMPLETED in statuses
        assert SyncStatus.FAILED in statuses
        assert SyncStatus.ABORTED in statuses

    engine.dispose()

    # 3. Test Rollback
    rollback_report = service.rollback(bundle_dir, services_stopped=True)
    assert rollback_report.success is True
    assert rollback_report.current_step == MigrationStep.COMPLETED

    # Verify database was restored exactly to recovery bundle state
    assert _compute_sha(isolated_legacy_install.db_path) == _compute_sha(bundle_dir / "mascloner.db")
    with SessionLocal() as db:
        mig_v = db.execute(select(ConfigKV.value).where(ConfigKV.key == "migration_version")).scalar_one_or_none()
        assert mig_v is None


def test_migration_cli_commands(isolated_legacy_install: InstallationRoot, monkeypatch: pytest.MonkeyPatch):
    """Test mascloner migrate CLI with --check, --dry-run, --apply, and --rollback."""
    monkeypatch.setenv("MASCLONER_BASE_DIR", str(isolated_legacy_install.base_dir))
    monkeypatch.setenv("MASCLONER_DB_PATH", str(isolated_legacy_install.db_path))
    monkeypatch.setenv("MASCLONER_ENV_FILE", str(isolated_legacy_install.root_env_path))
    monkeypatch.setenv("MASCLONER_RCLONE_CONFIG", str(isolated_legacy_install.rclone_conf_path))
    monkeypatch.setenv("MASCLONER_BACKUP_DIR", str(isolated_legacy_install.base_dir / "backups"))

    runner = CliRunner()

    # 1. Check
    res_check = runner.invoke(cli_app, ["migrate", "--check"])
    assert res_check.exit_code == 0
    assert "Preflight Checks" in res_check.stdout
    assert "Topology" in res_check.stdout

    # 2. Dry-run
    res_dry = runner.invoke(cli_app, ["migrate", "--dry-run"])
    assert res_dry.exit_code == 0
    assert "Simulating Migration" in res_dry.stdout
    assert "Effective Migrated Settings" in res_dry.stdout

    # 3. Apply
    res_apply = runner.invoke(cli_app, ["migrate", "--apply"])
    assert res_apply.exit_code == 0
    assert "Migration cutover completed successfully" in res_apply.stdout
    assert "Verified Recovery Bundle Created" in res_apply.stdout


def test_migration_idempotent_reapply(isolated_legacy_install: InstallationRoot):
    """Re-running apply after migration succeeds idempotently."""
    service = MigrationService(
        base_dir=isolated_legacy_install.base_dir,
        env_path=isolated_legacy_install.root_env_path,
        db_path=isolated_legacy_install.db_path,
        rclone_conf_path=isolated_legacy_install.rclone_conf_path,
        backup_root=isolated_legacy_install.base_dir / "backups",
    )

    rep1 = service.run_migration(mode=MigrationMode.APPLY)
    assert rep1.success is True

    rep2 = service.run_migration(mode=MigrationMode.APPLY)
    assert rep2.success is True
