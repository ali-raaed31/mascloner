"""Pytest fixtures and configuration for MasCloner tests."""

from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from tests.harness.installation import InstallationRoot
from tests.harness.state import ProcessStateReset

# Set test environment before importing app modules
os.environ["MASCLONER_FERNET_KEY"] = "test_key_for_testing_only_not_real"
os.environ["MASCLONER_AUTH_ENABLED"] = "0"  # Disable auth for tests
os.environ["MASCLONER_DB_PATH"] = "data/test_mascloner.db"


@pytest.fixture(scope="session")
def temp_dir() -> Generator[Path, None, None]:
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture(scope="function")
def test_db_path(temp_dir: Path) -> Path:
    """Create a unique test database path for each test."""
    return temp_dir / f"test_{datetime.now(timezone.utc).strftime('%H%M%S%f')}.db"


@pytest.fixture(scope="function")
def test_engine(test_db_path: Path):
    """Create a test database engine with durable SQLite pragmas."""
    from app.api.models import Base
    from app.api.db import create_sqlite_engine

    engine = create_sqlite_engine(test_db_path)
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def test_session(test_engine) -> Generator[Session, None, None]:
    """Create a test database session."""
    TestingSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


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
    from app.api.main import app
    with TestClient(app) as client:
        yield client


@pytest.fixture(scope="function")
def legacy_client(isolated_legacy_install: InstallationRoot) -> Generator[TestClient, None, None]:
    """TestClient bound to legacy isolated installation with auth headers."""
    from app.api.main import app
    headers = {"Authorization": "Basic bGVnYWN5X2FkbWluOmxlZ2FjeV9zZWNyZXRfcGFzc3dvcmRfNDU2"}
    with TestClient(app, headers=headers) as client:
        yield client


@pytest.fixture(scope="function")
def mock_config_manager():
    """Create a mock ConfigManager for tests."""
    mock_config = MagicMock()
    mock_config.get_base_config.return_value = {
        "base_dir": Path("/tmp/mascloner"),
        "data_dir": Path("/tmp/mascloner/data"),
        "log_dir": Path("/tmp/mascloner/logs"),
        "rclone_conf": Path("/tmp/mascloner/rclone.conf"),
    }
    mock_config.get_sync_config.return_value = {
        "gdrive_remote": "gdrive",
        "gdrive_src": "SourceFolder",
        "nc_remote": "ncwebdav",
        "nc_dest_path": "DestFolder",
    }
    mock_config.get_rclone_config.return_value = {
        "transfers": 4,
        "checkers": 8,
        "tpslimit": 10,
        "tpslimit_burst": 1,
        "bwlimit": "10M",
        "buffer_size": "16Mi",
        "fast_list": False,
        "drive_chunk_size": "64M",
        "drive_upload_cutoff": "128M",
        "log_level": "INFO",
        "drive_export": "desktop",
    }
    mock_config.is_auth_enabled.return_value = False
    return mock_config


@pytest.fixture(scope="function")
def test_client(test_session, mock_config_manager) -> Generator[TestClient, None, None]:
    """Create a TestClient with mocked dependencies."""
    from app.api.db import get_db
    from app.api.dependencies import get_config, get_configuration
    from app.api.main import app
    from app.configuration import Configuration

    app.dependency_overrides[get_db] = lambda: test_session
    app.dependency_overrides[get_config] = lambda: mock_config_manager
    app.dependency_overrides[get_configuration] = lambda: Configuration(session_factory=lambda: test_session)

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def mock_rclone_runner():
    """Mock RcloneRunner for tests."""
    with patch("app.api.dependencies.get_runner") as mock_get_runner:
        mock_instance = MagicMock()
        mock_get_runner.return_value = mock_instance

        mock_instance.test_connection.return_value = (True, "Connection successful")
        mock_instance.test_connection_async.return_value = (True, "Connection successful")
        mock_instance.list_folders.return_value = ["folder1", "folder2"]
        mock_instance.list_folders_async.return_value = ["folder1", "folder2"]
        mock_instance.run_sync.return_value = MagicMock(
            status="success",
            num_added=5,
            num_updated=2,
            bytes_transferred=1024000,
            errors=0,
            events=[],
        )

        yield mock_instance


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run for tests."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="gdrive:\nncwebdav:\n",
            stderr="",
        )
        yield mock_run


@pytest.fixture
def sample_run_data():
    """Sample run data for tests."""
    return {
        "status": "success",
        "num_added": 10,
        "num_updated": 5,
        "bytes_transferred": 1024 * 1024 * 10,
        "errors": 0,
    }


@pytest.fixture
def sample_config_data():
    """Sample configuration data for tests."""
    return {
        "gdrive_remote": "gdrive",
        "gdrive_src": "Test Folder",
        "nc_remote": "ncwebdav",
        "nc_dest_path": "Sync",
    }


@pytest.fixture
def sample_event_data():
    """Sample file event data for tests."""
    return {
        "action": "added",
        "file_path": "documents/test.pdf",
        "file_size": 1024 * 100,
        "message": "File copied successfully",
    }
