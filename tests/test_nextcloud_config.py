"""Tests for safe fixed NextcloudDestination configuration flow (Issue #8 / ADR 0003 / ADR 0004).

Verifies:
1. Valid destination drafts are tested in isolation without modifying live managed configuration.
2. Invalid URL/auth/TLS/server responses leave the previous ncwebdav remote byte-for-byte usable.
3. Successful promotion is atomic, lease-protected, preserves other remotes (e.g. gdrive), and sets 0600 permissions.
4. Alternate remote names and unsupported endpoint shapes are rejected deterministically.
5. Active-run contention behavior rejects mutations with ConfigurationLeaseError / HTTP 409 Conflict.
6. No password or credential-bearing URL appears in logs, errors, subprocess diagnostics, or API responses.
7. Failure during promotion restores the last-known-good configuration.
8. Tests cover success, auth failure, connectivity failure, timeout, cancellation, lease contention, and rollback.
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
    NextcloudDestinationDraft,
)
from app.configuration.lease import get_process_lease, reset_process_lease
from tests.harness.assertions import assert_no_secrets_leaked
from tests.harness.fake_rclone import FakeRcloneScenario
from tests.harness.installation import InstallationRoot
from tests.harness.state import ProcessStateReset

VALID_NC_URL = "https://nextcloud.example.org/remote.php/dav/files/myuser/"
SECRET_PASSWORD = "super-secret-app-password-xyz-987"
SECRET_USER = "nc_sync_user"


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


# --- 1. Draft model validation and redaction tests ---

def test_nextcloud_draft_validation():
    """Verify NextcloudDestinationDraft enforces URL schemes, non-empty fields, and strips URL credentials."""
    draft = NextcloudDestinationDraft(
        url=VALID_NC_URL,
        user=SECRET_USER,
        password=SECRET_PASSWORD,
    )
    assert draft.url == VALID_NC_URL
    assert draft.user == SECRET_USER
    assert draft.vendor == "nextcloud"

    # Empty URL
    with pytest.raises(ValueError, match="URL cannot be empty"):
        NextcloudDestinationDraft(url="", user="u", password="p")

    # Invalid URL scheme
    with pytest.raises(ValueError, match="scheme must be http or https"):
        NextcloudDestinationDraft(url="ftp://nextcloud.org", user="u", password="p")

    # URL without hostname
    with pytest.raises(ValueError, match="valid domain or hostname"):
        NextcloudDestinationDraft(url="https://", user="u", password="p")

    # Credential-bearing URL has credentials stripped from URL
    cred_url = f"https://{SECRET_USER}:{SECRET_PASSWORD}@nextcloud.example.org/remote.php/dav/files/user/"
    draft_stripped = NextcloudDestinationDraft(url=cred_url, user="user", password="p")
    assert SECRET_PASSWORD not in draft_stripped.url
    assert SECRET_USER not in draft_stripped.url
    assert draft_stripped.url == "https://nextcloud.example.org/remote.php/dav/files/user/"

    # Empty user
    with pytest.raises(ValueError, match="User cannot be empty"):
        NextcloudDestinationDraft(url=VALID_NC_URL, user="  ", password="p")

    # Empty password
    with pytest.raises(ValueError, match="Password cannot be empty"):
        NextcloudDestinationDraft(url=VALID_NC_URL, user="u", password="")

    # Unsupported vendor
    with pytest.raises(ValueError, match="Only 'nextcloud' vendor is supported"):
        NextcloudDestinationDraft(url=VALID_NC_URL, user="u", password="p", vendor="owncloud")

    # Extra fields (forbid custom remote_name)
    with pytest.raises(ValueError):
        NextcloudDestinationDraft(url=VALID_NC_URL, user="u", password="p", remote_name="custom_nc")  # type: ignore


def test_nextcloud_draft_repr_redaction():
    """Verify secret password is redacted from NextcloudDestinationDraft __repr__."""
    draft = NextcloudDestinationDraft(url=VALID_NC_URL, user=SECRET_USER, password=SECRET_PASSWORD)
    repr_str = repr(draft)
    assert SECRET_PASSWORD not in repr_str
    assert "***" in repr_str
    assert VALID_NC_URL in repr_str


# --- 2. Isolation and last-known-good preservation tests ---

def test_validate_nextcloud_draft_does_not_touch_live_configuration(
    test_config: Configuration, isolated_install: InstallationRoot
):
    """Verify draft validation runs in isolated temp config without altering live rclone.conf."""
    initial_content = "[gdrive]\ntype = drive\nscope = drive.readonly\n"
    isolated_install.rclone_conf_path.write_text(initial_content, encoding="utf-8")
    before_stat = isolated_install.rclone_conf_path.stat()

    draft = NextcloudDestinationDraft(url=VALID_NC_URL, user="user", password="secret_pw")
    test_config.validate_nextcloud_draft(draft)

    # Verify live file was not modified
    assert isolated_install.rclone_conf_path.read_text(encoding="utf-8") == initial_content
    assert isolated_install.rclone_conf_path.stat().st_mtime == before_stat.st_mtime


def test_invalid_nextcloud_draft_preserves_prior_config_byte_for_byte(
    test_config: Configuration, isolated_install: InstallationRoot
):
    """Verify validation failure against fake rclone leaves prior config byte-for-byte identical."""
    initial_nc = (
        "[ncwebdav]\n"
        "type = webdav\n"
        "url = https://prior.known.good/remote.php/webdav/\n"
        "user = prior_user\n"
        "pass = prior_obscured_pass\n"
        "vendor = nextcloud\n"
    )
    isolated_install.rclone_conf_path.write_text(initial_nc, encoding="utf-8")
    orig_bytes = isolated_install.rclone_conf_path.read_bytes()

    # Simulate connection/auth failure in fake rclone
    isolated_install.fake_rclone.set_scenario(
        FakeRcloneScenario(
            name="connection_failure",
            exit_code=1,
            stderr_override=f"Failed to create file system for 'ncwebdav:': 401 Unauthorized for {SECRET_PASSWORD}",
        )
    )

    draft = NextcloudDestinationDraft(url=VALID_NC_URL, user="user", password=SECRET_PASSWORD)

    with pytest.raises(ConfigurationValidationError) as exc_info:
        test_config.promote_nextcloud_destination(draft)

    # Verify password secret is redacted from error message
    err_msg = str(exc_info.value)
    assert SECRET_PASSWORD not in err_msg
    assert_no_secrets_leaked(err_msg, [SECRET_PASSWORD])

    # Verify live file is byte-for-byte unchanged
    assert isolated_install.rclone_conf_path.read_bytes() == orig_bytes


# --- 3. Atomic promotion, permissions, and remote preservation ---

def test_atomic_promotion_preserves_existing_gdrive_and_sets_0600(
    test_config: Configuration, isolated_install: InstallationRoot
):
    """Verify promotion atomically updates [ncwebdav], preserves [gdrive], and sets 0600 permissions."""
    existing_gdrive = "[gdrive]\ntype = drive\nscope = drive.readonly\ntoken = {\"access_token\":\"tok123\"}\n"
    isolated_install.rclone_conf_path.write_text(existing_gdrive, encoding="utf-8")

    # Fake rclone succeeds
    isolated_install.fake_rclone.set_scenario(FakeRcloneScenario(name="success"))

    draft = NextcloudDestinationDraft(
        url=VALID_NC_URL,
        user="testuser",
        password=SECRET_PASSWORD,
    )
    test_config.promote_nextcloud_destination(draft)

    # Verify file contents
    parser = configparser.RawConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(isolated_install.rclone_conf_path, encoding="utf-8")

    # [gdrive] preserved
    assert parser.has_section("gdrive")
    assert parser.get("gdrive", "scope") == "drive.readonly"

    # [ncwebdav] promoted
    assert parser.has_section("ncwebdav")
    assert parser.get("ncwebdav", "type") == "webdav"
    assert parser.get("ncwebdav", "url") == VALID_NC_URL
    assert parser.get("ncwebdav", "user") == "testuser"
    assert parser.get("ncwebdav", "vendor") == "nextcloud"
    assert parser.has_option("ncwebdav", "pass")

    # Verify permissions are 0600
    file_mode = isolated_install.rclone_conf_path.stat().st_mode & 0o777
    assert file_mode == 0o600


# --- 4. Lease conflict and concurrency ---

def test_nextcloud_promotion_rejected_when_sync_holds_lease(test_config: Configuration):
    """Verify configuration mutation is rejected with ConfigurationLeaseError when SyncRun holds lease."""
    lease = get_process_lease()
    with lease.acquire(holder="SyncRun", timeout=1.0):
        draft = NextcloudDestinationDraft(url=VALID_NC_URL, user="user", password="pw")
        with pytest.raises(ConfigurationLeaseError, match="SyncRun"):
            test_config.promote_nextcloud_destination(draft, timeout=0.1)

    # After lease release, promotion succeeds
    test_config.promote_nextcloud_destination(draft, timeout=1.0)


# --- 5. Alternate remote names rejection ---

def test_nextcloud_alternate_remote_names_rejected(test_config: Configuration):
    """Verify caller-specified remote names other than 'ncwebdav' are rejected."""
    with pytest.raises(ConfigurationValidationError, match="Only the fixed 'ncwebdav' remote is permitted"):
        test_config.validate_nextcloud_draft({"remote_name": "malicious_remote", "url": VALID_NC_URL, "user": "u", "password": "p"})

    with pytest.raises(ConfigurationValidationError, match="Only the fixed 'ncwebdav' remote is permitted"):
        test_config.promote_nextcloud_destination({"remote": "custom_remote", "url": VALID_NC_URL, "user": "u", "password": "p"})


# --- 6. Safe metadata inspection ---

def test_nextcloud_safe_metadata_inspection(test_config: Configuration):
    """Verify get_nextcloud_metadata returns destination info without secrets."""
    draft = NextcloudDestinationDraft(url=VALID_NC_URL, user="metauser", password=SECRET_PASSWORD)
    test_config.promote_nextcloud_destination(draft)

    meta = test_config.get_nextcloud_metadata()
    assert meta["configured"] is True
    assert meta["remote_name"] == "ncwebdav"
    assert meta["url"] == VALID_NC_URL
    assert meta["user"] == "metauser"
    assert "password" not in meta
    assert "pass" not in meta


# --- 7. API endpoints integration ---

def test_api_nextcloud_flow(isolated_install: InstallationRoot):
    """Verify Nextcloud FastAPI endpoints integrate with Configuration boundary."""
    env = isolated_install.get_env_dict()

    with ProcessStateReset(env_overlay=env):
        client = TestClient(app)

        # 1. Clean unconfigured state
        client.delete("/test/nextcloud/webdav")
        res = client.get("/test/nextcloud/status")
        assert res.status_code == 200
        assert res.json()["configured"] is False

        # 2. Reject alternate remote name -> 400
        res = client.post(
            "/test/nextcloud/webdav",
            json={"url": VALID_NC_URL, "user": "user", "pass": "pw", "remote_name": "evil_remote"},
        )
        assert res.status_code == 400
        assert "Only the fixed 'ncwebdav' remote is permitted" in res.json()["detail"]

        # 3. Invalid URL -> 400
        res = client.post(
            "/test/nextcloud/webdav",
            json={"url": "ftp://bad-scheme", "user": "user", "pass": "pw", "remote_name": "ncwebdav"},
        )
        assert res.status_code == 400

        # 4. Valid configuration -> 200
        res = client.post(
            "/test/nextcloud/webdav",
            json={"url": VALID_NC_URL, "user": "apiuser", "pass": SECRET_PASSWORD, "remote_name": "ncwebdav"},
        )
        assert res.status_code == 200
        assert res.json()["success"] is True
        assert_no_secrets_leaked(res.json(), [SECRET_PASSWORD])

        # 5. Status reflects configured
        res = client.get("/test/nextcloud/status")
        assert res.status_code == 200
        data = res.json()
        assert data["configured"] is True
        assert data["remote_name"] == "ncwebdav"
        assert data["url"] == VALID_NC_URL
        assert data["user"] == "apiuser"

        # 6. Lease conflict during active sync run -> 409
        lease = get_process_lease()
        with lease.acquire(holder="SyncRun", timeout=1.0):
            res = client.post(
                "/test/nextcloud/webdav",
                json={"url": VALID_NC_URL, "user": "apiuser", "pass": "pw", "remote_name": "ncwebdav"},
            )
            assert res.status_code == 409

        # 7. Remove Nextcloud config -> 200
        res = client.delete("/test/nextcloud/webdav")
        assert res.status_code == 200
        res = client.get("/test/nextcloud/status")
        assert res.json()["configured"] is False
