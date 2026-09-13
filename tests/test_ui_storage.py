"""Unit tests for Storage and Connections view logic."""

from unittest.mock import MagicMock, patch
import pytest

from app.ui.api_client import APIClient


def test_update_sync_paths_mock():
    api = APIClient(base_url="http://127.0.0.1:8787")
    with patch.object(api, "_make_request") as mock_req:
        mock_req.return_value = {"success": True, "message": "Paths updated"}

        res = api.update_sync_paths({
            "gdrive_src": "/NewSource",
            "nc_dest_path": "/NewDest",
        })

        assert res["success"] is True
        mock_req.assert_called_with(
            "POST",
            "/config/paths",
            json={"gdrive_src": "/NewSource", "nc_dest_path": "/NewDest"},
        )
