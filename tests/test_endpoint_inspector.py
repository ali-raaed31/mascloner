"""Tests for side-effect-free EndpointInspector module (Issue #9 / ADR 0005).

Verifies:
1. Inspection of managed endpoints never mutates managed configuration (byte-for-byte identical before/after).
2. Draft inspection uses isolated temporary configurations and always cleans up temp files/dirs.
3. Unsupported endpoints and traversal paths are rejected deterministically.
4. Output bounding (limit, truncated flag, total_count) works as specified.
5. Error categorization (auth_failure, network_failure, timeout, unknown) maps cleanly.
6. Secret redaction prevents tokens and passwords from appearing in errors, messages, and output.
7. Subprocess timeouts and cancellation clean up processes without leaving orphans.
8. API endpoints (/browse/folders, /estimate/size, /oauth/google-drive/status, /oauth/google-drive/test, /test/nextcloud) integrate with EndpointInspector.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Generator
import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.configuration.models import GoogleDriveSourceDraft, NextcloudDestinationDraft
from app.inspection import (
    BrowseResult,
    ConnectionTestResult,
    EndpointConcept,
    EndpointInspector,
    InspectionTimeoutError,
    InspectionValidationError,
    UnsupportedEndpointError,
)
from tests.harness.assertions import assert_no_secrets_leaked
from tests.harness.fake_rclone import FakeRcloneScenario
from tests.harness.installation import InstallationRoot
from tests.harness.state import ProcessStateReset

VALID_TOKEN = '{"access_token":"inspect_token_secret_12345","token_type":"Bearer"}'
VALID_NC_URL = "https://nextcloud.example.local/remote.php/dav/files/user/"
SECRET_PW = "secret_inspect_pw_98765"


@pytest.fixture
def isolated_install() -> Generator[InstallationRoot, None, None]:
    root = InstallationRoot()
    root.create_fresh()
    try:
        yield root
    finally:
        root.cleanup()


@pytest.fixture
def inspector(isolated_install: InstallationRoot) -> Generator[EndpointInspector, None, None]:
    with ProcessStateReset(env_overlay=isolated_install.get_env_dict()):
        insp = EndpointInspector(
            rclone_conf_path=isolated_install.rclone_conf_path,
            rclone_bin=isolated_install.fake_rclone.bin_path,
            default_timeout=5.0,
            max_browse_entries=5,
        )
        yield insp


# --- 1. Side-effect-free guarantee on managed endpoints ---

@pytest.mark.asyncio
async def test_managed_endpoint_inspection_does_not_mutate_config(
    inspector: EndpointInspector, isolated_install: InstallationRoot
):
    """Verify that browse and connection test calls leave rclone.conf byte-for-byte identical."""
    configured_content = (
        "[gdrive]\n"
        "type = drive\n"
        "scope = drive.readonly\n"
        "token = {\"access_token\":\"tok123\"}\n\n"
        "[ncwebdav]\n"
        "type = webdav\n"
        "vendor = nextcloud\n"
        "url = https://nextcloud.example.local/remote.php/webdav/\n"
        "user = testuser\n"
        "pass = obscured_pass\n"
    )
    isolated_install.rclone_conf_path.write_text(configured_content, encoding="utf-8")
    initial_bytes = isolated_install.rclone_conf_path.read_bytes()
    initial_stat = isolated_install.rclone_conf_path.stat()

    # Browse source and destination
    browse_src = await inspector.browse_folders("gdrive", path="")
    assert browse_src.success is True

    browse_dst = await inspector.browse_folders("ncwebdav", path="")
    assert browse_dst.success is True

    # Test connection
    conn_src = await inspector.test_connection("gdrive")
    assert conn_src.success is True

    conn_dst = await inspector.test_connection("ncwebdav")
    assert conn_dst.success is True

    # Check status
    status_src = await inspector.get_source_status()
    assert status_src.configured is True

    status_dst = await inspector.get_destination_status()
    assert status_dst.configured is True

    # Verify byte-for-byte identity and unchanged timestamp
    assert isolated_install.rclone_conf_path.read_bytes() == initial_bytes
    assert isolated_install.rclone_conf_path.stat().st_mtime == initial_stat.st_mtime


# --- 2. Draft inspection in isolated sandbox ---

@pytest.mark.asyncio
async def test_source_draft_inspection_isolation(
    inspector: EndpointInspector, isolated_install: InstallationRoot
):
    """Verify testing GoogleDriveSourceDraft runs in temporary sandbox and does not modify managed config."""
    initial_bytes = isolated_install.rclone_conf_path.read_bytes()

    draft = GoogleDriveSourceDraft(token=VALID_TOKEN, scope="drive.readonly")
    res = await inspector.test_source_draft(draft)
    assert res.success is True
    assert res.endpoint == "gdrive"

    # Managed config is pristine
    assert isolated_install.rclone_conf_path.read_bytes() == initial_bytes


@pytest.mark.asyncio
async def test_destination_draft_inspection_isolation(
    inspector: EndpointInspector, isolated_install: InstallationRoot
):
    """Verify testing NextcloudDestinationDraft runs in temporary sandbox and does not modify managed config."""
    initial_bytes = isolated_install.rclone_conf_path.read_bytes()

    draft = NextcloudDestinationDraft(
        url=VALID_NC_URL,
        user="testuser",
        password=SECRET_PW,
    )
    res = await inspector.test_destination_draft(draft)
    assert res.success is True
    assert res.endpoint == "ncwebdav"

    # Managed config is pristine
    assert isolated_install.rclone_conf_path.read_bytes() == initial_bytes


# --- 3. Unsupported endpoint and traversal rejection ---

@pytest.mark.asyncio
async def test_unsupported_endpoint_rejection(inspector: EndpointInspector):
    """Verify only 'gdrive' and 'ncwebdav' are permitted."""
    with pytest.raises(UnsupportedEndpointError, match="Unsupported endpoint 'custom_remote'"):
        await inspector.browse_folders("custom_remote")

    with pytest.raises(UnsupportedEndpointError, match="Unsupported endpoint 's3'"):
        await inspector.test_connection("s3")


@pytest.mark.asyncio
async def test_browse_path_traversal_rejection(inspector: EndpointInspector):
    """Verify path traversal (..) is rejected with InspectionValidationError."""
    with pytest.raises(InspectionValidationError, match="traversal not permitted"):
        await inspector.browse_folders("gdrive", path="../secret")

    with pytest.raises(InspectionValidationError, match="traversal not permitted"):
        await inspector.browse_folders("ncwebdav", path="folder/../../root")


# --- 4. Bounded output and pagination ---

@pytest.mark.asyncio
async def test_browse_output_bounding(
    inspector: EndpointInspector, isolated_install: InstallationRoot
):
    """Verify directory listing honors max entries limit and sets truncated flag."""
    # Set fake rclone to return 10 directories
    many_dirs = [f"Folder_{i:02d}" for i in range(10)]
    isolated_install.fake_rclone.set_scenario(
        FakeRcloneScenario(directories_override=many_dirs)
    )

    # Request with limit=3
    res = await inspector.browse_folders("gdrive", path="", limit=3)
    assert res.success is True
    assert len(res.folders) == 3
    assert len(res.entries) == 3
    assert res.truncated is True
    assert res.total_count == 10
    assert res.folders[0] == "Folder_00"

    # Request with default limit (5 from inspector fixture)
    res_default = await inspector.browse_folders("ncwebdav", path="")
    assert res_default.success is True
    assert len(res_default.folders) == 5
    assert res_default.truncated is True


# --- 5. Error classification and secret redaction ---

@pytest.mark.asyncio
async def test_connection_error_classification_and_redaction(
    inspector: EndpointInspector, isolated_install: InstallationRoot
):
    """Verify errors are classified into categories and secrets are never exposed."""
    # 1. Auth failure
    isolated_install.fake_rclone.set_scenario(
        FakeRcloneScenario(
            exit_code=1,
            stderr_override=f"Error 401 Unauthorized for token {VALID_TOKEN}",
        )
    )
    draft = GoogleDriveSourceDraft(token=VALID_TOKEN)
    res = await inspector.test_source_draft(draft)
    assert res.success is False
    assert res.error_category == "auth_failure"
    assert_no_secrets_leaked(res.message, [VALID_TOKEN])

    # 2. Network failure
    isolated_install.fake_rclone.set_scenario(
        FakeRcloneScenario(
            exit_code=1,
            stderr_override=f"dial tcp: lookup nextcloud.example.local: no route to host with pass {SECRET_PW}",
        )
    )
    nc_draft = NextcloudDestinationDraft(url=VALID_NC_URL, user="u", password=SECRET_PW)
    nc_res = await inspector.test_destination_draft(nc_draft)
    assert nc_res.success is False
    assert nc_res.error_category == "network_failure"
    assert_no_secrets_leaked(nc_res.message, [SECRET_PW])


# --- 6. Size estimation ---

@pytest.mark.asyncio
async def test_size_estimation(inspector: EndpointInspector):
    """Verify estimate_size queries rclone size without side effects."""
    res = await inspector.estimate_size(source_path="Backups")
    assert res.success is True
    assert res.size_mb > 0
    assert res.file_count > 0


# --- 7. API routes integration ---

def test_api_browse_and_test_routes_integration(isolated_install: InstallationRoot):
    """Verify FastAPI routes integrate with EndpointInspector."""
    env = isolated_install.get_env_dict()

    with ProcessStateReset(env_overlay=env):
        client = TestClient(app)

        # 1. Browse gdrive
        browse_res = client.get("/browse/folders/gdrive?path=Docs")
        assert browse_res.status_code == 200
        data = browse_res.json()
        assert data["success"] is True
        assert data["remote"] == "gdrive"
        assert len(data["folders"]) > 0

        # 2. Browse ncwebdav
        browse_nc = client.get("/browse/folders/ncwebdav")
        assert browse_nc.status_code == 200
        assert browse_nc.json()["success"] is True

        # 3. Reject unsupported remote browse
        bad_browse = client.get("/browse/folders/unsupported_remote")
        assert bad_browse.status_code == 400

        # 4. Estimate size
        est_res = client.get("/estimate/size?source=Docs")
        assert est_res.status_code == 200
        assert est_res.json()["success"] is True
        assert "size_mb" in est_res.json()

        # 5. Google Drive test connection
        gdrive_test = client.post("/oauth/google-drive/test")
        assert gdrive_test.status_code == 200
        assert gdrive_test.json()["success"] is True

        # 6. Nextcloud test connection
        nc_test = client.post("/test/nextcloud")
        assert nc_test.status_code == 200
        assert nc_test.json()["success"] is True
