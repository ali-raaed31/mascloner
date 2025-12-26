"""Tests for schedule API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class TestScheduleEndpoint:
    """Tests for the schedule endpoint."""

    def test_get_schedule(self, test_client: TestClient):
        """Should return current schedule configuration."""
        response = test_client.get("/schedule")
        assert response.status_code == 200
        data = response.json()

        # Check expected fields
        assert "interval_min" in data
        assert "jitter_sec" in data
        assert isinstance(data["interval_min"], int)
        assert isinstance(data["jitter_sec"], int)

    def test_update_schedule_valid(self, test_client: TestClient):
        """Should update schedule with valid values."""
        schedule_data = {"interval_min": 10, "jitter_sec": 30}
        response = test_client.post("/schedule", json=schedule_data)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_update_schedule_invalid_interval(self, test_client: TestClient):
        """Should reject invalid interval values."""
        # Interval too low
        response = test_client.post("/schedule", json={"interval_min": 0, "jitter_sec": 20})
        assert response.status_code == 422

        # Interval too high
        response = test_client.post(
            "/schedule", json={"interval_min": 10000, "jitter_sec": 20}
        )
        assert response.status_code == 422

    def test_update_schedule_invalid_jitter(self, test_client: TestClient):
        """Should reject invalid jitter values."""
        # Negative jitter
        response = test_client.post(
            "/schedule", json={"interval_min": 5, "jitter_sec": -1}
        )
        assert response.status_code == 422


class TestSchedulerControl:
    """Tests for scheduler start/stop endpoints."""

    def test_start_scheduler(self, test_client: TestClient):
        """Should start the scheduler."""
        response = test_client.post("/schedule/start")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_stop_scheduler(self, test_client: TestClient):
        """Should stop the scheduler."""
        response = test_client.post("/schedule/stop")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

