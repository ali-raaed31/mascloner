"""Characterization tests for scheduler lifecycle and configuration endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.harness.installation import InstallationRoot


def test_schedule_read_default(fresh_client: TestClient, isolated_fresh_install: InstallationRoot):
    """Verify reading schedule returns defaults or current job state."""
    response = fresh_client.get("/schedule")
    assert response.status_code == 200
    data = response.json()
    assert "interval_min" in data
    assert "jitter_sec" in data
    assert "interval" in data
    assert data["interval_min"] == 5
    assert data["jitter_sec"] == 20


def test_schedule_update(fresh_client: TestClient, isolated_fresh_install: InstallationRoot):
    """Verify updating schedule sets new interval and persists to SQLite ConfigKV."""
    payload = {"interval_min": 30, "jitter_sec": 45}
    response = fresh_client.post("/schedule", json=payload)
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Re-read schedule
    get_res = fresh_client.get("/schedule")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["interval_min"] == 30
    assert data["jitter_sec"] == 45


def test_schedule_start_and_stop_lifecycle(fresh_client: TestClient, isolated_fresh_install: InstallationRoot):
    """Verify starting and stopping scheduler via API."""
    # Start scheduler
    start_res = fresh_client.post("/schedule/start")
    assert start_res.status_code == 200
    assert start_res.json()["success"] is True

    # Stop scheduler
    stop_res = fresh_client.post("/schedule/stop")
    assert stop_res.status_code == 200
    assert stop_res.json()["success"] is True
