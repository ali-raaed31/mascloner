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
    """Create a test database engine."""
    from app.api.models import Base

    engine = create_engine(
        f"sqlite:///{test_db_path}",
        future=True,
        connect_args={"check_same_thread": False},
    )
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
def mock_config_manager():
    """Create a mock ConfigManager for tests."""
    mock_config = MagicMock()
    mock_config.get_base_config.return_value = {
        "base_dir": Path("/tmp/mascloner-test"),
        "db_path": "data/mascloner.db",
        "rclone_conf": "etc/rclone.conf",
        "env_file": "etc/mascloner-sync.env",
        "log_dir": Path("logs"),
    }
    mock_config.get_api_config.return_value = {
        "host": "127.0.0.1",
        "port": 8787,
    }
    mock_config.get_rclone_config.return_value = {
        "transfers": 4,
        "checkers": 8,
        "tpslimit": 10,
        "bwlimit": "0",
    }
    mock_config.get_sync_config.return_value = {
        "gdrive_remote": "gdrive",
        "gdrive_src": "TestFolder",
        "nc_remote": "ncwebdav",
        "nc_dest_path": "Backups",
    }
    return mock_config


@pytest.fixture(scope="function")
def test_client(test_engine, mock_config_manager) -> Generator[TestClient, None, None]:
    """Create a FastAPI test client with isolated database."""
    from app.api.db import get_db
    from app.api.dependencies import get_config, reset_dependencies
    from app.api.main import app

    TestingSessionLocal = sessionmaker(
        bind=test_engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )

    def override_get_db():
        session = TestingSessionLocal()
        try:
            yield session
        finally:
            session.close()

    def override_get_config():
        return mock_config_manager

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_config] = override_get_config

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
    reset_dependencies()  # Clear cached dependencies after test


@pytest.fixture
def mock_rclone_runner():
    """Mock RcloneRunner for tests that don't need real rclone."""
    with patch("app.api.rclone_runner.RcloneRunner") as mock_class:
        mock_instance = MagicMock()
        mock_class.return_value = mock_instance

        # Default mock behaviors
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

