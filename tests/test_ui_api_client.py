"""Tests for UI APIClient methods and aliases."""

from unittest.mock import MagicMock, patch
import pytest

from app.ui.api_client import APIClient


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
