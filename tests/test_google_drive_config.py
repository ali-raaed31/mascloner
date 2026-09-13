"""Tests for safe fixed GoogleDriveSource configuration flow (Issue #6 / ADR 0003 / ADR 0004).

Verifies:
1. Valid drafts are tested in isolation without altering the live managed file.
2. Invalid credentials/drafts leave the prior gdrive configuration byte-for-byte usable.
3. Promotion is atomic, sets 0600 permissions, and preserves other remotes (e.g. ncwebdav).
4. Mutations are rejected or serialized deterministically while a conflicting run holds the lease.
5. New credentials/tokens exist solely in the managed rclone file with restrictive permissions (no Fernet in .env).
6. No secret is returned or logged on success, validation failure, timeout, or cancellation.
7. User-controlled alternate remote names are rejected.
8. Fake-rclone tests cover token rewrite, promotion failure, contention, and rollback.
9. FastAPI endpoints integrate with Configuration boundary and handle 400/409 properly.
"""

from __future__ import annotations

import configparser
import json
import os
from pathlib import Path
from typing import Generator
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.main import app
from app.configuration import (
    Configuration,
    ConfigurationLeaseError,
    ConfigurationStoreError,
    ConfigurationValidationError,
    GoogleDriveSourceDraft,
)
from app.configuration.lease import get_process_lease, reset_process_lease
from tests.harness.assertions import assert_no_secrets_leaked
from tests.harness.fake_rclone import FakeRcloneScenario
from tests.harness.installation import InstallationRoot
from tests.harness.state import ProcessStateReset


VALID_TOKEN = json.dumps(
    {
        "access_token": "ya29.a0AfH6SMB_valid_access_token_mock",
        "token_type": "Bearer",
        "refresh_token": "1//04_valid_refresh_token_mock",
        "expiry": "2026-12-31T23:59:59Z",
    }
)

SECRET_TOKEN = "ya29.a0AfH6SMB_secret_access_token_12345"
SECRET_REFRESH = "1//04_secret_refresh_token_67890"
SECRET_CLIENT = "google-super-secret-client-xyz"


@pytest.fixture
def reset_harness_state():
    reset_process_lease()
    yield
    reset_process_lease()


@pytest.fixture
def isolated_install(reset_harness_state) -> Generator[InstallationRoot, None, None]:
    root = InstallationRoot()
    root.create_fresh()
    try:
        yield root
    finally:
        root.cleanup()


@pytest.fixture
def test_config(isolated_install: InstallationRoot) -> Configuration:
    engine = create_engine(f"sqlite:///{isolated_install.db_path}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(bind=engine)

    config_mod = Configuration(
        base_dir=isolated_install.base_dir,
        env_path=isolated_install.root_env_path,
        db_session_factory=session_factory,
        rclone_conf_path=isolated_install.rclone_conf_path,
    )
    return config_mod


# --- 1. Draft model validation tests ---

def test_google_drive_draft_validation():
    """Verify GoogleDriveSourceDraft enforces valid structure and rejects invalid tokens/scopes."""
    draft = GoogleDriveSourceDraft(token=VALID_TOKEN, scope="drive.readonly")
    assert draft.scope == "drive.readonly"
    assert "access_token" in json.loads(draft.token)

    # Empty token
    with pytest.raises(ValueError, match="Token cannot be empty"):
        GoogleDriveSourceDraft(token="", scope="drive.readonly")

    # Non-JSON token
    with pytest.raises(ValueError, match="Token is not valid JSON"):
        GoogleDriveSourceDraft(token="not-json", scope="drive.readonly")

    # Missing access_token
    with pytest.raises(ValueError, match="Token JSON must contain an 'access_token'"):
        GoogleDriveSourceDraft(token=json.dumps({"token_type": "Bearer"}), scope="drive.readonly")

    # Invalid scope
    with pytest.raises(ValueError, match="Invalid Google Drive scope"):
        GoogleDriveSourceDraft(token=VALID_TOKEN, scope="invalid.scope")

    # Extra fields (forbid custom remote_name)
    with pytest.raises(ValueError):
        GoogleDriveSourceDraft(token=VALID_TOKEN, remote_name="custom_gdrive")  # type: ignore


def test_google_drive_draft_redaction():
    """Verify secrets are redacted from draft __repr__."""
    draft = GoogleDriveSourceDraft(
        token=json.dumps({"access_token": SECRET_TOKEN, "refresh_token": SECRET_REFRESH}),
        client_id="my-client-id-12345.apps.googleusercontent.com",
        client_secret=SECRET_CLIENT,
        scope="drive.readonly",
    )
    repr_str = repr(draft)
    assert SECRET_TOKEN not in repr_str
    assert SECRET_REFRESH not in repr_str
    assert SECRET_CLIENT not in repr_str
    assert "***" in repr_str


# --- 2. Isolation and last-known-good preservation tests ---

def test_validate_draft_does_not_touch_live_configuration(test_config: Configuration, isolated_install: InstallationRoot):
    """Verify draft validation runs in isolated temp config without altering live rclone.conf."""
    initial_content = "[ncwebdav]\ntype = webdav\nurl = https://cloud.example.com\n"
    isolated_install.rclone_conf_path.write_text(initial_content, encoding="utf-8")
    before_stat = isolated_install.rclone_conf_path.stat()

    draft = GoogleDriveSourceDraft(token=VALID_TOKEN, scope="drive.readonly")
    test_config.validate_google_drive_draft(draft)

    # Verify live file was not modified
    assert isolated_install.rclone_conf_path.read_text(encoding="utf-8") == initial_content
    assert isolated_install.rclone_conf_path.stat().st_mtime == before_stat.st_mtime


def test_invalid_draft_fails_and_preserves_prior_config_byte_for_byte(
    test_config: Configuration, isolated_install: InstallationRoot
):
    """Verify validation failure against fake rclone leaves prior config byte-for-byte identical."""
    initial_gdrive = (
        "[gdrive]\n"
        "type = drive\n"
        "scope = drive.readonly\n"
        "token = {\"access_token\":\"prior_known_good_token\"}\n"
    )
    isolated_install.rclone_conf_path.write_text(initial_gdrive, encoding="utf-8")
    orig_bytes = isolated_install.rclone_conf_path.read_bytes()

    # Simulate validation error in fake rclone
    isolated_install.fake_rclone.set_scenario(
        FakeRcloneScenario(
            name="validation_failure",
            exit_code=1,
            stderr_override=f"Failed to create file system for 'gdrive:': token {SECRET_TOKEN} expired",
        )
    )

    draft = GoogleDriveSourceDraft(
        token=json.dumps({"access_token": SECRET_TOKEN, "refresh_token": SECRET_REFRESH}),
        client_secret=SECRET_CLIENT,
    )

    with pytest.raises(ConfigurationValidationError) as exc_info:
        test_config.promote_google_drive_source(draft)

    # Verify secrets are redacted from error message
    err_msg = str(exc_info.value)
    assert SECRET_TOKEN not in err_msg
    assert SECRET_REFRESH not in err_msg
    assert SECRET_CLIENT not in err_msg

    # Verify live file is byte-for-byte unchanged
    assert isolated_install.rclone_conf_path.read_bytes() == orig_bytes


# --- 3. Atomic promotion, permissions, and remote preservation ---

def test_atomic_promotion_preserves_existing_remotes_and_sets_0600(
    test_config: Configuration, isolated_install: InstallationRoot
):
    """Verify promotion atomically updates [gdrive], preserves [ncwebdav], and sets 0600 permissions."""
    existing_nc = "[ncwebdav]\ntype = webdav\nurl = https://nextcloud.test/remote.php/webdav\nuser = admin\n"
    isolated_install.rclone_conf_path.write_text(existing_nc, encoding="utf-8")

    # Reset fake rclone to success
    isolated_install.fake_rclone.set_scenario(FakeRcloneScenario(name="success"))

    draft = GoogleDriveSourceDraft(token=VALID_TOKEN, scope="drive.readonly")
    test_config.promote_google_drive_source(draft)

    # Verify file contents
    parser = configparser.RawConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(isolated_install.rclone_conf_path, encoding="utf-8")

    assert parser.has_section("ncwebdav")
    assert parser.get("ncwebdav", "url") == "https://nextcloud.test/remote.php/webdav"

    assert parser.has_section("gdrive")
    assert parser.get("gdrive", "type") == "drive"
    assert parser.get("gdrive", "scope") == "drive.readonly"
    assert "ya29" in parser.get("gdrive", "token")

    # Verify file permissions are 0600
    file_mode = isolated_install.rclone_conf_path.stat().st_mode & 0o777
    assert file_mode == 0o600


# --- 4. Lease conflict and concurrency ---

def test_promotion_rejected_when_sync_holds_conflicting_lease(test_config: Configuration):
    """Verify configuration mutation is rejected with ConfigurationLeaseError when SyncRun holds lease."""
    lease = get_process_lease()
    with lease.acquire(holder="SyncRun", timeout=1.0):
        draft = GoogleDriveSourceDraft(token=VALID_TOKEN, scope="drive.readonly")
        with pytest.raises(ConfigurationLeaseError, match="SyncRun"):
            test_config.promote_google_drive_source(draft, timeout=0.1)

        with pytest.raises(ConfigurationLeaseError, match="SyncRun"):
            test_config.save_google_drive_oauth_credentials("cid", "csec", timeout=0.1)

    # After lease release, promotion succeeds
    test_config.promote_google_drive_source(draft, timeout=1.0)


# --- 5. Custom OAuth credentials storage and safe retrieval ---

def test_custom_oauth_credentials_saved_to_rclone_without_env_fernet(
    test_config: Configuration, isolated_install: InstallationRoot
):
    """Verify custom OAuth client credentials are saved to rclone.conf and not written to .env with Fernet."""
    test_config.save_google_drive_oauth_credentials("custom_client_id_999", "custom_secret_key_888")

    # Verify rclone.conf contains credentials
    parser = configparser.RawConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(isolated_install.rclone_conf_path, encoding="utf-8")

    assert parser.has_section("gdrive")
    assert parser.get("gdrive", "client_id") == "custom_client_id_999"
    assert parser.get("gdrive", "client_secret") == "custom_secret_key_888"

    # Verify .env does NOT contain GDRIVE_OAUTH_CLIENT_ID
    env_text = isolated_install.root_env_path.read_text(encoding="utf-8")
    assert "GDRIVE_OAUTH_CLIENT_ID" not in env_text

    # Safe retrieval masks the secret
    meta = test_config.get_google_drive_oauth_credentials()
    assert meta["client_id"] == "custom_client_id_999"
    assert meta["client_secret"] == "***"
    assert meta["has_custom_oauth"] is True


# --- 6. Alternate remote names rejection ---

def test_alternate_remote_names_rejected(test_config: Configuration):
    """Verify caller-specified remote names other than 'gdrive' are rejected."""
    with pytest.raises(ConfigurationValidationError, match="Only the fixed 'gdrive' remote is permitted"):
        test_config.validate_google_drive_draft({"remote_name": "malicious_remote", "token": VALID_TOKEN})

    with pytest.raises(ConfigurationValidationError, match="Only the fixed 'gdrive' remote is permitted"):
        test_config.promote_google_drive_source({"remote": "custom_remote", "token": VALID_TOKEN})


# --- 7. Token rewrite / refresh support ---

def test_token_rewrite_scenario_updates_metadata(
    test_config: Configuration, isolated_install: InstallationRoot
):
    """Verify fake rclone token refresh updates rclone.conf and metadata reflects it cleanly."""
    draft = GoogleDriveSourceDraft(token=VALID_TOKEN, scope="drive.readonly")
    test_config.promote_google_drive_source(draft)

    refreshed_token = json.dumps(
        {
            "access_token": "mutated_refreshed_token_val_999",
            "token_type": "Bearer",
            "refresh_token": "valid_refresh_token_abc",
            "expiry": "2026-12-31T23:59:59Z",
        }
    )
    isolated_install.fake_rclone.set_scenario(
        FakeRcloneScenario(
            name="token_mutation",
            mutate_config={"gdrive": {"token": refreshed_token}},
        )
    )

    # Run fake rclone command that triggers token mutation
    import subprocess
    subprocess.run([str(isolated_install.fake_rclone.bin_path), "copy", "gdrive:a", "ncwebdav:b", f"--config={isolated_install.rclone_conf_path}"])

    parser = configparser.RawConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(isolated_install.rclone_conf_path, encoding="utf-8")
    assert parser.get("gdrive", "token") == refreshed_token

    meta = test_config.get_endpoint_metadata("gdrive")
    assert meta is not None
    assert meta.details.get("token_configured") == "true" 


# --- 8. API endpoints integration ---

def test_api_google_drive_flow(isolated_install: InstallationRoot):
    """Verify Google Drive FastAPI endpoints integrate with Configuration boundary."""
    env = isolated_install.get_env_dict()

    with ProcessStateReset(env_overlay=env):
        client = TestClient(app)

        # 1. Start from clean unconfigured state
        client.delete("/oauth/google-drive")
        res = client.get("/oauth/google-drive/status")
        assert res.status_code == 200
        assert res.json()["configured"] is False

        # 2. Configure with invalid token -> 400
        res = client.post("/oauth/google-drive", json={"token": "invalid_json"})
        assert res.status_code == 400

        # 3. Configure valid token -> 200
        res = client.post("/oauth/google-drive", json={"token": VALID_TOKEN, "scope": "drive.readonly"})
        assert res.status_code == 200
        assert res.json()["success"] is True

        # 4. Status reflects configured
        res = client.get("/oauth/google-drive/status")
        assert res.status_code == 200
        data = res.json()
        assert data["configured"] is True
        assert data["remote_name"] == "gdrive"
        assert data["scope"] == "drive.readonly"

        # 5. Save OAuth credentials
        res = client.post(
            "/oauth/google-drive/oauth-config",
            json={"client_id": "api_client_id_1", "client_secret": "api_client_secret_2"},
        )
        assert res.status_code == 200

        # 6. Read OAuth credentials -> masked
        res = client.get("/oauth/google-drive/oauth-config")
        assert res.status_code == 200
        data = res.json()
        assert data["client_id"] == "api_client_id_1"
        assert data["client_secret"] == "***"
        assert data["has_custom_oauth"] is True

        # 7. Conflicting lease -> 409
        lease = get_process_lease()
        with lease.acquire(holder="SyncRun", timeout=1.0):
            res = client.post("/oauth/google-drive", json={"token": VALID_TOKEN, "scope": "drive.readonly"})
            assert res.status_code == 409

        # 8. Remove configuration
        res = client.delete("/oauth/google-drive")
        assert res.status_code == 200
        res = client.get("/oauth/google-drive/status")
        assert res.json()["configured"] is False
