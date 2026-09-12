"""Characterization tests for Google Drive, Nextcloud, and browsing endpoints."""

from __future__ import annotations

import json
from fastapi.testclient import TestClient

from tests.harness.assertions import assert_no_secrets_leaked
from tests.harness.installation import InstallationRoot


def test_google_drive_oauth_endpoints(fresh_client: TestClient, isolated_fresh_install: InstallationRoot):
    """Verify Google Drive OAuth setup and configuration storage."""
    client_secret_raw = "super-secret-oauth-client-secret-999"

    # Test saving custom OAuth credentials
    save_payload = {
        "client_id": "123456789-google.apps.googleusercontent.com",
        "client_secret": client_secret_raw,
    }
    save_res = fresh_client.post("/oauth/google-drive/oauth-config", json=save_payload)
    assert save_res.status_code == 200
    assert save_res.json()["success"] is True

    # Test reading OAuth configuration (secret must be masked)
    get_res = fresh_client.get("/oauth/google-drive/oauth-config")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["client_id"] == "123456789-google.apps.googleusercontent.com"
    assert data["client_secret"] == "***"
    assert data["has_custom_oauth"] is True

    # Configure Google Drive via token
    token_json = json.dumps(
        {
            "access_token": "ya29.sample_fresh_token_111",
            "token_type": "Bearer",
            "refresh_token": "1//sample_refresh_token_222",
            "expiry": "2026-12-31T23:59:59Z",
        }
    )
    cfg_payload = {
        "token": token_json,
        "scope": "drive.readonly",
    }
    cfg_res = fresh_client.post("/oauth/google-drive", json=cfg_payload)
    assert cfg_res.status_code == 200
    assert cfg_res.json()["success"] is True

    # Verify rclone.conf updated with gdrive remote
    rclone_conf = isolated_fresh_install.rclone_conf_path.read_text(encoding="utf-8")
    assert "[gdrive]" in rclone_conf
    assert "ya29.sample_fresh_token_111" in rclone_conf

    # Secret assertion: raw client secret not leaked in API response
    assert_no_secrets_leaked(get_res.json(), [client_secret_raw])


def test_nextcloud_webdav_test_endpoint(fresh_client: TestClient, isolated_fresh_install: InstallationRoot):
    """Verify Nextcloud WebDAV connectivity check and remote creation using fake rclone."""
    secret_password = "very_secret_nextcloud_app_password"
    payload = {
        "url": "https://nextcloud.example.local/remote.php/dav/files/user/",
        "user": "sync_user",
        "pass": secret_password,
        "remote_name": "ncwebdav",
    }

    response = fresh_client.post("/test/nextcloud/webdav", json=payload)
    assert response.status_code == 200
    assert response.json()["success"] is True

    # Secret assertion: raw password never appears in API payload
    assert_no_secrets_leaked(response.json(), [secret_password])


def test_browse_and_size_estimation_endpoints(fresh_client: TestClient, isolated_fresh_install: InstallationRoot):
    """Verify browse folders and size estimation using fake rclone."""
    # List folders in gdrive
    browse_res = fresh_client.get("/browse/folders/gdrive?path=TestFolder")
    assert browse_res.status_code == 200
    browse_data = browse_res.json()
    assert browse_data["success"] is True
    assert "folders" in browse_data
    assert len(browse_data["folders"]) > 0

    # Estimate sync size
    size_res = fresh_client.get("/estimate/size?source=gdrive:TestFolder&dest=ncwebdav:Backups")
    assert size_res.status_code == 200
    size_data = size_res.json()
    assert size_data["success"] is True
    assert size_data["file_count"] >= 0
    assert size_data["size_mb"] >= 0
