"""Hermetic parity and lifecycle tests for scheduled and manual SyncExecutor integration (Issue #12)."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient

from app.api.db import get_db_session
from app.api.main import app
from app.api.models import Run, SyncStatus
from app.api.scheduler import SyncScheduler, sync_job
from app.configuration import Configuration, ScheduleSettings
from app.configuration.lease import ConfigurationLeaseError, get_process_lease
from app.execution import SyncExecutor
from tests.harness.fake_rclone import FakeRcloneScenario
from tests.harness.installation import InstallationRoot


@pytest.fixture
def isolated_install() -> Generator[InstallationRoot, None, None]:
    """Create isolated test environment."""
    root = InstallationRoot()
    root.create_fresh()

    # Pre-populate valid configured remotes
    conf_content = (
        "[gdrive]\n"
        "type = drive\n"
        "scope = drive.readonly\n"
        'token = {"access_token":"tok_valid_123"}\n\n'
        "[ncwebdav]\n"
        "type = webdav\n"
        "vendor = nextcloud\n"
        "url = https://nextcloud.example.local/remote.php/webdav/\n"
        "user = testuser\n"
        "pass = obscured_pass_secret\n"
    )
    root.rclone_conf_path.write_text(conf_content, encoding="utf-8")

    try:
        yield root
    finally:
        SyncExecutor.reset_instance()


@pytest.fixture
def executor(isolated_install: InstallationRoot):
    """Ensure SyncExecutor singleton is reset before and after each test."""
    SyncExecutor.reset_instance()
    inst = SyncExecutor.get_instance(
        session_factory=get_db_session,
        rclone_conf_path=isolated_install.rclone_conf_path,
        rclone_bin=isolated_install.fake_rclone.bin_path,
        log_dir=isolated_install.log_dir,
    )
    yield inst
    inst.shutdown(timeout=2.0)
    SyncExecutor.reset_instance()


def test_scheduled_run_lifecycle_and_parity(executor: SyncExecutor, isolated_install: InstallationRoot):
    """Scheduled trigger enters SyncExecutor and transitions PENDING -> RUNNING -> COMPLETED."""
    scenario = FakeRcloneScenario(
        name="scheduled_success",
        events_to_emit=[
            {
                "level": "info",
                "msg": "Copied (new)",
                "object": "scheduled_doc.txt",
                "size": 512,
                "time": "2026-09-13T21:00:00Z",
            }
        ],
    )
    isolated_install.fake_rclone.set_scenario(scenario)

    res = executor.trigger_scheduled_run(wait=True)
    assert res.accepted is True
    assert res.run_id is not None
    assert res.status == SyncStatus.COMPLETED

    with get_db_session() as db:
        run = db.get(Run, res.run_id)
        assert run is not None
        assert run.status == SyncStatus.COMPLETED
        assert run.started_at is not None
        assert run.finished_at is not None
        assert run.num_added == 1
        assert run.errors == 0


def test_scheduled_job_callback_delegates_to_executor(executor: SyncExecutor, isolated_install: InstallationRoot):
    """scheduler.sync_job() executes directly through SyncExecutor."""
    scenario = FakeRcloneScenario(
        name="sync_job_test",
        events_to_emit=[
            {
                "level": "info",
                "msg": "Copied (new)",
                "object": "job_file.txt",
                "size": 256,
                "time": "2026-09-13T21:00:00Z",
            }
        ],
    )
    isolated_install.fake_rclone.set_scenario(scenario)

    result = sync_job(wait=True)
    assert result is not None
    assert result.accepted is True
    assert result.status == SyncStatus.COMPLETED

    with get_db_session() as db:
        run = db.get(Run, result.run_id)
        assert run is not None
        assert run.status == SyncStatus.COMPLETED


def test_overlap_scheduled_while_manual_active(executor: SyncExecutor, isolated_install: InstallationRoot):
    """A scheduled trigger while a manual run is active creates a SKIPPED record."""
    scenario = FakeRcloneScenario(name="long_manual", sleep_seconds=1.5)
    isolated_install.fake_rclone.set_scenario(scenario)

    # 1. Start manual run
    manual_res = executor.trigger_manual_run(wait=False)
    assert manual_res.accepted is True

    # 2. Trigger scheduled run while manual is active
    sched_res = executor.trigger_scheduled_run(wait=False)
    assert sched_res.accepted is False
    assert sched_res.status == SyncStatus.SKIPPED
    assert sched_res.run_id is not None

    with get_db_session() as db:
        skipped_run = db.get(Run, sched_res.run_id)
        assert skipped_run is not None
        assert skipped_run.status == SyncStatus.SKIPPED
        assert "skipped" in (skipped_run.message or "").lower()

    # Await manual completion
    start = time.time()
    while executor.is_running() and (time.time() - start < 10.0):
        time.sleep(0.05)


def test_overlap_manual_while_scheduled_active(executor: SyncExecutor, isolated_install: InstallationRoot):
    """A manual trigger while a scheduled run is active creates a SKIPPED record."""
    scenario = FakeRcloneScenario(name="long_scheduled", sleep_seconds=1.5)
    isolated_install.fake_rclone.set_scenario(scenario)

    # 1. Start scheduled run
    sched_res = executor.trigger_scheduled_run(wait=False)
    assert sched_res.accepted is True

    # 2. Trigger manual run while scheduled is active
    manual_res = executor.trigger_manual_run(wait=False)
    assert manual_res.accepted is False
    assert manual_res.status == SyncStatus.SKIPPED
    assert manual_res.run_id is not None

    with get_db_session() as db:
        skipped_run = db.get(Run, manual_res.run_id)
        assert skipped_run is not None
        assert skipped_run.status == SyncStatus.SKIPPED
        assert "skipped" in (skipped_run.message or "").lower()

    # Await scheduled completion
    start = time.time()
    while executor.is_running() and (time.time() - start < 10.0):
        time.sleep(0.05)


def test_schedule_pause_does_not_abort_active_sync(executor: SyncExecutor, isolated_install: InstallationRoot):
    """Pausing the scheduler disables future triggers without terminating an active SyncRun."""
    scenario = FakeRcloneScenario(name="pause_test_run", sleep_seconds=1.0)
    isolated_install.fake_rclone.set_scenario(scenario)

    # Start scheduled run
    res = executor.trigger_scheduled_run(wait=False)
    assert res.accepted is True
    active_id = res.run_id

    # Client pauses schedule
    client = TestClient(app)
    pause_res = client.post("/schedule/stop")
    assert pause_res.status_code == 200
    assert pause_res.json()["success"] is True

    # Verify active run is STILL running
    assert executor.is_running() is True
    assert executor.get_active_run_id() == active_id

    # Wait for natural completion
    start = time.time()
    while executor.is_running() and (time.time() - start < 10.0):
        time.sleep(0.05)

    with get_db_session() as db:
        run = db.get(Run, active_id)
        assert run.status == SyncStatus.COMPLETED


def test_executor_graceful_shutdown_terminates_active_run_cleanly(
    executor: SyncExecutor, isolated_install: InstallationRoot
):
    """Shutdown aborts active run within timeout and persists terminal ABORTED state."""
    scenario = FakeRcloneScenario(name="hanging_run", sleep_seconds=10.0)
    isolated_install.fake_rclone.set_scenario(scenario)

    res = executor.trigger_scheduled_run(wait=False)
    assert res.accepted is True
    active_id = res.run_id

    # Wait until process is active
    start = time.time()
    while not executor.is_running() and (time.time() - start < 2.0):
        time.sleep(0.02)

    # Execute bounded shutdown
    shutdown_start = time.time()
    executor.shutdown(timeout=2.0)
    duration = time.time() - shutdown_start

    assert duration < 5.0
    assert executor.is_running() is False

    # Verify run is marked ABORTED, not RUNNING
    with get_db_session() as db:
        run = db.get(Run, active_id)
        assert run.status == SyncStatus.ABORTED
        assert "shutdown" in (run.message or "").lower() or "abort" in (run.message or "").lower()

    # Further triggers after shutdown must be rejected
    rejected = executor.trigger_manual_run()
    assert rejected.accepted is False
    assert rejected.status == SyncStatus.SKIPPED


def test_scheduled_run_live_snapshot_and_abort(executor: SyncExecutor, isolated_install: InstallationRoot):
    """Live snapshot, current-run endpoint, and abort work identically for scheduled runs."""
    scenario = FakeRcloneScenario(name="abortable_scheduled", sleep_seconds=5.0)
    isolated_install.fake_rclone.set_scenario(scenario)

    res = executor.trigger_scheduled_run(wait=False)
    assert res.accepted is True
    run_id = res.run_id

    client = TestClient(app)

    # Check GET /runs/current returns live snapshot
    time.sleep(0.1)
    curr_res = client.get("/runs/current")
    assert curr_res.status_code == 200
    curr_data = curr_res.json()
    assert curr_data is not None
    assert curr_data["id"] == run_id
    assert curr_data["status"] in (SyncStatus.PENDING, SyncStatus.RUNNING)

    # Abort via POST /runs/{id}/stop
    stop_res = client.post(f"/runs/{run_id}/stop")
    assert stop_res.status_code == 200
    assert stop_res.json()["success"] is True

    # Wait for abort to finish
    start = time.time()
    while executor.is_running() and (time.time() - start < 10.0):
        time.sleep(0.05)

    with get_db_session() as db:
        run = db.get(Run, run_id)
        assert run.status == SyncStatus.ABORTED


def test_abort_and_completion_race_yields_single_terminal_state(
    executor: SyncExecutor, isolated_install: InstallationRoot
):
    """Concurrent abort requests on exiting/completed process yield single deterministic state."""
    scenario = FakeRcloneScenario(name="quick_abort_race", sleep_seconds=0.2)
    isolated_install.fake_rclone.set_scenario(scenario)

    res = executor.trigger_scheduled_run(wait=False)
    assert res.accepted is True
    run_id = res.run_id

    # Fire multiple concurrent abort requests
    res1 = executor.request_abort(run_id)
    res2 = executor.request_abort(run_id)

    # Wait for execution to settle
    start = time.time()
    while executor.is_running() and (time.time() - start < 10.0):
        time.sleep(0.05)

    with get_db_session() as db:
        run = db.get(Run, run_id)
        assert run.status in (SyncStatus.ABORTED, SyncStatus.COMPLETED)
        assert run.finished_at is not None
        # Must not remain in RUNNING or PENDING
        assert run.status not in (SyncStatus.PENDING, SyncStatus.RUNNING)
