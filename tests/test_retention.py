"""Tests for 60-day RetentionPolicy (ADR 0008, Issue #13)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.testclient import TestClient
from typer.testing import CliRunner

from app.api import db as api_db
from app.api.models import Base, ConfigKV, FileEvent, Run, SyncStatus
from app.api.scheduler import SyncScheduler, retention_job
from app.configuration import Configuration, RetentionPolicySettings
from app.retention import RetentionReport, RetentionService
from ops.cli.main import app as cli_app
from tests.harness.installation import InstallationRoot


@pytest.fixture
def temp_db_and_session(tmp_path: Path):
    """Create a temporary sqlite DB and sessionmaker."""
    db_path = tmp_path / "test_retention.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    yield session_factory, tmp_path
    engine.dispose()


def test_retention_defaults_to_60_days():
    """RetentionPolicySettings default must be exactly 60 days per ADR 0008."""
    settings = RetentionPolicySettings()
    assert settings.retention_days == 60


def test_retention_strictly_beyond_cutoff_boundary(temp_db_and_session):
    """Only terminal records strictly beyond 60-day cutoff are eligible."""
    session_factory, _ = temp_db_and_session
    service = RetentionService(session_factory=session_factory)

    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
    cutoff = now - timedelta(days=60)  # 2026-07-17 12:00:00

    with session_factory() as db:
        # Run 1: 61 days old, completed -> eligible
        r1 = Run(
            status=SyncStatus.COMPLETED,
            started_at=cutoff - timedelta(days=1, hours=1),
            finished_at=cutoff - timedelta(days=1),
        )
        # Run 2: exactly at cutoff -> NOT eligible (must be strictly beyond)
        r2 = Run(
            status=SyncStatus.COMPLETED,
            started_at=cutoff - timedelta(hours=1),
            finished_at=cutoff,
        )
        # Run 3: 59 days old -> NOT eligible
        r3 = Run(
            status=SyncStatus.COMPLETED,
            started_at=cutoff + timedelta(days=1),
            finished_at=cutoff + timedelta(days=1, hours=1),
        )
        # Run 4: 70 days old, but PENDING -> NEVER eligible
        r4 = Run(
            status=SyncStatus.PENDING,
            started_at=cutoff - timedelta(days=10),
            finished_at=None,
        )
        # Run 5: 70 days old, but RUNNING -> NEVER eligible
        r5 = Run(
            status=SyncStatus.RUNNING,
            started_at=cutoff - timedelta(days=10),
            finished_at=None,
        )
        # Run 6: 62 days old, FAILED -> eligible
        r6 = Run(
            status=SyncStatus.FAILED,
            started_at=cutoff - timedelta(days=2, hours=1),
            finished_at=cutoff - timedelta(days=2),
        )
        # Run 7: 63 days old, ABORTED -> eligible
        r7 = Run(
            status=SyncStatus.ABORTED,
            started_at=cutoff - timedelta(days=3, hours=1),
            finished_at=cutoff - timedelta(days=3),
        )
        # Run 8: 64 days old, SKIPPED (finished_at may be same as started_at) -> eligible
        r8 = Run(
            status=SyncStatus.SKIPPED,
            started_at=cutoff - timedelta(days=4),
            finished_at=cutoff - timedelta(days=4),
        )
        db.add_all([r1, r2, r3, r4, r5, r6, r7, r8])
        db.commit()

        r1_id = r1.id
        r2_id = r2.id
        r3_id = r3.id
        r4_id = r4.id
        r5_id = r5.id
        r6_id = r6.id
        r7_id = r7.id
        r8_id = r8.id

    # Apply retention with controlled 'now'
    report = service.apply_retention(now=now)

    assert report.is_dry_run is False
    assert report.runs_deleted == 4  # r1, r6, r7, r8
    assert report.retention_days == 60
    assert report.cutoff_utc == cutoff

    with session_factory() as db:
        remaining_ids = set(db.execute(select(Run.id)).scalars().all())
        assert r1_id not in remaining_ids
        assert r6_id not in remaining_ids
        assert r7_id not in remaining_ids
        assert r8_id not in remaining_ids

        # Non-eligible runs remain intact
        assert r2_id in remaining_ids
        assert r3_id in remaining_ids
        assert r4_id in remaining_ids  # pending never deleted
        assert r5_id in remaining_ids  # running never deleted


def test_retention_cleans_file_events_and_logs(temp_db_and_session):
    """Deleting expired runs also removes dependent FileEvents and log files."""
    session_factory, tmp_path = temp_db_and_session
    service = RetentionService(session_factory=session_factory)

    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
    cutoff = now - timedelta(days=60)

    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file1 = log_dir / "sync_run1.log"
    log_file1.write_text("sync log content 1", encoding="utf-8")

    with session_factory() as db:
        run1 = Run(
            status=SyncStatus.COMPLETED,
            started_at=cutoff - timedelta(days=5),
            finished_at=cutoff - timedelta(days=5),
            log_path=str(log_file1),
        )
        run2 = Run(
            status=SyncStatus.COMPLETED,
            started_at=cutoff - timedelta(days=6),
            finished_at=cutoff - timedelta(days=6),
            log_path=str(log_dir / "missing_file.log"),  # Already missing
        )
        db.add_all([run1, run2])
        db.commit()

        ev1 = FileEvent(run_id=run1.id, timestamp=run1.started_at, action="copy", file_path="a.txt", file_size=100)
        ev2 = FileEvent(run_id=run1.id, timestamp=run1.started_at, action="copy", file_path="b.txt", file_size=200)
        ev3 = FileEvent(run_id=run2.id, timestamp=run2.started_at, action="copy", file_path="c.txt", file_size=300)
        db.add_all([ev1, ev2, ev3])
        db.commit()

        run1_id = run1.id
        run2_id = run2.id

    assert log_file1.exists()

    report = service.apply_retention(now=now)

    assert report.runs_deleted == 2
    assert report.events_deleted == 3
    assert report.logs_deleted == 1
    assert not log_file1.exists()  # deleted from filesystem

    with session_factory() as db:
        remaining_events = db.execute(select(FileEvent).where(FileEvent.run_id.in_([run1_id, run2_id]))).scalars().all()
        assert len(remaining_events) == 0


def test_retention_log_deletion_failure_handled_safely(temp_db_and_session):
    """If log file deletion raises an OSError, report tracks failure without rolling back DB deletion."""
    session_factory, tmp_path = temp_db_and_session
    service = RetentionService(session_factory=session_factory)

    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
    cutoff = now - timedelta(days=60)

    log_file = tmp_path / "locked.log"
    log_file.write_text("locked", encoding="utf-8")

    with session_factory() as db:
        run = Run(
            status=SyncStatus.COMPLETED,
            started_at=cutoff - timedelta(days=5),
            finished_at=cutoff - timedelta(days=5),
            log_path=str(log_file),
        )
        db.add(run)
        db.commit()
        run_id = run.id

    with patch.object(Path, "unlink", side_effect=PermissionError("Permission denied")):
        report = service.apply_retention(now=now)

    assert report.runs_deleted == 1
    assert len(report.log_deletion_failures) == 1
    assert "Permission denied" in report.log_deletion_failures[0]

    with session_factory() as db:
        remaining = db.get(Run, run_id)
        assert remaining is None  # DB record still deleted


def test_retention_dry_run_leaves_database_and_disk_untouched(temp_db_and_session):
    """Dry-run reports accurate counts but makes zero mutations."""
    session_factory, tmp_path = temp_db_and_session
    service = RetentionService(session_factory=session_factory)

    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
    cutoff = now - timedelta(days=60)

    log_file = tmp_path / "dry_run.log"
    log_file.write_text("test dry run", encoding="utf-8")

    with session_factory() as db:
        run = Run(
            status=SyncStatus.COMPLETED,
            started_at=cutoff - timedelta(days=5),
            finished_at=cutoff - timedelta(days=5),
            log_path=str(log_file),
        )
        db.add(run)
        db.commit()

        ev = FileEvent(run_id=run.id, timestamp=run.started_at, action="copy", file_path="dry.txt", file_size=50)
        db.add(ev)
        db.commit()
        run_id = run.id

    report = service.apply_retention(dry_run=True, now=now)

    assert report.is_dry_run is True
    assert report.runs_evaluated == 1
    assert report.runs_deleted == 1
    assert report.events_deleted == 1
    assert report.logs_deleted == 1

    # Verify nothing was deleted
    assert log_file.exists()
    with session_factory() as db:
        r = db.get(Run, run_id)
        assert r is not None
        events = db.execute(select(FileEvent).where(FileEvent.run_id == run_id)).scalars().all()
        assert len(events) == 1


def test_retention_batched_processing(temp_db_and_session):
    """Retention cleans up in small bounded batches."""
    session_factory, _ = temp_db_and_session
    service = RetentionService(session_factory=session_factory)

    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
    cutoff = now - timedelta(days=60)

    # Create 25 expired runs
    with session_factory() as db:
        for i in range(25):
            r = Run(
                status=SyncStatus.COMPLETED,
                started_at=cutoff - timedelta(days=i + 1),
                finished_at=cutoff - timedelta(days=i + 1),
            )
            db.add(r)
        db.commit()

    # Process in batches of 7 (4 batches total: 7, 7, 7, 4)
    report = service.apply_retention(batch_size=7, now=now)

    assert report.runs_deleted == 25

    with session_factory() as db:
        remaining = db.execute(select(func.count(Run.id))).scalar()
        assert remaining == 0


def test_retention_idempotent_repeated_passes(temp_db_and_session):
    """Running retention repeatedly is completely safe and a no-op when clean."""
    session_factory, _ = temp_db_and_session
    service = RetentionService(session_factory=session_factory)

    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
    cutoff = now - timedelta(days=60)

    with session_factory() as db:
        db.add(Run(
            status=SyncStatus.COMPLETED,
            started_at=cutoff - timedelta(days=2),
            finished_at=cutoff - timedelta(days=2),
        ))
        db.commit()

    r1 = service.apply_retention(now=now)
    assert r1.runs_deleted == 1

    r2 = service.apply_retention(now=now)
    assert r2.runs_deleted == 0
    assert r2.events_deleted == 0
    assert r2.logs_deleted == 0


def test_retention_last_report_persistence(temp_db_and_session):
    """Last report is saved in SQLite ConfigKV and retrievable via get_last_report."""
    session_factory, _ = temp_db_and_session
    service = RetentionService(session_factory=session_factory)

    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
    cutoff = now - timedelta(days=60)

    with session_factory() as db:
        db.add(Run(
            status=SyncStatus.COMPLETED,
            started_at=cutoff - timedelta(days=2),
            finished_at=cutoff - timedelta(days=2),
        ))
        db.commit()

    rep = service.apply_retention(now=now)

    # In-memory check
    assert service.get_last_report() == rep

    # New service instance loading from DB
    new_service = RetentionService(session_factory=session_factory)
    loaded = new_service.get_last_report()
    assert loaded is not None
    assert loaded.runs_deleted == rep.runs_deleted
    assert loaded.cutoff_utc == rep.cutoff_utc


def test_retention_api_endpoints(fresh_client: TestClient, isolated_fresh_install: InstallationRoot):
    """Verify GET /maintenance/retention and POST /maintenance/retention API endpoints."""
    # 1. Initial status check
    resp = fresh_client.get("/maintenance/retention")
    assert resp.status_code == 200
    data = resp.json()
    assert data["retention_days"] == 60
    assert data["last_report"] is None

    # Insert an old run
    old_time = datetime.now(timezone.utc) - timedelta(days=65)
    with api_db.SessionLocal() as db:
        run = Run(
            status=SyncStatus.COMPLETED,
            started_at=old_time,
            finished_at=old_time,
        )
        db.add(run)
        db.commit()

    # 2. Dry run trigger
    dry_resp = fresh_client.post("/maintenance/retention?dry_run=true")
    assert dry_resp.status_code == 200
    dry_data = dry_resp.json()
    assert dry_data["success"] is True
    assert dry_data["data"]["is_dry_run"] is True
    assert dry_data["data"]["runs_deleted"] == 1

    # Verify run still exists
    with api_db.SessionLocal() as db:
        count = db.execute(select(func.count(Run.id))).scalar()
        assert count == 1

    # 3. Apply trigger
    apply_resp = fresh_client.post("/maintenance/retention?dry_run=false")
    assert apply_resp.status_code == 200
    apply_data = apply_resp.json()
    assert apply_data["success"] is True
    assert apply_data["data"]["is_dry_run"] is False
    assert apply_data["data"]["runs_deleted"] == 1

    # Verify run was deleted
    with api_db.SessionLocal() as db:
        count = db.execute(select(func.count(Run.id))).scalar()
        assert count == 0

    # 4. GET status now reflects last report
    status_resp = fresh_client.get("/maintenance/retention")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["last_report"] is not None
    assert status_data["last_report"]["runs_deleted"] == 1


def test_retention_scheduler_job():
    """Verify SyncScheduler retention job scheduling and execution."""
    scheduler = SyncScheduler()
    try:
        assert scheduler.add_retention_job(hour=4, minute=30) is True
        job = scheduler.scheduler.get_job("retention")
        assert job is not None
        assert "retention" in job.name.lower()

        # Execute retention_job directly
        report = retention_job()
        assert report is not None
        assert isinstance(report, RetentionReport)
    finally:
        scheduler.stop()
        RetentionService.reset_instance()


def test_retention_cli_command(isolated_fresh_install: InstallationRoot):
    """Verify mascloner prune CLI command in dry-run and apply modes."""
    runner = CliRunner()

    # Dry-run
    res_dry = runner.invoke(cli_app, ["prune", "--dry-run"])
    assert res_dry.exit_code == 0
    assert "Simulating History Pruning" in res_dry.stdout
    assert "Dry-Run" in res_dry.stdout

    # Apply
    res_apply = runner.invoke(cli_app, ["prune", "--days", "30", "--batch-size", "50"])
    assert res_apply.exit_code == 0
    assert "Pruning Expired History" in res_apply.stdout
    assert "History pruned successfully" in res_apply.stdout


def test_retention_concurrency_with_active_sync(temp_db_and_session):
    """Retention operation does not interfere with concurrently active sync run."""
    session_factory, _ = temp_db_and_session
    service = RetentionService(session_factory=session_factory)

    now = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)
    cutoff = now - timedelta(days=60)

    with session_factory() as db:
        # Expired completed run
        db.add(Run(
            status=SyncStatus.COMPLETED,
            started_at=cutoff - timedelta(days=5),
            finished_at=cutoff - timedelta(days=5),
        ))
        # Active currently running run (started 5 minutes ago)
        active_run = Run(
            status=SyncStatus.RUNNING,
            started_at=now - timedelta(minutes=5),
            finished_at=None,
        )
        db.add(active_run)
        db.commit()
        active_id = active_run.id

    report = service.apply_retention(now=now)

    assert report.runs_deleted == 1

    with session_factory() as db:
        remaining = db.get(Run, active_id)
        assert remaining is not None
        assert remaining.status == SyncStatus.RUNNING
