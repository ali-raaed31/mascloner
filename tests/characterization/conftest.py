"""Fixtures for characterization tests."""

from __future__ import annotations

from typing import Generator
import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from tests.harness.installation import InstallationRoot
from tests.harness.state import ProcessStateReset


@pytest.fixture(scope="function")
def isolated_fresh_install() -> Generator[InstallationRoot, None, None]:
    """Provide a fresh isolated installation with state reset."""
    install = InstallationRoot()
    install.create_fresh()
    with ProcessStateReset(install.get_env_dict()):
        yield install
    install.cleanup()


@pytest.fixture(scope="function")
def isolated_legacy_install() -> Generator[InstallationRoot, None, None]:
    """Provide a legacy isolated installation with state reset."""
    install = InstallationRoot()
    install.create_legacy()
    with ProcessStateReset(install.get_env_dict()):
        yield install
    install.cleanup()


@pytest.fixture(scope="function")
def fresh_client(isolated_fresh_install: InstallationRoot) -> Generator[TestClient, None, None]:
    """TestClient bound to fresh isolated installation."""
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="function")
def legacy_client(isolated_legacy_install: InstallationRoot) -> Generator[TestClient, None, None]:
    """TestClient bound to legacy isolated installation with auth headers."""
    headers = {"Authorization": "Basic bGVnYWN5X2FkbWluOmxlZ2FjeV9zZWNyZXRfcGFzc3dvcmRfNDU2"}
    with TestClient(app, headers=headers) as client:
        yield client
