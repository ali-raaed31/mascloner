"""TDD tests for Issue #5: Persist Schedule enabled state, interval, and jitter.

Verifies:
1. Schema migration seeds schedule_enabled="true" for legacy and fresh installations.
2. Schedule configuration validation (interval 1..1440 min, jitter 0..300 sec, jitter < interval).
3. Reversible Alembic downgrade and idempotent retry.
4. Process restart retains paused/running state.
5. In-process scheduler reconstructs exactly one job when enabled, zero when disabled.
6. Start/stop calls are idempotent and reconcile runtime state.
7. Scheduler-registration failure rolls back DB and does not falsely report success.
8. API /status and /schedule display consistent metadata.
9. Tests run with controlled time without wall-clock waits.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.models import Base, ConfigKV
from app.configuration import Configuration, ScheduleSettings
from tests.harness.installation import InstallationRoot


@pytest.fixture
def test_alembic_cfg() -> Config:
    """Provide Alembic Config pointing to repo alembic.ini."""
    repo_root = Path(__file__).resolve().parent.parent
    ini_path = repo_root / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
    return cfg


def test_schedule_schema_upgrade_seeds_legacy_install(
    isolated_legacy_install: InstallationRoot,
    test_alembic_cfg: Config,
    monkeypatch: pytest.MonkeyPatch,
):
    """Upgrading an existing installation seeds schedule_enabled='true' to avoid disabling sync."""
    monkeypatch.setenv("MASCLONER_DB_PATH", str(isolated_legacy_install.db_path))
    monkeypatch.setenv("MASCLONER_BASE_DIR", str(isolated_legacy_install.base_dir))

    # Stamp at previous revision then run upgrade to head
    command.stamp(test_alembic_cfg, "20250101_000001")
    command.upgrade(test_alembic_cfg, "head")

    engine = create_engine(f"sqlite:///{isolated_legacy_install.db_path}")
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        rows = {row.key: row for row in session.execute(select(ConfigKV)).scalars().all()}

        assert "schedule_enabled" in rows
        assert rows["schedule_enabled"].value == "true"
        assert rows["schedule_enabled"].provenance in ("default", "imported_legacy")

        assert "interval_min" in rows
        assert rows["interval_min"].value in ("5", "10", "30", "60")  # Documented range

        assert "jitter_sec" in rows
        assert rows["jitter_sec"].value in ("20", "30", "0")


def test_schedule_schema_upgrade_seeds_fresh_install(
    temp_dir: Path,
    test_alembic_cfg: Config,
    monkeypatch: pytest.MonkeyPatch,
):
    """Fresh installations receive documented schedule defaults (enabled=true, interval=5, jitter=20)."""
    db_file = temp_dir / "fresh_schedule.db"
    monkeypatch.setenv("MASCLONER_DB_PATH", str(db_file))
    monkeypatch.setenv("MASCLONER_BASE_DIR", str(temp_dir))

    command.upgrade(test_alembic_cfg, "head")

    engine = create_engine(f"sqlite:///{db_file}")
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        rows = {row.key: row for row in session.execute(select(ConfigKV)).scalars().all()}

        assert "schedule_enabled" in rows
        assert rows["schedule_enabled"].value == "true"
        assert rows["schedule_enabled"].provenance == "default"

        assert "interval_min" in rows
        assert rows["interval_min"].value == "5"
        assert rows["interval_min"].provenance == "default"

        assert "jitter_sec" in rows
        assert rows["jitter_sec"].value == "20"
        assert rows["jitter_sec"].provenance == "default"


def test_schedule_migration_downgrade_and_retry(
    temp_dir: Path,
    test_alembic_cfg: Config,
    monkeypatch: pytest.MonkeyPatch,
):
    """Downgrade to 20250101_000001 removes schedule keys; re-upgrading succeeds idempotently."""
    db_file = temp_dir / "schedule_downgrade.db"
    monkeypatch.setenv("MASCLONER_DB_PATH", str(db_file))
    monkeypatch.setenv("MASCLONER_BASE_DIR", str(temp_dir))

    # 1. Upgrade to head
    command.upgrade(test_alembic_cfg, "head")

    engine = create_engine(f"sqlite:///{db_file}")
    SessionLocal = sessionmaker(bind=engine)
    with SessionLocal() as session:
        rows = {row.key: row for row in session.execute(select(ConfigKV)).scalars().all()}
        assert "schedule_enabled" in rows

    # 2. Downgrade to 20250101_000001
    command.downgrade(test_alembic_cfg, "20250101_000001")

    with SessionLocal() as session:
        rows = {row.key: row for row in session.execute(select(ConfigKV)).scalars().all()}
        assert "schedule_enabled" not in rows

    # 3. Upgrade to head again
    command.upgrade(test_alembic_cfg, "head")
    with SessionLocal() as session:
        rows = {row.key: row for row in session.execute(select(ConfigKV)).scalars().all()}
        assert "schedule_enabled" in rows


def test_schedule_settings_cadence_validation():
    """ScheduleSettings validates cadence boundaries (interval 1..1440, jitter 0..300, jitter < interval)."""
    from pydantic import ValidationError

    # Valid settings
    valid = ScheduleSettings(enabled=True, interval_min=15, jitter_sec=45)
    assert valid.enabled is True
    assert valid.interval_min == 15
    assert valid.jitter_sec == 45

    # Invalid interval
    with pytest.raises((ValidationError, ValueError)):
        ScheduleSettings(interval_min=0, jitter_sec=0)

    with pytest.raises((ValidationError, ValueError)):
        ScheduleSettings(interval_min=1441, jitter_sec=0)

    # Invalid jitter
    with pytest.raises((ValidationError, ValueError)):
        ScheduleSettings(interval_min=5, jitter_sec=-1)

    with pytest.raises((ValidationError, ValueError)):
        ScheduleSettings(interval_min=5, jitter_sec=301)

    # Jitter exceeding interval (e.g. 1 min interval with 60s jitter)
    with pytest.raises((ValidationError, ValueError)):
        ScheduleSettings(interval_min=1, jitter_sec=60)

    with pytest.raises((ValidationError, ValueError)):
        ScheduleSettings(interval_min=1, jitter_sec=120)


def test_configuration_schedule_round_trip(isolated_fresh_install: InstallationRoot):
    """Configuration facade loads and saves ScheduleSettings durably in SQLite."""
    engine = create_engine(f"sqlite:///{isolated_fresh_install.db_path}")
    SessionLocal = sessionmaker(bind=engine)

    cfg = Configuration(session_factory=SessionLocal)

    # Initial default from DB
    sched = cfg.get_schedule()
    assert sched.enabled is True
    assert sched.interval_min == 5
    assert sched.jitter_sec == 20

    # Persist disabled schedule with custom timing
    cfg.set_schedule(ScheduleSettings(enabled=False, interval_min=45, jitter_sec=100))

    # Re-read with a new Configuration instance
    cfg2 = Configuration(session_factory=SessionLocal)
    sched2 = cfg2.get_schedule()
    assert sched2.enabled is False
    assert sched2.interval_min == 45
    assert sched2.jitter_sec == 100


def test_scheduler_startup_reconstructs_job_when_enabled(
    isolated_fresh_install: InstallationRoot,
    monkeypatch: pytest.MonkeyPatch,
):
    """Startup reconstructs exactly one scheduled job when enabled in SQLite."""
    from app.api.scheduler import get_scheduler, start_scheduler, stop_scheduler

    monkeypatch.setenv("MASCLONER_DB_PATH", str(isolated_fresh_install.db_path))
    monkeypatch.setenv("MASCLONER_BASE_DIR", str(isolated_fresh_install.base_dir))

    scheduler = get_scheduler()
    try:
        # Start scheduler
        success = start_scheduler()
        assert success is True

        # Exactly one sync job registered
        job = scheduler.scheduler.get_job("sync")
        assert job is not None
        assert len(scheduler.scheduler.get_jobs()) == 1
        assert scheduler.is_enabled() is True
    finally:
        stop_scheduler()


def test_scheduler_startup_reconstructs_no_job_when_disabled(
    isolated_fresh_install: InstallationRoot,
    monkeypatch: pytest.MonkeyPatch,
):
    """Startup reconstructs zero scheduled jobs when disabled in SQLite."""
    from app.api.scheduler import get_scheduler, start_scheduler, stop_scheduler

    monkeypatch.setenv("MASCLONER_DB_PATH", str(isolated_fresh_install.db_path))
    monkeypatch.setenv("MASCLONER_BASE_DIR", str(isolated_fresh_install.base_dir))

    engine = create_engine(f"sqlite:///{isolated_fresh_install.db_path}")
    SessionLocal = sessionmaker(bind=engine)
    cfg = Configuration(session_factory=SessionLocal)
    cfg.set_schedule(ScheduleSettings(enabled=False, interval_min=10, jitter_sec=20))

    scheduler = get_scheduler()
    try:
        success = start_scheduler()
        assert success is True

        # Zero sync jobs registered because schedule is disabled
        job = scheduler.scheduler.get_job("sync")
        assert job is None
        assert len(scheduler.scheduler.get_jobs()) == 0
        assert scheduler.is_enabled() is False
    finally:
        stop_scheduler()


def test_api_schedule_full_lifecycle_and_restart(
    fresh_client: TestClient,
    isolated_fresh_install: InstallationRoot,
    monkeypatch: pytest.MonkeyPatch,
):
    """Pause/resume survives restart, updates SQLite, and surfaces consistent next-run info."""
    # 1. Initial status: enabled=True, scheduler_running=True
    get_res = fresh_client.get("/schedule")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["enabled"] is True
    assert data["interval_min"] == 5
    assert data["jitter_sec"] == 20
    assert data["next_run_time"] is not None

    status_res = fresh_client.get("/status")
    assert status_res.status_code == 200
    assert status_res.json()["scheduler_running"] is True
    assert status_res.json()["next_run"] is not None

    # 2. Update interval/jitter with validation
    # Invalid cadence (jitter >= interval * 60)
    inv_res = fresh_client.post("/schedule", json={"interval_min": 1, "jitter_sec": 60})
    assert inv_res.status_code == 422

    # Valid update
    upd_res = fresh_client.post("/schedule", json={"interval_min": 15, "jitter_sec": 45})
    assert upd_res.status_code == 200
    assert upd_res.json()["success"] is True

    get_upd = fresh_client.get("/schedule")
    assert get_upd.json()["interval_min"] == 15
    assert get_upd.json()["jitter_sec"] == 45

    # 3. Stop / Pause scheduler
    stop_res = fresh_client.post("/schedule/stop")
    assert stop_res.status_code == 200
    assert stop_res.json()["success"] is True

    # Repeated stop is idempotent
    stop_res2 = fresh_client.post("/schedule/stop")
    assert stop_res2.status_code == 200

    # Status reflects stopped state
    sched_stopped = fresh_client.get("/schedule").json()
    assert sched_stopped["enabled"] is False
    assert sched_stopped["next_run_time"] is None

    status_stopped = fresh_client.get("/status").json()
    assert status_stopped["scheduler_running"] is False
    assert status_stopped["next_run"] is None

    # 4. Restart simulation: recreate client and check that schedule remains disabled
    from app.api.dependencies import reset_dependencies
    reset_dependencies()

    get_after_restart = fresh_client.get("/schedule").json()
    assert get_after_restart["enabled"] is False
    assert get_after_restart["next_run_time"] is None

    # 5. Start / Resume scheduler
    start_res = fresh_client.post("/schedule/start")
    assert start_res.status_code == 200
    assert start_res.json()["success"] is True

    # Repeated start is idempotent
    start_res2 = fresh_client.post("/schedule/start")
    assert start_res2.status_code == 200

    sched_resumed = fresh_client.get("/schedule").json()
    assert sched_resumed["enabled"] is True
    assert sched_resumed["next_run_time"] is not None


def test_schedule_registration_failure_rolls_back(
    fresh_client: TestClient,
    isolated_fresh_install: InstallationRoot,
):
    """If scheduler registration fails, API returns an error and does not mutate durable state."""
    from app.api.dependencies import get_scheduler

    scheduler = fresh_client.app.dependency_overrides.get(get_scheduler)
    if not scheduler:
        scheduler = get_scheduler()

    # Initial state
    orig_sched = fresh_client.get("/schedule").json()
    orig_interval = orig_sched["interval_min"]

    # Mock add_sync_job to raise/fail
    with patch.object(scheduler, "add_sync_job", side_effect=RuntimeError("Scheduler registration failed")):
        res = fresh_client.post("/schedule", json={"interval_min": 100, "jitter_sec": 30})
        assert res.status_code == 500
        assert "failed" in str(res.json()).lower()

    # Verify durable state was NOT modified to 100
    after_res = fresh_client.get("/schedule").json()
    assert after_res["interval_min"] == orig_interval


def test_schedule_rapid_repeated_requests_idempotent(fresh_client: TestClient):
    """Repeated start and stop calls are idempotent without duplicate jobs."""
    # Rapid repeated stops
    for _ in range(3):
        res = fresh_client.post("/schedule/stop")
        assert res.status_code == 200
        assert res.json()["success"] is True

    sched_stopped = fresh_client.get("/schedule").json()
    assert sched_stopped["enabled"] is False
    assert sched_stopped["next_run_time"] is None

    # Rapid repeated starts
    for _ in range(3):
        res = fresh_client.post("/schedule/start")
        assert res.status_code == 200
        assert res.json()["success"] is True

    sched_started = fresh_client.get("/schedule").json()
    assert sched_started["enabled"] is True
    assert sched_started["next_run_time"] is not None
