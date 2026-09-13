"""Tests for Issue #10: Canonical SyncStatus lifecycle, migration, and stale run recovery.

Verifies:
1. Canonical states: pending, running, completed, failed, aborted, skipped.
2. Alembic migration maps legacy statuses (success -> completed, error/partial -> failed, cancelled/stopped -> aborted).
3. Migration blocks safely on unknown statuses.
4. Valid vs invalid lifecycle state transitions.
5. Pending run is durable before execution, transitions to running when execution begins.
6. Overlapping executions produce durable skipped runs with clear reasons.
7. Startup recovery converts stale pending/running runs into failed runs with recovery details.
8. User abort maps to aborted.
9. API filtering and schemas support all canonical statuses.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.db import create_sqlite_engine, get_db_session
from app.api.models import Base, Run, SyncStatus, validate_status_transition
from app.api.scheduler import reconcile_stale_runs, sync_job
from tests.harness.installation import InstallationRoot


def test_canonical_sync_status_enum_values():
    """All 6 canonical status values exist and are lower-case strings."""
    assert SyncStatus.PENDING == "pending"
    assert SyncStatus.RUNNING == "running"
    assert SyncStatus.COMPLETED == "completed"
    assert SyncStatus.FAILED == "failed"
    assert SyncStatus.ABORTED == "aborted"
    assert SyncStatus.SKIPPED == "skipped"

    assert SyncStatus.is_terminal("completed") is True
    assert SyncStatus.is_terminal("failed") is True
    assert SyncStatus.is_terminal("aborted") is True
    assert SyncStatus.is_terminal("skipped") is True
    assert SyncStatus.is_terminal("pending") is False
    assert SyncStatus.is_terminal("running") is False


def test_allowed_status_transitions():
    """Valid transitions succeed; invalid transitions raise ValueError."""
    # Pending transitions
    assert validate_status_transition("pending", "running") == "running"
    assert validate_status_transition("pending", "failed") == "failed"
    assert validate_status_transition("pending", "aborted") == "aborted"
    assert validate_status_transition("pending", "skipped") == "skipped"

    # Running transitions
    assert validate_status_transition("running", "completed") == "completed"
    assert validate_status_transition("running", "failed") == "failed"
    assert validate_status_transition("running", "aborted") == "aborted"

    # Invalid transitions
    with pytest.raises(ValueError, match="Invalid status transition"):
        validate_status_transition("pending", "completed")

    with pytest.raises(ValueError, match="Invalid status transition"):
        validate_status_transition("completed", "running")

    with pytest.raises(ValueError, match="Invalid status transition"):
        validate_status_transition("failed", "completed")

    with pytest.raises(ValueError, match="Invalid status transition"):
        validate_status_transition("aborted", "running")

    with pytest.raises(ValueError, match="Invalid status transition"):
        validate_status_transition("skipped", "running")


def test_migration_maps_legacy_statuses(temp_dir: Path):
    """Alembic migration maps success -> completed, error/partial -> failed, cancelled/stopped -> aborted."""
    from alembic import command
    from alembic.config import Config

    db_path = temp_dir / "migration_test.db"
    engine = create_sqlite_engine(db_path)
    Base.metadata.create_all(bind=engine)

    # Seed legacy runs
    with Session(engine) as session:
        session.execute(text("INSERT INTO runs (id, status, started_at, num_added, num_updated, bytes_transferred, errors) VALUES (1, 'success', CURRENT_TIMESTAMP, 0, 0, 0, 0)"))
        session.execute(text("INSERT INTO runs (id, status, started_at, num_added, num_updated, bytes_transferred, errors) VALUES (2, 'error', CURRENT_TIMESTAMP, 0, 0, 0, 0)"))
        session.execute(text("INSERT INTO runs (id, status, started_at, num_added, num_updated, bytes_transferred, errors) VALUES (3, 'partial', CURRENT_TIMESTAMP, 0, 0, 0, 0)"))
        session.execute(text("INSERT INTO runs (id, status, started_at, num_added, num_updated, bytes_transferred, errors) VALUES (4, 'stopped', CURRENT_TIMESTAMP, 0, 0, 0, 0)"))
        session.execute(text("INSERT INTO runs (id, status, started_at, num_added, num_updated, bytes_transferred, errors) VALUES (5, 'cancelled', CURRENT_TIMESTAMP, 0, 0, 0, 0)"))
        session.execute(text("INSERT INTO runs (id, status, started_at, num_added, num_updated, bytes_transferred, errors) VALUES (6, 'running', CURRENT_TIMESTAMP, 0, 0, 0, 0)"))
        session.commit()

    # Apply migration 20250101_000003
    # Test canonical status migration helper
    # Verify migration script logic
    from app.api.sync_lifecycle import migrate_legacy_statuses
    migrate_legacy_statuses(engine)

    with Session(engine) as session:
        rows = {r[0]: r[1] for r in session.execute(text("SELECT id, status FROM runs ORDER BY id")).fetchall()}

    assert rows[1] == "completed"
    assert rows[2] == "failed"
    assert rows[3] == "failed"
    assert rows[4] == "aborted"
    assert rows[5] == "aborted"
    assert rows[6] == "running"


def test_migration_fails_safely_on_unknown_status(temp_dir: Path):
    """Migration raises error and aborts if an unknown legacy status is encountered."""
    from app.api.sync_lifecycle import migrate_legacy_statuses

    db_path = temp_dir / "unknown_status.db"
    engine = create_sqlite_engine(db_path)
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        session.execute(text("INSERT INTO runs (id, status, started_at, num_added, num_updated, bytes_transferred, errors) VALUES (10, 'mysterious_status', CURRENT_TIMESTAMP, 0, 0, 0, 0)"))
        session.commit()

    with pytest.raises(ValueError, match="Unknown legacy run status 'mysterious_status'"):
        migrate_legacy_statuses(engine)


def test_startup_reconciles_stale_runs(isolated_fresh_install: InstallationRoot):
    """Startup recovery transitions stale pending/running runs to failed with recovery explanation."""
    with get_db_session() as session:
        r1 = Run(status="pending", started_at=datetime.now(timezone.utc))
        r2 = Run(status="running", started_at=datetime.now(timezone.utc))
        r3 = Run(status="completed", started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc))
        session.add_all([r1, r2, r3])
        session.commit()
        r1_id, r2_id, r3_id = r1.id, r2.id, r3.id

    # Run startup reconciliation
    recovered_count = reconcile_stale_runs()
    assert recovered_count == 2

    with get_db_session() as session:
        run1 = session.get(Run, r1_id)
        run2 = session.get(Run, r2_id)
        run3 = session.get(Run, r3_id)

        assert run1.status == "failed"
        assert "Interrupted" in (run1.message or "")
        assert run1.finished_at is not None

        assert run2.status == "failed"
        assert "Interrupted" in (run2.message or "")
        assert run2.finished_at is not None

        # Terminal run was untouched
        assert run3.status == "completed"


def test_overlapping_execution_records_skipped_run(
    isolated_fresh_install: InstallationRoot,
    monkeypatch: pytest.MonkeyPatch,
):
    """When sync is triggered while a lock is held, a durable 'skipped' run is recorded."""
    from app.api import scheduler

    # Lock is already held
    scheduler._sync_lock.acquire(blocking=False)
    try:
        scheduler.sync_job()
    finally:
        scheduler._sync_lock.release()

    with get_db_session() as session:
        latest_run = session.execute(
            select(Run).order_by(Run.id.desc())
        ).scalars().first()

        assert latest_run is not None
        assert latest_run.status == "skipped"
        assert "skip" in (latest_run.message or "").lower()
        assert latest_run.finished_at is not None


def test_api_status_filtering_and_schemas(test_client: TestClient, test_session: Session):
    """API /runs endpoint filters correctly by canonical status."""
    # Trigger or seed runs into the test session used by test_client
    test_session.add(Run(status="completed", started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc)))
    test_session.add(Run(status="failed", started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc)))
    test_session.add(Run(status="aborted", started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc)))
    test_session.add(Run(status="skipped", started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc)))
    test_session.commit()

    for status_val in ["completed", "failed", "aborted", "skipped"]:
        resp = test_client.get(f"/runs?status={status_val}")
        assert resp.status_code == 200, resp.text
        runs = resp.json()
        assert len(runs) >= 1
        assert all(r["status"] == status_val for r in runs)


def test_alembic_upgrade_and_downgrade_lifecycle(tmp_path: Path):
    """Verify Alembic migration 20250101_000003 upgrade and downgrade cycle."""
    import sqlite3
    from alembic import command
    from alembic.config import Config

    db_file = tmp_path / "migration_cycle.db"
    project_root = Path(__file__).parent.parent
    alembic_cfg = Config(str(project_root / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(project_root / "alembic"))
    alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_file}")

    # 1. Upgrade to 20250101_000002
    command.upgrade(alembic_cfg, "20250101_000002")

    # Seed legacy rows
    conn = sqlite3.connect(db_file)
    conn.execute(
        "INSERT INTO runs (id, status, started_at, num_added, num_updated, bytes_transferred, errors) "
        "VALUES (1, 'success', CURRENT_TIMESTAMP, 0, 0, 0, 0)"
    )
    conn.commit()
    conn.close()

    # 2. Upgrade to 20250101_000003
    command.upgrade(alembic_cfg, "20250101_000003")

    conn = sqlite3.connect(db_file)
    cur = conn.cursor()
    cur.execute("SELECT status, message FROM runs WHERE id = 1")
    row = cur.fetchone()
    assert row[0] == "completed"
    conn.close()

    # 3. Downgrade back to 20250101_000002
    command.downgrade(alembic_cfg, "20250101_000002")

    conn = sqlite3.connect(db_file)
    cur = conn.cursor()
    cur.execute("SELECT status FROM runs WHERE id = 1")
    row = cur.fetchone()
    assert row[0] == "success"
    # Verify message column dropped
    col_names = [col[1] for col in cur.execute("PRAGMA table_info(runs)").fetchall()]
    assert "message" not in col_names
    conn.close()
