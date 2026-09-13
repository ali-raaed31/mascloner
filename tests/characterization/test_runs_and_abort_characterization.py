"""Characterization tests for manual/scheduled sync runs, logs, events, and graceful abort."""

from __future__ import annotations

import threading
import time
from fastapi.testclient import TestClient
from sqlalchemy import desc, select

import app.api.db as api_db
from app.api.models import FileEvent, Run
from app.api.scheduler import sync_job
from tests.harness.assertions import assert_no_secrets_leaked
from tests.harness.fake_rclone import FakeRcloneScenario
from tests.harness.installation import InstallationRoot


def test_sync_job_success_lifecycle(fresh_client: TestClient, isolated_fresh_install: InstallationRoot):
    """Verify sync_job creates Run record, records FileEvents, and updates metrics."""
    isolated_fresh_install.fake_rclone.set_scenario(FakeRcloneScenario(name="success"))

    # Execute sync_job directly
    sync_job()

    with api_db.SessionLocal() as session:
        last_run = session.execute(select(Run).order_by(desc(Run.id))).scalars().first()
        assert last_run is not None
        assert last_run.status == "completed"
        assert last_run.bytes_transferred == 3072
        assert last_run.num_added == 2
        assert last_run.num_updated == 1
        run_id = last_run.id

        events = (
            session.execute(select(FileEvent).where(FileEvent.run_id == run_id))
            .scalars()
            .all()
        )
        assert len(events) >= 2

    # Query via API endpoints
    # 1. GET /runs
    runs_res = fresh_client.get("/runs")
    assert runs_res.status_code == 200
    runs_data = runs_res.json()
    assert len(runs_data) >= 1
    assert runs_data[0]["id"] == run_id
    assert runs_data[0]["status"] == "completed"

    # 2. GET /runs/{run_id}/logs
    logs_res = fresh_client.get(f"/runs/{run_id}/logs")
    assert logs_res.status_code == 200
    logs_data = logs_res.json()
    assert "logs" in logs_data
    assert len(logs_data["logs"]) > 0

    # 3. GET /runs/{run_id}/events
    events_res = fresh_client.get(f"/runs/{run_id}/events")
    assert events_res.status_code == 200
    events_data = events_res.json()
    assert len(events_data) >= 2

    # 4. GET /events
    all_events_res = fresh_client.get("/events")
    assert all_events_res.status_code == 200
    all_events = all_events_res.json()
    assert len(all_events) >= 2

    # Secret assertions: Fernet key not leaked in logs or events
    assert_no_secrets_leaked(logs_data, [isolated_fresh_install.fernet_key])
    assert_no_secrets_leaked(events_data, [isolated_fresh_install.fernet_key])


def test_graceful_abort_lifecycle(fresh_client: TestClient, isolated_fresh_install: InstallationRoot):
    """Verify graceful abort flow: active snapshot, stop request, and stopped status."""
    isolated_fresh_install.fake_rclone.set_scenario(FakeRcloneScenario(name="cancellation"))

    # Launch sync_job in a background thread
    job_thread = threading.Thread(target=sync_job, daemon=True)
    job_thread.start()

    # Wait for run to appear in running status
    active_run_id = None
    for _ in range(50):
        current_res = fresh_client.get("/runs/current")
        if current_res.status_code == 200 and current_res.json() is not None:
            active_run_id = current_res.json()["id"]
            break
        time.sleep(0.05)

    assert active_run_id is not None

    # Request graceful stop
    stop_res = fresh_client.post(f"/runs/{active_run_id}/stop")
    assert stop_res.status_code == 200
    assert stop_res.json()["success"] is True

    job_thread.join(timeout=5.0)

    # Verify run completed with 'stopped' status
    with api_db.SessionLocal() as session:
        stopped_run = session.execute(
            select(Run).where(Run.id == active_run_id)
        ).scalars().first()
        assert stopped_run is not None
        assert stopped_run.status == "aborted"
