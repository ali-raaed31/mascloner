"""Regression coverage for the v3.2 legacy-cutover safety boundary."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import create_engine

from app.api.db import classify_legacy_baseline, upgrade_database_to_head
from app.api.models import Base
from app.api.sync_lifecycle import migrate_legacy_statuses
from app.migration import MigrationMode, MigrationService
from tests.harness.installation import InstallationRoot


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _service(install: InstallationRoot) -> MigrationService:
    return MigrationService(
        base_dir=install.base_dir,
        env_path=install.root_env_path,
        db_path=install.db_path,
        rclone_conf_path=install.rclone_conf_path,
        backup_root=install.base_dir / "backups",
    )


def test_completed_cutover_is_a_no_mutation_boundary(isolated_legacy_install: InstallationRoot):
    service = _service(isolated_legacy_install)
    first = service.run_migration(MigrationMode.APPLY)
    assert first.success
    db_before = _digest(isolated_legacy_install.db_path)
    config_before = _digest(isolated_legacy_install.rclone_conf_path)

    replay = service.run_migration(MigrationMode.APPLY)

    assert replay.success
    assert replay.migrated_settings == {"cutover": "already complete"}
    assert _digest(isolated_legacy_install.db_path) == db_before
    assert _digest(isolated_legacy_install.rclone_conf_path) == config_before


def test_bundle_precedes_quiesce_and_failed_endpoint_validation_clears_evidence(
    isolated_legacy_install: InstallationRoot,
    monkeypatch,
):
    from tests.harness.fake_rclone import FakeRcloneScenario

    monkeypatch.setenv("RCLONE_BIN", str(isolated_legacy_install.fake_rclone.bin_path))
    monkeypatch.setenv("FAKE_RCLONE_CONTROL_FILE", str(isolated_legacy_install.fake_rclone.control_file))
    isolated_legacy_install.fake_rclone.set_scenario(
        FakeRcloneScenario(name="destination-fails", failing_remotes=["ncwebdav"])
    )

    report = _service(isolated_legacy_install).run_migration(MigrationMode.APPLY)

    assert not report.success
    assert report.endpoints_validated == []
    assert report.recovery_bundle is not None
    bundle_db = Path(report.recovery_bundle.database_backup_path)
    with create_engine(f"sqlite:///{bundle_db}").connect() as connection:
        statuses = {row[0] for row in connection.exec_driver_sql("SELECT status FROM runs")}
    assert "running" in statuses
    with create_engine(f"sqlite:///{isolated_legacy_install.db_path}").connect() as connection:
        restored_statuses = {row[0] for row in connection.exec_driver_sql("SELECT status FROM runs")}
    assert restored_statuses == statuses


def test_mapping_preserves_disabled_schedule_and_full_performance_from_env(isolated_legacy_install: InstallationRoot):
    env_path = isolated_legacy_install.root_env_path
    env_path.write_text(
        env_path.read_text(encoding="utf-8")
        + "\nSCHEDULE_ENABLED=false\nRCLONE_TPSLIMIT=31\nRCLONE_TPSLIMIT_BURST=3\n"
        + "RCLONE_BUFFER_SIZE=64Mi\nRCLONE_DRIVE_CHUNK_SIZE=128M\n"
        + "RCLONE_DRIVE_UPLOAD_CUTOFF=256M\nRCLONE_FAST_LIST=true\n",
        encoding="utf-8",
    )

    mapping = _service(isolated_legacy_install).calculate_v3_mappings(
        _service(isolated_legacy_install).inventory_legacy()
    )

    assert mapping["schedule"]["enabled"] is False
    assert mapping["performance"] == {
        "transfers": 4, "checkers": 8, "tpslimit": 31, "tpslimit_burst": 3,
        "buffer_size": "64Mi", "drive_chunk_size": "128M",
        "drive_upload_cutoff": "256M", "fast_list": True,
    }
    assert mapping["provenance"]["tpslimit"] == "imported_legacy"


def test_unknown_status_leaves_all_rows_unchanged(tmp_path: Path):
    database = tmp_path / "statuses.db"
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE runs (status TEXT NOT NULL)")
        connection.exec_driver_sql("INSERT INTO runs(status) VALUES ('success'), ('mystery')")
    try:
        with engine.begin() as connection:
            try:
                migrate_legacy_statuses(connection)
            except ValueError:
                pass
            else:
                raise AssertionError("unknown status should stop migration")
        with engine.connect() as connection:
            statuses = [row[0] for row in connection.exec_driver_sql("SELECT status FROM runs ORDER BY rowid")]
        assert statuses == ["success", "mystery"]
    finally:
        engine.dispose()


def test_unstamped_supported_schema_upgrades_and_unknown_schema_is_untouched(tmp_path: Path):
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parent.parent
    supported = tmp_path / "supported.db"
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{supported}")
    command.upgrade(cfg, "20241226_000001")
    with create_engine(f"sqlite:///{supported}").begin() as connection:
        connection.exec_driver_sql("DROP TABLE alembic_version")

    assert classify_legacy_baseline(supported) == "20241226_000001"
    assert upgrade_database_to_head(supported)

    unknown = tmp_path / "unknown.db"
    with create_engine(f"sqlite:///{unknown}").begin() as connection:
        connection.exec_driver_sql("CREATE TABLE unrelated (value TEXT)")
        connection.exec_driver_sql("INSERT INTO unrelated VALUES ('keep')")
    before = _digest(unknown)
    assert classify_legacy_baseline(unknown) is None
    assert not upgrade_database_to_head(unknown)
    assert _digest(unknown) == before


def test_stamped_head_with_missing_v3_columns_fails_closed(tmp_path: Path):
    database = tmp_path / "incomplete-head.db"
    engine = create_engine(f"sqlite:///{database}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)")
        connection.exec_driver_sql("CREATE TABLE runs (id INTEGER PRIMARY KEY, status TEXT, started_at TEXT, finished_at TEXT, num_added INTEGER, num_updated INTEGER, bytes_transferred INTEGER, errors INTEGER, log_path TEXT)")
        connection.exec_driver_sql("CREATE TABLE file_events (id INTEGER PRIMARY KEY, run_id INTEGER, timestamp TEXT, action TEXT, file_path TEXT, file_size INTEGER, file_hash TEXT, message TEXT)")
        connection.exec_driver_sql("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        connection.exec_driver_sql("INSERT INTO alembic_version VALUES ('20250101_000003')")
    engine.dispose()

    before = _digest(database)
    assert classify_legacy_baseline(database) == "stamped"
    assert not upgrade_database_to_head(database)
    assert _digest(database) == before


def test_migration_service_resolves_relative_bootstrap_paths_from_base(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("MASCLONER_BASE_DIR", str(tmp_path))
    monkeypatch.setenv("MASCLONER_DB_PATH", "data/mascloner.db")
    monkeypatch.setenv("MASCLONER_RCLONE_CONF", "etc/rclone.conf")

    service = MigrationService()

    assert service.db_path == tmp_path / "data" / "mascloner.db"
    assert service.rclone_conf_path == tmp_path / "etc" / "rclone.conf"


def test_complete_unstamped_current_orm_schema_can_be_safely_stamped(tmp_path: Path):
    database = tmp_path / "current-schema.db"
    engine = create_engine(f"sqlite:///{database}")
    Base.metadata.create_all(engine)
    engine.dispose()

    assert classify_legacy_baseline(database) == "head"
    assert upgrade_database_to_head(database)
