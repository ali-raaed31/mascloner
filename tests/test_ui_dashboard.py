"""Unit tests for Live Dashboard logic."""

from unittest.mock import MagicMock, patch
import pytest

from app.ui.api_client import APIClient
from app.ui.components.theme import get_status_badge_meta, render_status_pill


def test_dashboard_endpoint_verification_mock():
    api = APIClient(base_url="http://127.0.0.1:8787")
    with patch.object(api, "test_google_drive_connection") as mock_gd, \
         patch.object(api, "test_nextcloud") as mock_nc:
        
        mock_gd.return_value = {"success": True, "message": "Google Drive reachable"}
        mock_nc.return_value = {"success": True, "message": "Nextcloud WebDAV verified"}

        gd_res = api.test_google_drive_connection()
        nc_res = api.test_nextcloud()

        assert gd_res["success"] is True
        assert nc_res["success"] is True
        assert "reachable" in gd_res["message"]
        assert "verified" in nc_res["message"]


def test_status_pill_rendering_for_runs():
    assert "🟢" in render_status_pill("completed")
    assert "Completed" in render_status_pill("completed")

    assert "🔵" in render_status_pill("running")
    assert "Running" in render_status_pill("running")

    assert "🔴" in render_status_pill("failed")
    assert "Failed" in render_status_pill("failed")
