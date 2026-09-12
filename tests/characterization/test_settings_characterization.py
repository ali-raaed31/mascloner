"""Characterization tests for settings reads/writes and configuration flows."""

from __future__ import annotations

from fastapi.testclient import TestClient
from cryptography.fernet import Fernet

from app.api.config import ConfigManager
from tests.harness.assertions import assert_no_secrets_leaked
from tests.harness.installation import InstallationRoot


def test_status_endpoint_flow(fresh_client: TestClient, isolated_fresh_install: InstallationRoot):
    """Verify /status endpoint returns operational status and system metrics."""
    response = fresh_client.get("/status")
    assert response.status_code == 200
    data = response.json()
    assert "scheduler_running" in data
    assert "database_ok" in data
    assert data["database_ok"] is True
    assert "total_runs" in data
    assert "config_valid" in data
    assert "remotes_configured" in data


def test_config_read_and_update_flow(fresh_client: TestClient, isolated_fresh_install: InstallationRoot):
    """Verify /config endpoint reads and updates SQLite ConfigKV pairs."""
    # Initially empty in fresh database
    initial_res = fresh_client.get("/config")
    assert initial_res.status_code == 200

    # Update with valid ConfigRequest
    payload = {
        "gdrive_remote": "gdrive",
        "gdrive_src": "UpdatedSourceFolder",
        "nc_remote": "ncwebdav",
        "nc_dest_path": "UpdatedDestinationFolder",
    }

    response = fresh_client.post("/config", json=payload)
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Re-read config to verify updates took effect
    get_res = fresh_client.get("/config")
    assert get_res.status_code == 200
    updated_data = get_res.json()
    assert updated_data["gdrive_remote"] == "gdrive"
    assert updated_data["gdrive_src"] == "UpdatedSourceFolder"
    assert updated_data["nc_remote"] == "ncwebdav"
    assert updated_data["nc_dest_path"] == "UpdatedDestinationFolder"

    # Secret assertions: Fernet key should not be in the response
    assert_no_secrets_leaked(updated_data, [isolated_fresh_install.fernet_key])


def test_rclone_config_read_and_update(fresh_client: TestClient, isolated_fresh_install: InstallationRoot):
    """Verify reading and updating /rclone/config performance settings."""
    # Read current rclone settings
    res = fresh_client.get("/rclone/config")
    assert res.status_code == 200
    rclone_cfg = res.json()
    assert rclone_cfg["transfers"] == 8
    assert rclone_cfg["checkers"] == 16

    # Update rclone config with all required fields
    update_payload = {
        "transfers": 12,
        "checkers": 24,
        "tpslimit": 30,
        "tpslimit_burst": 50,
        "fast_list": True,
    }
    update_res = fresh_client.post("/rclone/config", json=update_payload)
    assert update_res.status_code == 200
    assert update_res.json()["success"] is True

    # Verify updated settings returned on read
    verify_res = fresh_client.get("/rclone/config")
    assert verify_res.status_code == 200
    updated = verify_res.json()
    assert updated["transfers"] == 12
    assert updated["checkers"] == 24
    assert updated["tpslimit"] == 30
    assert updated["tpslimit_burst"] == 50
    assert updated["fast_list"] is True


def test_legacy_encrypted_settings_decryption(legacy_client: TestClient, isolated_legacy_install: InstallationRoot):
    """Verify legacy Fernet-encrypted environment values are decrypted properly by ConfigManager."""
    cfg = ConfigManager()
    gdrive_oauth = cfg.get_gdrive_oauth_config()

    # The decrypted values must match the legacy seeded plaintexts
    assert gdrive_oauth["client_id"] == "legacy-google-client-id-12345.apps.googleusercontent.com"
    assert gdrive_oauth["client_secret"] == "legacy-google-client-secret-XYZ-SECRET"

    # Verify API read does not leak Fernet key or auth password
    res = legacy_client.get("/config")
    assert res.status_code == 200
    config_dict = res.json()
    assert config_dict.get("gdrive_src") == "LegacyFolder"
    assert config_dict.get("nc_dest_path") == "LegacyBackups"

    assert_no_secrets_leaked(
        config_dict,
        [
            isolated_legacy_install.fernet_key,
            "legacy_secret_password_456",
        ],
    )
