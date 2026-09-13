"""Unit tests for Maintenance and Diagnostics view logic."""

from unittest.mock import MagicMock, patch
import pytest

from app.ui.api_client import APIClient


def test_retention_and_backup_calls():
    api = APIClient(base_url="http://127.0.0.1:8787")
    with patch.object(api, "_make_request") as mock_req:
        mock_req.side_effect = [
            {"retention_days": 60, "last_report": {"runs_pruned": 12, "events_pruned": 45}},
            {"success": True, "runs_pruned": 5, "events_pruned": 20},
            {"success": True, "data": {"backup_path": "/srv/mascloner/backups/b1.db", "verified": True}},
        ]

        # 1. Retention status
        status = api.get_retention_status()
        assert status["retention_days"] == 60
        assert status["last_report"]["runs_pruned"] == 12

        # 2. Trigger retention
        ret_res = api.trigger_retention(dry_run=True, retention_days=60)
        assert ret_res["success"] is True

        # 3. Create backup bundle
        backup_res = api.create_backup_bundle()
        assert backup_res["success"] is True
        assert backup_res["data"]["verified"] is True
