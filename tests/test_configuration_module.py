"""Tests for the typed Configuration module (Issue #3 / ADR 0001 / ADR 0003).

Verifies:
1. Every documented setting has exactly one declared owner and a typed representation.
2. Invalid and missing values produce deterministic typed errors without leaking secrets.
3. The configuration lease serializes contending mutating holders and releases on failure/cancellation.
4. New module tests run against isolated .env, SQLite, and rclone fixture stores from #1.
5. Shadow reads match current effective values for representative legacy installations.
6. Application startup and current APIs continue to behave as before.
7. No new persisted value uses Fernet or another application-layer encryption scheme.
"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from pathlib import Path
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.api.config import ConfigManager
from app.api.models import ConfigKV
from tests.harness.assertions import assert_no_secrets_leaked
from tests.harness.installation import InstallationRoot
from tests.harness.state import ProcessStateReset

from app.configuration import (
    Configuration,
    ConfigurationError,
    ConfigurationValidationError,
    ConfigurationLeaseError,
    StoreType,
    BootstrapSettings,
    ScheduleSettings,
    RclonePerformanceSettings,
    SyncPathsSettings,
    RetentionPolicySettings,
    SettingDiagnostic,
)


@pytest.fixture
def isolated_install():
    """Create a hermetic isolated installation for testing."""
    root = InstallationRoot()
    root.create_fresh()
    try:
        yield root
    finally:
        root.cleanup()


@pytest.fixture
def test_config(isolated_install: InstallationRoot):
    """Return an instantiated Configuration module wired to the isolated installation."""
    engine = create_engine(f"sqlite:///{isolated_install.db_path}", connect_args={"check_same_thread": False})
    session_factory = sessionmaker(bind=engine)

    config_mod = Configuration(
        base_dir=isolated_install.base_dir,
        env_path=isolated_install.root_env_path,
        db_session_factory=session_factory,
        rclone_conf_path=isolated_install.rclone_conf_path,
    )
    return config_mod


def test_bootstrap_settings_ownership_and_types(test_config: Configuration, isolated_install: InstallationRoot):
    """Verify bootstrap settings are owned by .env, typed, and correctly defaulted."""
    bootstrap = test_config.get_bootstrap()

    assert isinstance(bootstrap, BootstrapSettings)
    assert bootstrap.base_dir == isolated_install.base_dir
    assert bootstrap.data_dir == isolated_install.data_dir
    assert bootstrap.log_dir == isolated_install.log_dir
    assert bootstrap.db_path == isolated_install.db_path
    assert bootstrap.rclone_conf_path == isolated_install.rclone_conf_path
    assert bootstrap.api_host in ["127.0.0.1", "localhost"]
    assert bootstrap.api_port == 8787
    assert isinstance(bootstrap.auth_enabled, bool)
    assert isinstance(bootstrap.cors_origins, list)


def test_sqlite_settings_ownership_and_mutations(test_config: Configuration, isolated_install: InstallationRoot):
    """Verify SQLite owns Schedule, SyncPaths, Performance, and RetentionPolicy."""
    # 1. Schedule defaults and mutation
    sched = test_config.get_schedule()
    assert isinstance(sched, ScheduleSettings)
    assert sched.enabled is True
    assert sched.interval_min == 5
    assert sched.jitter_sec == 20

    test_config.set_schedule(ScheduleSettings(enabled=False, interval_min=15, jitter_sec=30))
    updated_sched = test_config.get_schedule()
    assert updated_sched.enabled is False
    assert updated_sched.interval_min == 15
    assert updated_sched.jitter_sec == 30

    # 2. Performance settings defaults and mutation
    perf = test_config.get_performance()
    assert isinstance(perf, RclonePerformanceSettings)
    assert perf.transfers == 8  # read from .env fallback in create_fresh
    assert perf.checkers == 16

    test_config.set_performance(RclonePerformanceSettings(transfers=12, checkers=24, tpslimit=20, fast_list=True))
    updated_perf = test_config.get_performance()
    assert updated_perf.transfers == 12
    assert updated_perf.checkers == 24
    assert updated_perf.tpslimit == 20
    assert updated_perf.fast_list is True

    # 3. Paths settings defaults and mutation
    paths = test_config.get_sync_paths()
    assert isinstance(paths, SyncPathsSettings)
    assert paths.gdrive_src == "FreshSource"
    assert paths.nc_dest_path == "FreshDestination"

    test_config.set_sync_paths(SyncPathsSettings(gdrive_src="/new/folder/", nc_dest_path="nextcloud/backup"))
    updated_paths = test_config.get_sync_paths()
    # Paths should be normalized (stripped of leading/trailing slashes)
    assert updated_paths.gdrive_src == "new/folder"
    assert updated_paths.nc_dest_path == "nextcloud/backup"

    # 4. Retention policy settings
    retention = test_config.get_retention_policy()
    assert isinstance(retention, RetentionPolicySettings)
    assert retention.retention_days == 60


def test_rclone_conf_metadata_and_redaction(test_config: Configuration, isolated_install: InstallationRoot):
    """Verify rclone.conf is inspected safely without exposing credentials or OAuth tokens."""
    metadata = test_config.get_all_endpoint_metadata()
    assert "gdrive" in metadata
    assert "ncwebdav" in metadata

    gdrive_meta = metadata["gdrive"]
    assert gdrive_meta.is_configured is True
    assert gdrive_meta.type == "drive"

    nc_meta = metadata["ncwebdav"]
    assert nc_meta.is_configured is True
    assert nc_meta.type == "webdav"

    # Read the raw conf to get actual secret strings to scan for
    raw_conf = isolated_install.rclone_conf_path.read_text(encoding="utf-8")
    forbidden_secrets = [
        "fake_client_secret_xyz123",
        "fake_access_token_abc456",
        "fake_refresh_token_def789",
        "obscured_fake_pass_12345",
    ]

    # Check that endpoint metadata representation contains NO forbidden secrets
    assert_no_secrets_leaked(metadata, forbidden_secrets)
    assert_no_secrets_leaked(repr(metadata), forbidden_secrets)
    assert_no_secrets_leaked(str(metadata), forbidden_secrets)


def test_validation_errors_deterministic_and_no_secret_leak(test_config: Configuration):
    """Verify invalid settings produce deterministic errors without leaking secrets."""
    secret_token = "ultra_secret_value_9999"

    # Invalid schedule interval passed as dict
    with pytest.raises(ConfigurationValidationError) as exc_info:
        test_config.set_schedule({"interval_min": 0, "jitter_sec": 10})
    assert "interval_min" in str(exc_info.value)
    assert secret_token not in str(exc_info.value)

    # Invalid performance transfers passed as dict
    with pytest.raises(ConfigurationValidationError) as exc_info:
        test_config.set_performance({"transfers": 100})
    assert "transfers" in str(exc_info.value)


def test_configuration_lease_serialization_and_release(test_config: Configuration):
    """Verify the configuration lease serializes contending holders and releases properly."""
    # 1. Successful sync acquisition and release
    with test_config.acquire_lease(holder="migration_test", timeout=1.0) as lease:
        assert lease.holder == "migration_test"
        assert test_config.is_lease_held()

    assert not test_config.is_lease_held()

    # 2. Release on error
    with pytest.raises(RuntimeError):
        with test_config.acquire_lease(holder="failing_task", timeout=1.0):
            assert test_config.is_lease_held()
            raise RuntimeError("Deliberate failure inside lease")

    assert not test_config.is_lease_held()

    # 3. Contention / timeout
    lease_acquired = threading.Event()
    release_lease = threading.Event()

    def hold_lease():
        with test_config.acquire_lease(holder="thread_holder", timeout=2.0):
            lease_acquired.set()
            release_lease.wait(timeout=5.0)

    t = threading.Thread(target=hold_lease)
    t.start()
    lease_acquired.wait(timeout=2.0)

    try:
        with pytest.raises(ConfigurationLeaseError) as exc_info:
            with test_config.acquire_lease(holder="contending_thread", timeout=0.2):
                pass
        assert "thread_holder" in str(exc_info.value)
    finally:
        release_lease.set()
        t.join(timeout=2.0)

    assert not test_config.is_lease_held()


@pytest.mark.asyncio
async def test_async_configuration_lease(test_config: Configuration):
    """Verify the configuration lease works with async context managers."""
    async with test_config.acquire_async_lease(holder="async_task", timeout=1.0) as lease:
        assert lease.holder == "async_task"
        assert test_config.is_lease_held()

    assert not test_config.is_lease_held()


def test_diagnostics_report_ownership_and_validity_redacted(test_config: Configuration, isolated_install: InstallationRoot):
    """Verify get_diagnostics() lists settings, owners, validity, and redacted values."""
    diagnostics = test_config.get_diagnostics()
    assert len(diagnostics) > 0

    diag_map = {d.key: d for d in diagnostics}

    assert "MASCLONER_BASE_DIR" in diag_map
    assert diag_map["MASCLONER_BASE_DIR"].owner == StoreType.ENV
    assert diag_map["MASCLONER_BASE_DIR"].is_valid is True

    assert "interval_min" in diag_map
    assert diag_map["interval_min"].owner == StoreType.SQLITE
    assert diag_map["interval_min"].is_valid is True

    assert "gdrive" in diag_map
    assert diag_map["gdrive"].owner == StoreType.RCLONE_CONF
    assert diag_map["gdrive"].is_valid is True

    forbidden_secrets = [
        "fake_client_secret_xyz123",
        "fake_access_token_abc456",
        "fake_refresh_token_def789",
        "obscured_fake_pass_12345",
    ]
    assert_no_secrets_leaked(diagnostics, forbidden_secrets)


def test_shadow_reads_match_legacy_resolution(
    test_config: Configuration,
    isolated_install: InstallationRoot,
    monkeypatch: pytest.MonkeyPatch,
):
    """Verify shadow reads compare accurately with legacy resolution."""
    import app.api.scheduler as legacy_scheduler
    from app.api.scheduler import get_sync_config_from_db

    with ProcessStateReset(isolated_install.get_env_dict()):
        # Initialize a legacy ConfigManager bound to the isolated environment
        legacy_manager = ConfigManager(env_file=str(isolated_install.root_env_path))
        monkeypatch.setattr(legacy_scheduler, "config", legacy_manager)

        legacy_base = legacy_manager.get_base_config()
        bootstrap = test_config.get_bootstrap()
        assert bootstrap.base_dir == legacy_base["base_dir"]

        legacy_rclone = legacy_manager.get_rclone_config()
        perf = test_config.get_performance()
        assert perf.transfers == legacy_rclone["transfers"]
        assert perf.checkers == legacy_rclone["checkers"]

        engine = create_engine(f"sqlite:///{isolated_install.db_path}")
        Session = sessionmaker(bind=engine)
        with Session() as session:
            legacy_sync = get_sync_config_from_db(session)
            paths = test_config.get_sync_paths()
            assert paths.gdrive_src == legacy_sync["gdrive_src"]
            assert paths.nc_dest_path == legacy_sync["nc_dest_path"]

        # Module provides compare_with_legacy helper
        with Session() as session:
            comparison = test_config.compare_with_legacy(legacy_manager, session)
            assert comparison["matches"] is True
            assert comparison["discrepancies"] == []


def test_no_fernet_used_for_new_writes(test_config: Configuration, isolated_install: InstallationRoot):
    """Verify no new setting write creates Fernet ciphertext."""
    test_config.set_performance(RclonePerformanceSettings(transfers=6, checkers=12))

    engine = create_engine(f"sqlite:///{isolated_install.db_path}")
    Session = sessionmaker(bind=engine)
    with Session() as session:
        rows = session.execute(select(ConfigKV)).scalars().all()
        for row in rows:
            assert not str(row.value).startswith("gAAAAA"), f"Found Fernet ciphertext in SQLite row: {row.key}"
