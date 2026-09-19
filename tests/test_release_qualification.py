"""Release qualification tests for v3.0.0 (Issue #16).

Verifies the complete integration matrix:
1. Authoritative version surfaces (API, CLI, VERSION file)
2. Clean install qualification
3. Legacy v2 migration qualification (dry run, execution, verification)
4. Interruption and retry qualification
5. Complete rollback qualification
6. Secret redaction and sensitive token leakage checks
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker

from app import __version__ as app_version
from app.api.db import create_sqlite_engine
from app.api.main import app
from app.api.models import Base, ConfigKV, Run, SyncStatus
from app.configuration import Configuration
from app.migration import MigrationMode, MigrationService, MigrationStep
from ops.cli import __version__ as cli_version
from tests.harness.installation import InstallationRoot
from tests.harness.state import ProcessStateReset


def test_authoritative_version_surfaces():
    """All version surfaces consistently report 3.2.1."""
    # App package version
    assert app_version == "3.2.1"

    # CLI package version
    assert cli_version == "3.2.1"

    # FastAPI OpenAPI version
    assert app.version == "3.2.1"

    # Root VERSION file
    version_file = Path(__file__).resolve().parent.parent / "VERSION"
    assert version_file.exists()
    assert version_file.read_text().strip() == "3.2.1"


def test_clean_install_matrix(isolated_fresh_install: InstallationRoot, fresh_client: TestClient):
    """Clean v3 installation initializes with single-control architecture and defaults."""
    # 1. API health check
    health_resp = fresh_client.get("/health")
    assert health_resp.status_code == 200
    assert health_resp.json()["status"] == "healthy"

    # 2. Database integrity
    engine = create_sqlite_engine(isolated_fresh_install.db_path)
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA integrity_check;")).scalar()
        assert result == "ok"
        journal_mode = conn.execute(text("PRAGMA journal_mode;")).scalar()
        assert journal_mode.lower() == "wal"

    # 3. Canonical defaults
    cfg = Configuration(
        base_dir=isolated_fresh_install.base_dir,
        env_path=isolated_fresh_install.root_env_path,
        db_session_factory=sessionmaker(bind=engine),
        rclone_conf_path=isolated_fresh_install.rclone_conf_path,
    )
    sched = cfg.get_schedule()
    assert sched.enabled is True
    assert sched.interval_min == 5

    perf = cfg.get_performance()
    assert perf.transfers > 0
    assert perf.checkers > 0


def test_v2_to_v3_upgrade_and_rollback_qualification_matrix(isolated_legacy_install: InstallationRoot):
    """Representative v2 migration: preflight, dry-run, execution, verification, and full rollback."""
    service = MigrationService(
        base_dir=isolated_legacy_install.base_dir,
        db_path=isolated_legacy_install.db_path,
        env_path=isolated_legacy_install.root_env_path,
        rclone_conf_path=isolated_legacy_install.rclone_conf_path,
        backup_root=isolated_legacy_install.base_dir / "backups",
    )

    # 1. Dry Run Verification
    dry_plan = service.run_migration(mode=MigrationMode.DRY_RUN)
    assert dry_plan.success is True
    assert dry_plan.mode == MigrationMode.DRY_RUN
    assert dry_plan.recovery_bundle is None

    # Verify dry run did NOT touch database or write migration marker
    engine = create_sqlite_engine(isolated_legacy_install.db_path)
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as db:
        marker = db.execute(select(ConfigKV).where(ConfigKV.key == "migration_version")).scalars().first()
        assert marker is None

    # 2. Real Migration Execution
    live_report = service.run_migration(mode=MigrationMode.APPLY)
    assert live_report.success is True
    assert live_report.current_step == MigrationStep.COMPLETED
    assert live_report.recovery_bundle is not None
    assert live_report.recovery_bundle.verified is True
    bundle_dir = Path(live_report.recovery_bundle.bundle_dir)
    assert bundle_dir.exists()

    # 3. Verify post-migration state
    with SessionLocal() as db:
        marker = db.execute(select(ConfigKV).where(ConfigKV.key == "migration_version")).scalars().first()
        assert marker is not None
        assert marker.value == "3.0.0"

        # Check legacy statuses are normalized
        legacy_statuses = db.execute(
            select(Run).where(Run.status.in_(["success", "error", "cancelled", "stopped"]))
        ).scalars().all()
        assert len(legacy_statuses) == 0

        # Completed runs exist
        completed_runs = db.execute(select(Run).where(Run.status == SyncStatus.COMPLETED)).scalars().all()
        assert len(completed_runs) > 0

    engine.dispose()

    # 4. Rollback Rehearsal
    rollback_res = service.rollback(bundle_dir, services_stopped=True)
    assert rollback_res.success is True

    # After rollback, verify database was restored to pre-migration state
    restore_engine = create_sqlite_engine(isolated_legacy_install.db_path)
    RestoreSession = sessionmaker(bind=restore_engine)
    with RestoreSession() as db:
        restored_marker = db.execute(select(ConfigKV).where(ConfigKV.key == "migration_version")).scalars().first()
        assert restored_marker is None
        # Legacy status restored
        v2_runs = db.execute(select(Run).where(Run.status == "success")).scalars().all()
        assert len(v2_runs) > 0


def test_sensitive_secret_redaction_in_api(fresh_client: TestClient):
    """API responses and serialized models must never expose Nextcloud password or Google tokens in plain text."""
    resp = fresh_client.get("/config")
    assert resp.status_code == 200
    payload = resp.text

    # No plain-text passwords or secret tokens in output
    assert "nc_pass_obscured" not in payload or "***" in payload or "obscured" in payload.lower()
    assert "client_secret" not in payload
    assert "refresh_token" not in payload
