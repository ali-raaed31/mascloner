"""Tests for runs and events API endpoints."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.models import FileEvent, Run


class TestRunsEndpoint:
    """Tests for the runs endpoint."""

    def test_get_runs_empty_initially(self, test_client: TestClient):
        """Runs list should be empty initially."""
        response = test_client.get("/runs")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_get_runs_with_data(self, test_client: TestClient, test_session: Session):
        """Should return runs when they exist."""
        # Create a test run
        run = Run(
            status="success",
            num_added=5,
            num_updated=2,
            bytes_transferred=1024,
            errors=0,
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
        )
        test_session.add(run)
        test_session.commit()

        response = test_client.get("/runs")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1

    def test_get_runs_with_limit(self, test_client: TestClient, test_session: Session):
        """Should respect limit parameter."""
        # Create multiple runs
        for i in range(5):
            run = Run(
                status="success",
                num_added=i,
                num_updated=0,
                bytes_transferred=0,
                errors=0,
                started_at=datetime.now(timezone.utc),
            )
            test_session.add(run)
        test_session.commit()

        response = test_client.get("/runs?limit=3")
        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 3


class TestEventsEndpoint:
    """Tests for the events endpoint."""

    def test_get_events_empty_initially(self, test_client: TestClient):
        """Events list should be empty initially."""
        response = test_client.get("/events")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_get_events_with_data(self, test_client: TestClient, test_session: Session):
        """Should return events when they exist."""
        # Create a run first
        run = Run(
            status="success",
            started_at=datetime.now(timezone.utc),
        )
        test_session.add(run)
        test_session.commit()
        test_session.refresh(run)

        # Create test event
        event = FileEvent(
            run_id=run.id,
            action="added",
            file_path="test/file.txt",
            file_size=1024,
            timestamp=datetime.now(timezone.utc),
        )
        test_session.add(event)
        test_session.commit()

        response = test_client.get("/events")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1


class TestRunEventsEndpoint:
    """Tests for the run-specific events endpoint."""

    def test_get_run_events_not_found(self, test_client: TestClient):
        """Should return 404 for non-existent run."""
        response = test_client.get("/runs/99999/events")
        assert response.status_code == 404

    def test_get_run_events_with_data(
        self, test_client: TestClient, test_session: Session
    ):
        """Should return events for a specific run."""
        # Create a run
        run = Run(
            status="success",
            started_at=datetime.now(timezone.utc),
        )
        test_session.add(run)
        test_session.commit()
        test_session.refresh(run)

        # Create events for this run
        for i in range(3):
            event = FileEvent(
                run_id=run.id,
                action="added",
                file_path=f"test/file{i}.txt",
                file_size=1024 * (i + 1),
                timestamp=datetime.now(timezone.utc),
            )
            test_session.add(event)
        test_session.commit()

        response = test_client.get(f"/runs/{run.id}/events")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3


class TestTriggerSync:
    """Tests for the trigger sync endpoint."""

    def test_trigger_sync(self, test_client: TestClient):
        """Should trigger a sync successfully."""
        response = test_client.post("/runs")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "triggered" in data["message"].lower()

