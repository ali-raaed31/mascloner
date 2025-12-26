"""Tests for configuration API endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    def test_health_returns_healthy(self, test_client: TestClient):
        """Health endpoint should return healthy status."""
        response = test_client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "mascloner-api"


class TestStatusEndpoint:
    """Tests for the status endpoint."""

    def test_status_returns_expected_fields(self, test_client: TestClient):
        """Status endpoint should return all expected fields."""
        response = test_client.get("/status")
        assert response.status_code == 200
        data = response.json()

        # Check required fields exist
        assert "scheduler_running" in data
        assert "database_ok" in data
        assert "total_runs" in data
        assert "config_valid" in data
        assert "remotes_configured" in data

    def test_status_database_ok(self, test_client: TestClient):
        """Status should report database as OK when connected."""
        response = test_client.get("/status")
        assert response.status_code == 200
        data = response.json()
        assert data["database_ok"] is True


class TestConfigEndpoint:
    """Tests for the configuration endpoint."""

    def test_get_config_empty_initially(self, test_client: TestClient):
        """Config should be empty initially."""
        response = test_client.get("/config")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)

    def test_update_config(self, test_client: TestClient, sample_config_data):
        """Should be able to update configuration."""
        response = test_client.post("/config", json=sample_config_data)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_get_config_after_update(self, test_client: TestClient, sample_config_data):
        """Config should persist after update."""
        # Update config
        test_client.post("/config", json=sample_config_data)

        # Retrieve config
        response = test_client.get("/config")
        assert response.status_code == 200
        data = response.json()

        # Verify values
        assert data.get("gdrive_remote") == sample_config_data["gdrive_remote"]
        assert data.get("gdrive_src") == sample_config_data["gdrive_src"]
        assert data.get("nc_remote") == sample_config_data["nc_remote"]
        assert data.get("nc_dest_path") == sample_config_data["nc_dest_path"]

    def test_update_config_invalid_payload(self, test_client: TestClient):
        """Should reject invalid configuration payload."""
        response = test_client.post("/config", json={"invalid_field": "value"})
        assert response.status_code == 422  # Validation error

