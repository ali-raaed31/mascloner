"""TDD tests for Issue #4: Move synchronization paths and rclone performance settings to SQLite.

Verifies:
1. Alembic schema migration adding provenance to config table.
2. Migration seeds/imports legacy settings without altering effective values.
3. Fresh installations receive documented defaults.
4. GET and POST endpoints for rclone performance and sync paths persist strictly to SQLite.
5. Production writes to .env are removed.
6. Validation errors return deterministic 422 responses without leaking secrets.
7. Active sync runs isolate immutable settings snapshots.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.api.models import Base, ConfigKV
from app.execution.command_builder import RcloneCommandBuilder
from app.configuration import Configuration, RclonePerformanceSettings, SyncPathsSettings
from tests.harness.installation import InstallationRoot


@pytest.fixture
def test_alembic_cfg() -> Config:
    """Provide Alembic Config pointing to repo alembic.ini."""
    repo_root = Path(__file__).resolve().parent.parent
    ini_path = repo_root / "alembic.ini"
    cfg = Config(str(ini_path))
    cfg.set_main_option("script_location", str(repo_root / "alembic"))
    return cfg


def test_schema_upgrade_seeds_legacy_fixtures(
    isolated_legacy_install: InstallationRoot,
    test_alembic_cfg: Config,
    monkeypatch: pytest.MonkeyPatch,
):
    """A schema upgrade seeds/imports all supported settings from legacy fixtures without changing effective values."""
    monkeypatch.setenv("MASCLONER_DB_PATH", str(isolated_legacy_install.db_path))
    monkeypatch.setenv("MASCLONER_BASE_DIR", str(isolated_legacy_install.base_dir))

    # Stamp at previous revision then run upgrade
    command.stamp(test_alembic_cfg, "20241226_000001")
    command.upgrade(test_alembic_cfg, "head")

    engine = create_engine(f"sqlite:///{isolated_legacy_install.db_path}")
    Session = sessionmaker(bind=engine)
    with Session() as session:
        rows = {row.key: row for row in session.execute(select(ConfigKV)).scalars().all()}

        # Verify paths imported with legacy values
        assert "gdrive_src" in rows
        assert rows["gdrive_src"].value == "LegacyFolder"
        assert rows["gdrive_src"].provenance in ("imported_legacy", "legacy")

        assert "nc_dest_path" in rows
        assert rows["nc_dest_path"].value == "LegacyBackups"

        # Verify performance settings imported with legacy values
        assert "transfers" in rows
        assert rows["transfers"].value == "4"  # Default / seeded
        assert rows["checkers"].value == "8"


def test_fresh_install_receives_documented_defaults(
    temp_dir: Path,
    test_alembic_cfg: Config,
    monkeypatch: pytest.MonkeyPatch,
):
    """Fresh installations receive documented validated defaults."""
    db_file = temp_dir / "fresh_alembic.db"
    monkeypatch.setenv("MASCLONER_DB_PATH", str(db_file))
    monkeypatch.setenv("MASCLONER_BASE_DIR", str(temp_dir))

    # Run upgrade from head on fresh empty DB
    command.upgrade(test_alembic_cfg, "head")

    engine = create_engine(f"sqlite:///{db_file}")
    Session = sessionmaker(bind=engine)
    with Session() as session:
        rows = {row.key: row for row in session.execute(select(ConfigKV)).scalars().all()}
        assert "transfers" in rows
        assert rows["transfers"].value == "4"
        assert rows["transfers"].provenance == "default"
        assert "checkers" in rows
        assert rows["checkers"].value == "8"
        assert "tpslimit" in rows
        assert "fast_list" in rows
        assert rows["fast_list"].value == "false"


def test_api_rclone_performance_persists_to_sqlite_not_env(
    fresh_client: TestClient, isolated_fresh_install: InstallationRoot
):
    """Updating rclone performance persists to SQLite and no longer writes to .env."""
    env_content_before = isolated_fresh_install.root_env_path.read_text(encoding="utf-8")

    update_payload = {
        "transfers": 12,
        "checkers": 24,
        "tpslimit": 30,
        "tpslimit_burst": 50,
        "fast_list": True,
        "buffer_size": "64Mi",
    }

    res = fresh_client.post("/rclone/config", json=update_payload)
    assert res.status_code == 200
    assert res.json()["success"] is True

    # .env MUST NOT be modified
    env_content_after = isolated_fresh_install.root_env_path.read_text(encoding="utf-8")
    assert env_content_before == env_content_after
    assert "RCLONE_TRANSFERS=12" not in env_content_after

    # SQLite MUST contain the updated values
    engine = create_engine(f"sqlite:///{isolated_fresh_install.db_path}")
    Session = sessionmaker(bind=engine)
    with Session() as session:
        rows = {row.key: row for row in session.execute(select(ConfigKV)).scalars().all()}
        assert rows["transfers"].value == "12"
        assert rows["transfers"].provenance == "user"
        assert rows["checkers"].value == "24"
        assert rows["buffer_size"].value == "64Mi"
        assert rows["fast_list"].value == "true"

    # API GET returns the updated values
    get_res = fresh_client.get("/rclone/config")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["transfers"] == 12
    assert data["checkers"] == 24
    assert data["buffer_size"] == "64Mi"
    assert data["fast_list"] is True


def test_api_sync_paths_crud_and_normalization(
    fresh_client: TestClient, isolated_fresh_install: InstallationRoot
):
    """Sync paths endpoints normalize slashes, persist to SQLite, and reject invalid inputs."""
    # Dedicated /config/paths endpoint
    payload = {
        "gdrive_src": "/my/source/folder/",
        "nc_dest_path": "nextcloud/backup/dest/",
    }
    res = fresh_client.post("/config/paths", json=payload)
    assert res.status_code == 200
    assert res.json()["success"] is True

    get_res = fresh_client.get("/config/paths")
    assert get_res.status_code == 200
    data = get_res.json()
    # Normalized without leading/trailing slashes
    assert data["gdrive_src"] == "my/source/folder"
    assert data["nc_dest_path"] == "nextcloud/backup/dest"

    # Compatibility: GET /config also reflects the paths
    config_res = fresh_client.get("/config")
    assert config_res.status_code == 200
    assert config_res.json()["gdrive_src"] == "my/source/folder"
    assert config_res.json()["nc_dest_path"] == "nextcloud/backup/dest"


def test_field_level_validation_errors_and_no_secrets(fresh_client: TestClient):
    """Invalid performance values are rejected with field-level errors and no secret leakage."""
    # Invalid transfers (0 is < 1, 100 is > 64)
    res = fresh_client.post("/rclone/config", json={"transfers": 0, "checkers": 16})
    assert res.status_code == 422
    assert "transfers" in str(res.json())

    res2 = fresh_client.post("/rclone/config", json={"transfers": 100, "checkers": 16})
    assert res2.status_code == 422
    assert "transfers" in str(res2.json())

    # Invalid checkers
    res3 = fresh_client.post("/rclone/config", json={"transfers": 8, "checkers": 200})
    assert res3.status_code == 422
    assert "checkers" in str(res3.json())


def test_immutable_settings_snapshot_isolation(isolated_fresh_install: InstallationRoot):
    """A run uses one immutable settings snapshot even if settings are changed while it executes."""
    # Initial snapshot
    initial_perf = RclonePerformanceSettings(transfers=4, checkers=8, tpslimit=10)
    initial_paths = SyncPathsSettings(gdrive_src="initial/src", nc_dest_path="initial/dest")

    # Build command using the initial snapshot
    cmd1 = RcloneCommandBuilder.build_sync_command(
        paths=initial_paths,
        perf=initial_perf,
        rclone_conf_path=isolated_fresh_install.rclone_conf_path,
        log_file_path=Path("/tmp/test.log"),
    )
    assert "--transfers=4" in cmd1
    assert "--checkers=8" in cmd1
    assert "gdrive:initial/src" in cmd1
    assert "ncwebdav:initial/dest" in cmd1

    # Mutate settings in the middle of execution
    mutated_perf = RclonePerformanceSettings(transfers=16, checkers=32, tpslimit=50)
    mutated_paths = SyncPathsSettings(gdrive_src="mutated/src", nc_dest_path="mutated/dest")

    # Command using the active run's immutable snapshot is unchanged
    assert "--transfers=4" in cmd1
    assert "--checkers=8" in cmd1
    assert "--transfers=16" not in cmd1

    # Subsequent run uses the new snapshot
    cmd2 = RcloneCommandBuilder.build_sync_command(
        paths=mutated_paths,
        perf=mutated_perf,
        rclone_conf_path=isolated_fresh_install.rclone_conf_path,
        log_file_path=Path("/tmp/test.log"),
    )
    assert "--transfers=16" in cmd2
    assert "--checkers=32" in cmd2
    assert "gdrive:mutated/src" in cmd2
    assert "ncwebdav:mutated/dest" in cmd2


def test_active_run_mutation_determinism(
    fresh_client: TestClient, isolated_fresh_install: InstallationRoot
):
    """Mutating settings during an active run updates SQLite for subsequent runs while active run maintains snapshot."""
    initial_perf = RclonePerformanceSettings(transfers=6, checkers=12, tpslimit=15)
    initial_paths = SyncPathsSettings(gdrive_src="src", nc_dest_path="dest")

    # Mid-run mutation via API
    res = fresh_client.post(
        "/rclone/config",
        json={"transfers": 16, "checkers": 32, "tpslimit": 40, "tpslimit_burst": 50},
    )
    assert res.status_code == 200

    # Active run still uses its snapshot
    active_cmd = RcloneCommandBuilder.build_sync_command(
        paths=initial_paths,
        perf=initial_perf,
        rclone_conf_path=isolated_fresh_install.rclone_conf_path,
        log_file_path=Path("/tmp/active_run.log"),
    )
    assert "--transfers=6" in active_cmd
    assert "--transfers=16" not in active_cmd

    # Subsequent run without snapshot uses updated settings from SQLite
    cfg = Configuration(
        base_dir=isolated_fresh_install.base_dir,
        env_path=isolated_fresh_install.root_env_path,
        rclone_conf_path=isolated_fresh_install.rclone_conf_path,
    )
    new_perf = cfg.get_performance()
    assert new_perf.transfers == 16
    assert new_perf.checkers == 32

    next_cmd = RcloneCommandBuilder.build_sync_command(
        paths=initial_paths,
        perf=new_perf,
        rclone_conf_path=isolated_fresh_install.rclone_conf_path,
        log_file_path=Path("/tmp/next_run.log"),
    )
    assert "--transfers=16" in next_cmd
    assert "--checkers=32" in next_cmd


def test_path_and_size_syntax_validation(fresh_client: TestClient):
    """Verify path traversal, null bytes, and invalid size strings are rejected."""
    # Path traversal rejected on /config/paths
    traversal_res = fresh_client.post("/config/paths", json={"gdrive_src": "../evil", "nc_dest_path": "dest"})
    assert traversal_res.status_code == 422
    assert "traversal" in str(traversal_res.json()).lower()

    # Path traversal rejected on legacy /config
    traversal_legacy = fresh_client.post(
        "/config",
        json={"gdrive_remote": "gdrive", "gdrive_src": "../evil", "nc_remote": "ncwebdav", "nc_dest_path": "dest"},
    )
    assert traversal_legacy.status_code == 422
    assert "traversal" in str(traversal_legacy.json()).lower()

    # Null bytes rejected
    null_res = fresh_client.post("/config/paths", json={"gdrive_src": "safe\0evil", "nc_dest_path": "dest"})
    assert null_res.status_code == 422

    # Complete valid payload with invalid size string rejected with 422 (not 500)
    invalid_size_res = fresh_client.post(
        "/rclone/config",
        json={
            "transfers": 4,
            "checkers": 8,
            "tpslimit": 10,
            "tpslimit_burst": 1,
            "buffer_size": "not_a_size",
        },
    )
    assert invalid_size_res.status_code == 422
    assert "buffer_size" in str(invalid_size_res.json()).lower()


def test_migration_downgrade_and_retry(
    temp_dir: Path,
    test_alembic_cfg: Config,
    monkeypatch: pytest.MonkeyPatch,
):
    """Downgrade drops provenance and deletes newly seeded keys; upgrading again succeeds idempotently."""
    db_file = temp_dir / "downgrade_test.db"
    monkeypatch.setenv("MASCLONER_DB_PATH", str(db_file))
    monkeypatch.setenv("MASCLONER_BASE_DIR", str(temp_dir))

    # 1. Upgrade to head
    command.upgrade(test_alembic_cfg, "head")

    engine = create_engine(f"sqlite:///{db_file}")
    Session = sessionmaker(bind=engine)
    with Session() as session:
        rows = {row.key: row for row in session.execute(select(ConfigKV)).scalars().all()}
        assert "transfers" in rows
        assert hasattr(rows["transfers"], "provenance")

    # 2. Downgrade to 20241226_000001
    command.downgrade(test_alembic_cfg, "20241226_000001")

    # Verify column dropped and seeded keys removed
    with Session() as session:
        # Check table columns in SQLite
        col_res = session.execute(text("PRAGMA table_info(config)")).fetchall()
        col_names = [col[1] for col in col_res]
        assert "provenance" not in col_names

        # Seeded performance keys removed
        rows_downgraded = session.execute(text("SELECT key FROM config WHERE key = 'transfers'")).fetchall()
        assert len(rows_downgraded) == 0

    # 3. Upgrade to head again (retry)
    command.upgrade(test_alembic_cfg, "head")
    with Session() as session:
        rows_retry = {row.key: row for row in session.execute(select(ConfigKV)).scalars().all()}
        assert "transfers" in rows_retry


def test_drive_chunk_size_power_of_two_validation(fresh_client: TestClient, isolated_fresh_install: InstallationRoot):
    """Verify drive_chunk_size enforces power-of-two >= 256k and invalid values fall back to 64M."""
    # Valid power-of-two sizes accepted
    for valid in ["256k", "512k", "1M", "2M", "16M", "32M", "64M", "128M"]:
        res = fresh_client.post(
            "/rclone/config",
            json={"transfers": 4, "checkers": 8, "tpslimit": 10, "tpslimit_burst": 1, "drive_chunk_size": valid},
        )
        assert res.status_code == 200, f"Expected 200 for {valid}, got {res.status_code}"

    # Non-power-of-two (like 10Mi) or too small (<256k) rejected with 422
    for invalid in ["10Mi", "10M", "3M", "100k", "128k"]:
        res = fresh_client.post(
            "/rclone/config",
            json={"transfers": 4, "checkers": 8, "tpslimit": 10, "tpslimit_burst": 1, "drive_chunk_size": invalid},
        )
        assert res.status_code == 422, f"Expected 422 for {invalid}, got {res.status_code}"
        assert "power of two" in str(res.json()).lower() or "256k" in str(res.json()).lower()

    # If database contains corrupted value like 10Mi, load_performance falls back safely to 64M
    cfg = Configuration(
        base_dir=isolated_fresh_install.base_dir,
        env_path=isolated_fresh_install.root_env_path,
        rclone_conf_path=isolated_fresh_install.rclone_conf_path,
    )
    with cfg._session_factory() as session:
        cfg._sqlite_adapter._set_kv("drive_chunk_size", "10Mi", session)
        session.commit()

    loaded = cfg.get_performance()
    assert loaded.drive_chunk_size == "64M"
