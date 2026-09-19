"""The route probe must verify selected folders as well as remote roots."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_configuration
from app.api.main import app
from tests.harness.fake_rclone import FakeRcloneScenario
from tests.harness.installation import InstallationRoot
from tests.harness.state import ProcessStateReset


@pytest.mark.parametrize(
    ("scenario", "failed_endpoint", "failed_kind"),
    [
        (FakeRcloneScenario(missing_paths=["gdrive:SelectedSource"]), "source", "path"),
        (FakeRcloneScenario(missing_paths=["ncwebdav:SelectedDestination"]), "destination", "path"),
        (FakeRcloneScenario(failing_remotes=["gdrive"]), "source", "remote"),
        (FakeRcloneScenario(failing_remotes=["ncwebdav"]), "destination", "remote"),
    ],
)
def test_selected_route_failure_is_identified_without_secrets(
    scenario: FakeRcloneScenario, failed_endpoint: str, failed_kind: str
) -> None:
    installation = InstallationRoot()
    installation.create_fresh()
    installation.fake_rclone.set_scenario(scenario)
    try:
        with ProcessStateReset(env_overlay=installation.get_env_dict()):
            get_configuration().set_sync_paths(
                {"gdrive_src": "SelectedSource", "nc_dest_path": "SelectedDestination"}
            )
            response = TestClient(app).post("/config/paths/verify")
            assert response.status_code == 200
            payload = response.json()
            assert payload["success"] is False
            assert payload[failed_endpoint]["path_ok"] is False
            assert payload[failed_endpoint]["remote_ok"] is (failed_kind == "path")
            assert payload["source" if failed_endpoint == "destination" else "destination"]["path_ok"] is True
            assert "SelectedSource" not in response.text
            assert "SelectedDestination" not in response.text
    finally:
        installation.cleanup()


def test_selected_route_success_and_unconfigured_path() -> None:
    installation = InstallationRoot()
    installation.create_fresh()
    try:
        with ProcessStateReset(env_overlay=installation.get_env_dict()):
            configuration = get_configuration()
            configuration.set_sync_paths(
                {"gdrive_src": "SelectedSource", "nc_dest_path": "SelectedDestination"}
            )
            original_config = installation.rclone_conf_path.read_bytes()
            client = TestClient(app)
            assert client.post("/config/paths/verify").json()["success"] is True
            assert installation.rclone_conf_path.read_bytes() == original_config

            configuration.set_sync_paths(
                {"gdrive_src": "", "nc_dest_path": "SelectedDestination"}
            )
            result = client.post("/config/paths/verify").json()
            assert result["success"] is False
            assert result["source"]["remote_ok"] is True
            assert result["source"]["path_ok"] is False
    finally:
        installation.cleanup()


def test_route_probe_redacts_rclone_errors() -> None:
    installation = InstallationRoot()
    installation.create_fresh()
    secret = "refresh-token-secret-12345"
    installation.fake_rclone.set_scenario(
        FakeRcloneScenario(exit_code=1, stderr_override=f"401 invalid token {secret}")
    )
    try:
        with ProcessStateReset(env_overlay=installation.get_env_dict()):
            get_configuration().set_sync_paths(
                {"gdrive_src": "SelectedSource", "nc_dest_path": "SelectedDestination"}
            )
            response = TestClient(app).post("/config/paths/verify")
            assert response.status_code == 200
            assert response.json()["success"] is False
            assert secret not in response.text
    finally:
        installation.cleanup()
