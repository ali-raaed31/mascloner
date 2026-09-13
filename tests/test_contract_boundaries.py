"""Architecture and contract boundary tests enforcing single ownership and path deletion (ADR 0001, ADR 0005, Issue #15)."""

from __future__ import annotations

import os
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.models import ConfigKV
from app.configuration import (
    Configuration,
    RclonePerformanceSettings,
    ScheduleSettings,
    SyncPathsSettings,
)
from tests.harness.installation import InstallationRoot


def test_rclone_runner_module_is_deleted():
    """Verify that RcloneRunner and legacy runner dependencies do not exist."""
    with pytest.raises(ImportError):
        import app.api.rclone_runner  # type: ignore

    with pytest.raises(ImportError):
        from app.api.dependencies import get_runner  # type: ignore

    with pytest.raises(ImportError):
        from app.api.dependencies import get_rclone_runner  # type: ignore


def test_api_rejects_arbitrary_remote_names(fresh_client: TestClient):
    """Verify that API rejects attempts to specify arbitrary remote names."""
    # Attempt to set arbitrary gdrive remote
    res1 = fresh_client.post(
        "/config",
        json={
            "gdrive_remote": "my_custom_drive",
            "gdrive_src": "FolderA",
            "nc_remote": "ncwebdav",
            "nc_dest_path": "FolderB",
        },
    )
    assert res1.status_code == 422
    assert "Arbitrary remote names are not allowed" in str(res1.json())

    # Attempt to set arbitrary nextcloud remote
    res2 = fresh_client.post(
        "/config",
        json={
            "gdrive_remote": "gdrive",
            "gdrive_src": "FolderA",
            "nc_remote": "my_custom_nc",
            "nc_dest_path": "FolderB",
        },
    )
    assert res2.status_code == 422
    assert "Arbitrary remote names are not allowed" in str(res2.json())

    # Valid fixed remotes are accepted
    res3 = fresh_client.post(
        "/config",
        json={
            "gdrive_remote": "gdrive",
            "gdrive_src": "FolderA",
            "nc_remote": "ncwebdav",
            "nc_dest_path": "FolderB",
        },
    )
    assert res3.status_code == 200


def test_post_cutover_ignores_legacy_env_fallbacks(isolated_fresh_install: InstallationRoot):
    """After cutover milestone is recorded in SQLite, changes in .env for SQLite-owned keys are ignored."""
    engine = create_engine(f"sqlite:///{isolated_fresh_install.db_path}")
    SessionLocal = sessionmaker(bind=engine)

    cfg = Configuration(
        base_dir=isolated_fresh_install.base_dir,
        env_path=isolated_fresh_install.root_env_path,
        db_session_factory=SessionLocal,
        rclone_conf_path=isolated_fresh_install.rclone_conf_path,
    )

    # Before cutover marker, fallbacks work if key is missing from SQLite
    with SessionLocal() as db:
        db.execute(ConfigKV.__table__.delete().where(ConfigKV.key.in_(["interval_min", "transfers", "migration_version"])))
        db.commit()

    # Write fallback values into .env
    with open(isolated_fresh_install.root_env_path, "a") as f:
        f.write("\nSYNC_INTERVAL_MIN=99\nRCLONE_TRANSFERS=77\n")

    # In pre-cutover state, fallback is consulted
    sched_pre = cfg.get_schedule()
    assert sched_pre.interval_min == 99

    # Now simulate cutover milestone
    with SessionLocal() as db:
        db.merge(ConfigKV(key="migration_version", value="3.0.0", provenance="system"))
        db.commit()

    # After cutover, fallback reads from .env are strictly ignored; canonical defaults apply
    sched_post = cfg.get_schedule()
    assert sched_post.interval_min == 5  # default, NOT 99!

    perf_post = cfg.get_performance()
    assert perf_post.transfers == 4  # default, NOT 77!


def test_no_fernet_ciphertext_created_on_endpoint_updates(isolated_fresh_install: InstallationRoot):
    """Verify endpoint updates and performance settings writes never generate Fernet ciphertext."""
    engine = create_engine(f"sqlite:///{isolated_fresh_install.db_path}")
    SessionLocal = sessionmaker(bind=engine)

    cfg = Configuration(
        base_dir=isolated_fresh_install.base_dir,
        env_path=isolated_fresh_install.root_env_path,
        db_session_factory=SessionLocal,
        rclone_conf_path=isolated_fresh_install.rclone_conf_path,
    )

    cfg.set_performance(RclonePerformanceSettings(transfers=8, checkers=16))
    cfg.set_sync_paths(SyncPathsSettings(gdrive_src="NewSrc", nc_dest_path="NewDest"))
    cfg.set_schedule(ScheduleSettings(enabled=True, interval_min=15, jitter_sec=10))

    # Inspect SQLite rows
    with SessionLocal() as db:
        rows = db.execute(select(ConfigKV)).scalars().all()
        for row in rows:
            assert not str(row.value).startswith("gAAAAA"), f"Forbidden Fernet token found in {row.key}"

    # Inspect .env file to verify it was not modified with runtime settings
    with open(isolated_fresh_install.root_env_path, "r") as f:
        env_content = f.read()
    assert "gAAAAA" not in env_content
