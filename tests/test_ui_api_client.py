"""Tests for UI APIClient methods and aliases."""

from unittest.mock import MagicMock, patch
import pytest

from pydantic import ValidationError

from app.ui.api_client import (
    APIClient,
    RclonePerformanceContract,
    RunContract,
    ScheduleUpdateContract,
    SyncRouteVerificationContract,
)


def test_api_client_gdrive_methods():
    client = APIClient(base_url="http://127.0.0.1:8787")
    
    with patch.object(client, "_make_request") as mock_req:
        mock_req.return_value = {"success": True}

        # Google Drive status
        client.get_google_drive_status()
        mock_req.assert_called_with("GET", "/oauth/google-drive/status")

        client.get_gdrive_status()
        mock_req.assert_called_with("GET", "/oauth/google-drive/status")

        # Google Drive test
        client.test_google_drive_connection()
        mock_req.assert_called_with("POST", "/oauth/google-drive/test")

        client.test_gdrive("gdrive")
        mock_req.assert_called_with("POST", "/oauth/google-drive/test")

        # Google Drive remove
        client.remove_google_drive_config()
        mock_req.assert_called_with("DELETE", "/oauth/google-drive")

        client.remove_gdrive_config()
        mock_req.assert_called_with("DELETE", "/oauth/google-drive")

        # OAuth config
        client.get_google_drive_oauth_config()
        mock_req.assert_called_with("GET", "/oauth/google-drive/oauth-config")

        client.get_gdrive_oauth_config()
        mock_req.assert_called_with("GET", "/oauth/google-drive/oauth-config")

        client.save_google_drive_oauth_config("cid", "csec")
        mock_req.assert_called_with(
            "POST",
            "/oauth/google-drive/oauth-config",
            json={"client_id": "cid", "client_secret": "csec"},
        )

        client.save_gdrive_oauth_config("cid2", "csec2")
        mock_req.assert_called_with(
            "POST",
            "/oauth/google-drive/oauth-config",
            json={"client_id": "cid2", "client_secret": "csec2"},
        )

        # Configure OAuth
        client.configure_google_drive_oauth(token="tok123", scope="drive.readonly")
        mock_req.assert_called_with(
            "POST",
            "/oauth/google-drive",
            json={"token": "tok123", "scope": "drive.readonly"},
        )

        client.configure_gdrive_oauth(token="tok456")
        mock_req.assert_called_with(
            "POST",
            "/oauth/google-drive",
            json={"token": "tok456", "scope": "drive.readonly"},
        )


def test_api_client_nextcloud_methods():
    client = APIClient(base_url="http://127.0.0.1:8787")
    
    with patch.object(client, "_make_request") as mock_req:
        mock_req.return_value = {"success": True}

        # Nextcloud status
        client.get_nextcloud_status()
        mock_req.assert_called_with("GET", "/test/nextcloud/status")

        # Nextcloud remove
        client.remove_nextcloud_config()
        mock_req.assert_called_with("DELETE", "/test/nextcloud")

        # Remove remote dispatch
        client.remove_remote("gdrive")
        mock_req.assert_called_with("DELETE", "/oauth/google-drive")

        client.remove_remote("ncwebdav")
        mock_req.assert_called_with("DELETE", "/test/nextcloud")


def test_api_client_maintenance_and_oauth_methods():
    client = APIClient(base_url="http://127.0.0.1:8787")
    
    with patch.object(client, "_make_request") as mock_req:
        mock_req.return_value = {"success": True}

        # Retention status
        client.get_retention_status()
        mock_req.assert_called_with("GET", "/maintenance/retention")

        # Trigger retention
        client.trigger_retention(dry_run=True, retention_days=30)
        mock_req.assert_called_with(
            "POST",
            "/maintenance/retention",
            params={"dry_run": True, "retention_days": 30},
        )

        client.trigger_retention_cleanup()
        mock_req.assert_called_with(
            "POST",
            "/maintenance/retention",
            params={"dry_run": False, "retention_days": None},
        )

        # Create backup bundle
        client.create_backup_bundle()
        mock_req.assert_called_with("POST", "/maintenance/backup")

        # Test OAuth credentials
        client.test_oauth_credentials("test-client-id", "test-secret")
        mock_req.assert_called_with(
            "POST",
            "/oauth/google-drive/oauth-config/test",
            json={"client_id": "test-client-id", "client_secret": "test-secret"},
        )


def test_ui_contracts_reject_missing_and_unknown_fields():
    """The UI boundary must fail before a retired request reaches FastAPI."""
    with pytest.raises(ValidationError):
        ScheduleUpdateContract(enabled=True, interval_min=120)

    with pytest.raises(ValidationError):
        RclonePerformanceContract(
            transfers=4,
            checkers=8,
            tpslimit=10,
            tpslimit_burst=1,
            fast_list=False,
            use_fast_list=False,
        )


def test_typed_schedule_and_performance_operations_use_canonical_payloads():
    client = APIClient(base_url="http://127.0.0.1:8787")
    schedule = ScheduleUpdateContract(enabled=True, interval_min=120, jitter_sec=20)
    performance = RclonePerformanceContract(
        transfers=4,
        checkers=8,
        tpslimit=10,
        tpslimit_burst=1,
        buffer_size="32Mi",
        drive_chunk_size="64M",
        drive_upload_cutoff="128M",
        fast_list=False,
    )

    with patch.object(client, "_make_request") as mock_req:
        mock_req.return_value = {"success": True, "message": "saved"}
        assert client.save_schedule(schedule).success is True
        mock_req.assert_called_with(
            "POST", "/schedule", json={"enabled": True, "interval_min": 120, "jitter_sec": 20}
        )

        assert client.save_rclone_performance(performance).success is True
        mock_req.assert_called_with(
            "POST",
            "/rclone/config",
            json=performance.model_dump(),
        )


def test_typed_operations_preserve_validation_messages():
    client = APIClient(base_url="http://127.0.0.1:8787")
    schedule = ScheduleUpdateContract(enabled=True, interval_min=120, jitter_sec=20)
    with patch.object(client, "_make_request", return_value={"success": False, "message": "jitter is invalid"}):
        result = client.save_schedule(schedule)
    assert result.success is False
    assert result.message == "jitter is invalid"


def test_runs_and_route_verification_use_canonical_response_shapes():
    client = APIClient(base_url="http://127.0.0.1:8787")
    run = {
        "id": 7,
        "status": "completed",
        "started_at": "2026-09-19T10:00:00Z",
        "finished_at": "2026-09-19T10:01:30Z",
        "num_added": 3,
        "num_updated": 2,
        "bytes_transferred": 1024,
        "errors": 0,
        "log_path": None,
        "message": None,
    }
    with patch.object(client, "_make_request", return_value=[run]):
        runs = client.get_recent_runs()
    assert runs == [RunContract.model_validate(run)]
    assert runs[0].mutation_count == 5
    assert runs[0].duration_seconds == 90

    route = {
        "success": False,
        "source": {"remote_ok": True, "path_ok": False, "message": "Source path missing"},
        "destination": {"remote_ok": True, "path_ok": True, "message": "Destination path exists"},
    }
    with patch.object(client, "_make_request", return_value=route) as mock_req:
        result = client.verify_sync_route()
    assert result == SyncRouteVerificationContract.model_validate(route)
    mock_req.assert_called_with("POST", "/config/paths/verify")
