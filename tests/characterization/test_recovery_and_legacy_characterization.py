"""Characterization tests for startup recovery, legacy databases, and status preservation."""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

import app.api.db as api_db
from app.api.models import FileEvent, Run
from tests.harness.assertions import assert_no_secrets_leaked
from tests.harness.installation import InstallationRoot


def test_legacy_database_startup_and_status_preservation(
    legacy_client: TestClient,
    isolated_legacy_install: InstallationRoot,
):
    """Verify legacy database with legacy statuses is read properly on startup."""
    # 1. GET /status on legacy install
    status_res = legacy_client.get("/status")
    assert status_res.status_code == 200
    status_data = status_res.json()
    assert status_data["database_ok"] is True
    assert status_data["total_runs"] >= 5

    # 2. GET /runs lists legacy runs and preserves legacy statuses
    runs_res = legacy_client.get("/runs?limit=10")
    assert runs_res.status_code == 200
    runs = runs_res.json()
    assert len(runs) >= 5

    statuses = {r["status"] for r in runs}
    # Verified canonical statuses after migration and startup recovery:
    assert "completed" in statuses
    assert "failed" in statuses
    assert "aborted" in statuses

    # Find the completed run (migrated from legacy success)
    completed_run = next(r for r in runs if r["status"] == "completed")
    assert completed_run["num_added"] == 15
    assert completed_run["num_updated"] == 2
    assert completed_run["bytes_transferred"] == 1048576

    # 3. GET /runs/{id}/events loads legacy file events
    events_res = legacy_client.get(f"/runs/{completed_run['id']}/events")
    assert events_res.status_code == 200
    events = events_res.json()
    assert len(events) == 2
    actions = {e["action"] for e in events}
    assert "added" in actions
    assert "updated" in actions

    # 4. GET /events loads recent file events across all runs
    all_events_res = legacy_client.get("/events")
    assert all_events_res.status_code == 200
    all_events = all_events_res.json()
    assert len(all_events) >= 3

    # Secret assertions: No secrets leaked in /runs or /status or /events
    secrets_to_check = [
        isolated_legacy_install.fernet_key,
        "legacy_secret_password_456",
        "obscured_legacy_pass_999",
        "ya29.legacy_token_123",
        "1//legacy_refresh_abc",
    ]
    assert_no_secrets_leaked(status_data, secrets_to_check)
    assert_no_secrets_leaked(runs, secrets_to_check)
    assert_no_secrets_leaked(all_events, secrets_to_check)


def test_legacy_database_direct_orm_queries(isolated_legacy_install: InstallationRoot):
    """Verify legacy schema and data integrity via direct SQLAlchemy queries."""
    with api_db.SessionLocal() as session:
        runs = session.execute(select(Run)).scalars().all()
        assert len(runs) >= 5

        events = session.execute(select(FileEvent)).scalars().all()
        assert len(events) >= 3
