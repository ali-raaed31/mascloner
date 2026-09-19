"""Focused safety tests for the v3.2 updater/recovery contract (#34-#38)."""

from __future__ import annotations

import json
import os
import pwd
import sqlite3
import subprocess
import sys
import tarfile
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

import ops.cli.transaction as transaction_module
import ops.cli.commands.update as update_command
from ops.cli.main import app as cli_app
from ops.cli.recovery import RecoveryBundleError, create_recovery_bundle, restore_recovery_bundle, validate_recovery_bundle
from ops.cli.transaction import UpdateTransactionError, run_update_transaction, sha256_file, validate_release
from tests.harness import InstallationRoot


def _write(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _installation(root: Path, revision: str = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa") -> Path:
    for directory in ("app", "ops/systemd", "alembic", "etc", ".venv/bin"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    _write(root / "app/main.py")
    _write(root / "ops/cli.py")
    for service in ("mascloner-api", "mascloner-ui", "mascloner-tunnel"):
        _write(root / f"ops/systemd/{service}.service", f"[Service]\nExecStart={service}\n")
    _write(root / "alembic/env.py")
    _write(root / "alembic.ini")
    _write(root / "requirements.txt", "streamlit==1.63.0\n")
    _write(root / "VERSION", "3.0.0\n")
    _write(root / ".commit_hash", revision + "\n")
    _write(root / ".env", "MASCLONER_DB_PATH=data/mascloner.db\n")
    _write(root / "etc/rclone.conf", "[gdrive]\ntype = drive\n")
    python_path = root / ".venv/bin/python"
    _write(python_path, f"#!/bin/sh\nexec {sys.executable} \"$@\"\n")
    python_path.chmod(0o700)
    database = root / "data/mascloner.db"
    database.parent.mkdir(exist_ok=True)
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT)")
    connection.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY, status TEXT)")
    connection.execute("CREATE TABLE file_events (id INTEGER PRIMARY KEY, run_id INTEGER)")
    connection.execute("INSERT INTO config VALUES ('gdrive_src', 'source')")
    connection.execute("INSERT INTO runs VALUES (1, 'completed')")
    connection.commit()
    # Keep a WAL sidecar live while the bundle is created.
    connection.execute("INSERT INTO runs VALUES (2, 'completed')")
    connection.commit()
    connection.close()
    return root


def _release(root: Path, revision: str = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb") -> Path:
    """Create an immutable source artifact, separate from its installed runtime."""
    release = _installation(root, revision=revision)
    for relative in (".venv", "data", "etc"):
        shutil.rmtree(release / relative)
    (release / ".env").unlink()
    _write(release / "VERSION", "3.2.2\n")
    return release


def _release_manifest(root: Path, revision: str) -> None:
    inventory = {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in root.rglob("*")
        if path.is_file() and path.name != "RELEASE.json"
    }
    _write(root / "RELEASE.json", json.dumps({"format": 1, "version": "3.2.2", "revision": revision, "inventory": inventory}))


def test_recovery_bundle_snapshots_wal_database_and_restores_exact_runtime(tmp_path: Path) -> None:
    install = _installation(tmp_path / "install")
    _write(install / "data/keep.txt", "prior-data")
    wal_connection = sqlite3.connect(install / "data/mascloner.db")
    wal_connection.execute("PRAGMA journal_mode=WAL")
    wal_connection.execute("INSERT INTO runs VALUES (3, 'completed')")
    wal_connection.commit()
    wal_path = install / "data/mascloner.db-wal"
    assert wal_path.is_file() and wal_path.stat().st_size > 0
    backup = create_recovery_bundle(install, tmp_path / "backups", service_dir=install / "ops/systemd")
    wal_connection.close()
    manifest, _ = validate_recovery_bundle(backup)
    assert manifest["source"] == {"version": "3.0.0", "revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}

    _write(install / "app/failed-release.py", "bad")
    _write(install / "app/main.py", "changed")
    _write(install / "data/keep.txt", "changed")
    _write(install / "data/new.txt", "new")
    _write(install / "logs/operator-note.log", "preserve this operational log")
    restore_recovery_bundle(
        backup,
        install,
        service_dir=tmp_path / "units",
        stop_services=lambda: True,
        start_services=lambda: True,
        health_check=lambda: True,
    )
    assert not (install / "app/failed-release.py").exists()
    assert (install / "app/main.py").read_text(encoding="utf-8") == "x"
    assert (install / "data/keep.txt").read_text(encoding="utf-8") == "prior-data"
    assert not (install / "data/new.txt").exists()
    assert (install / "logs/operator-note.log").read_text(encoding="utf-8") == "preserve this operational log"
    assert sqlite3.connect(install / "data/mascloner.db").execute("SELECT count(*) FROM runs").fetchone() == (3,)


def test_recovery_bundle_inventory_matches_archive_when_python_caches_exist(tmp_path: Path) -> None:
    install = _installation(tmp_path / "install")
    _write(install / "app/__pycache__/main.cpython-312.pyc", "cache")
    _write(install / ".venv/lib/python3.12/site-packages/example.pyc", "cache")

    bundle = create_recovery_bundle(install, tmp_path / "backups", service_dir=install / "ops/systemd")
    manifest, _ = validate_recovery_bundle(bundle)

    assert all("__pycache__" not in Path(name).parts and not name.endswith(".pyc") for name in manifest["inventory"])


def test_recovery_bundle_validation_reads_payload_in_archive_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install = _installation(tmp_path / "install")
    packages = install / ".venv/lib/python3.12/site-packages"
    _write(packages / "example/module.py", "module")
    _write(packages / "example-1.dist-info/METADATA", "metadata")
    bundle = create_recovery_bundle(install, tmp_path / "backups", service_dir=install / "ops/systemd")

    extracted_offsets: list[int] = []
    original_extractfile = tarfile.TarFile.extractfile

    def record_extractfile(archive: tarfile.TarFile, member: str | tarfile.TarInfo):
        info = archive.getmember(member) if isinstance(member, str) else member
        if info.name.startswith("payload/") and info.isfile():
            extracted_offsets.append(info.offset_data)
        return original_extractfile(archive, member)

    monkeypatch.setattr(tarfile.TarFile, "extractfile", record_extractfile)
    validate_recovery_bundle(bundle)

    assert extracted_offsets == sorted(extracted_offsets)


def test_recovery_bundle_rejects_corrupt_payload_before_restore(tmp_path: Path) -> None:
    install = _installation(tmp_path / "install")
    backup = create_recovery_bundle(install, tmp_path / "backups", service_dir=install / "ops/systemd")
    import tarfile

    corrupt = tmp_path / "corrupt.tar.gz"
    with tarfile.open(backup, "r:gz") as source, tarfile.open(corrupt, "w:gz") as target:
        for member in source.getmembers():
            content = source.extractfile(member) if member.isfile() else None
            if member.name.endswith("app/main.py"):
                content_data = b"tampered"
                member.size = len(content_data)
                import io
                target.addfile(member, io.BytesIO(content_data))
            else:
                target.addfile(member, content)
    with pytest.raises(RecoveryBundleError, match="checksum mismatch"):
        restore_recovery_bundle(corrupt, install, stop_services=lambda: False)


def test_v3_0_fixture_without_version_is_backed_up_and_restored_without_version(tmp_path: Path) -> None:
    fixture = InstallationRoot(tmp_path / "legacy").create_installed_v3_0()
    fixture.base_dir.joinpath("VERSION").unlink()
    bundle = create_recovery_bundle(fixture.base_dir, tmp_path / "backups", service_dir=fixture.base_dir / "ops/systemd")
    manifest, _ = validate_recovery_bundle(bundle)
    assert manifest["source"]["version"] == "3.0.0 (inferred from 7f22b48)"
    _write(fixture.base_dir / "VERSION", "failed-release\n")
    restore_recovery_bundle(
        bundle,
        fixture.base_dir,
        service_dir=tmp_path / "units",
        stop_services=lambda: True,
        reload_services=lambda: True,
        start_services=lambda: True,
        health_check=lambda: True,
    )
    assert not fixture.base_dir.joinpath("VERSION").exists()


def test_legacy_updater_characterization_uses_default_branch_and_omits_root_metadata() -> None:
    legacy_source = (Path(__file__).parent / "fixtures" / "legacy_v3_0_update.py").read_text(encoding="utf-8")
    assert '["git", "clone", "--depth", "1", git_repo, temp_dir]' in legacy_source
    legacy_update_code = legacy_source[legacy_source.index("def update_code("):]
    assert '"requirements.txt"' not in legacy_update_code
    assert '"VERSION"' not in legacy_update_code


def test_shell_update_entrypoint_only_dispatches_to_verified_cli(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "ops/scripts/update.sh"
    install = tmp_path / "install"
    install.mkdir()
    environment = dict(os.environ, INSTALL_DIR=str(install), MASCLONER_RELEASE_DIR=str(tmp_path / "release"))

    missing_cli = subprocess.run(["bash", str(script)], env=environment, capture_output=True, text=True)
    assert missing_cli.returncode != 0
    assert "verified" in missing_cli.stderr
    assert list(install.iterdir()) == []

    _write(install / "ops/cli/main.py", "")
    python = install / ".venv/bin/python"
    marker = tmp_path / "invocation.txt"
    _write(python, f'#!/bin/sh\nprintf "%s\\n" "$*" > "{marker}"\n')
    python.chmod(0o700)
    dispatched = subprocess.run(
        ["bash", str(script), "--check-only"], env=environment, capture_output=True, text=True
    )
    assert dispatched.returncode == 0
    assert marker.read_text(encoding="utf-8").strip() == "-m ops.cli.main update --check-only"


def test_update_failure_restores_the_pre_update_bundle(tmp_path: Path) -> None:
    install = _installation(tmp_path / "install")
    release = _release(tmp_path / "release", revision="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    _write(release / "app/main.py", "new")
    _release_manifest(release, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    health = lambda: True
    with pytest.raises(UpdateTransactionError, match="recovery succeeded"):
        run_update_transaction(
            release,
            install,
            tmp_path / "backups",
            install_dependencies=lambda _: False,
            run_migrations=lambda _: True,
            install_services=lambda _: True,
            stop_services=lambda: True,
            start_services=lambda: True,
            health_check=health,
            rollback_services_dir=tmp_path / "units",
        )
    assert (install / "app/main.py").read_text(encoding="utf-8") == "x"
    records = list((tmp_path / "backups/transactions").glob("*.json"))
    assert json.loads(records[0].read_text(encoding="utf-8"))["recovery"]["state"] == "completed"


def test_python_3_9_preflight_changes_nothing(tmp_path: Path) -> None:
    install = _installation(tmp_path / "install")
    fake_python = install / ".venv/bin/python"
    fake_python.unlink()
    _write(fake_python, "#!/bin/sh\necho 3.9\n")
    fake_python.chmod(0o700)
    release = _release(tmp_path / "release", revision="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    _release_manifest(release, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    with pytest.raises(UpdateTransactionError, match="Python 3.9 is incompatible"):
        run_update_transaction(
            release,
            install,
            tmp_path / "backups",
            install_dependencies=lambda _: (_ for _ in ()).throw(AssertionError("must not install")),
            run_migrations=lambda _: True,
            install_services=lambda _: True,
            stop_services=lambda: True,
            start_services=lambda: True,
            health_check=lambda: True,
        )
    assert (install / "app/main.py").read_text(encoding="utf-8") == "x"
    assert not (tmp_path / "backups/transactions").exists()


def test_failed_pre_mutation_backup_does_not_block_a_safe_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install = _installation(tmp_path / "install")
    release = _release(tmp_path / "release", revision="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    _release_manifest(release, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    monkeypatch.setattr(
        transaction_module,
        "create_recovery_bundle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RecoveryBundleError("disk full")),
    )
    with pytest.raises(UpdateTransactionError, match="no recovery needed.*installation unchanged"):
        run_update_transaction(
            release, install, tmp_path / "backups", install_dependencies=lambda _: True,
            run_migrations=lambda _: True, install_services=lambda _: True, stop_services=lambda: True,
            start_services=lambda: True, health_check=lambda: True,
        )
    monkeypatch.undo()
    result = run_update_transaction(
        release, install, tmp_path / "backups", install_dependencies=lambda _: True,
        run_migrations=lambda _: True, install_services=lambda _: True, stop_services=lambda: True,
        start_services=lambda: True, health_check=lambda: True, rollback_services_dir=tmp_path / "units",
    )
    assert result["state"] == "completed"


def test_subsequent_verified_update_publishes_version_after_qualification(tmp_path: Path) -> None:
    install = _installation(tmp_path / "install")
    release = _release(tmp_path / "release", revision="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    _write(release / "VERSION", "3.2.2\n")
    _write(release / "requirements.txt", "streamlit==1.63.0\n")
    _release_manifest(release, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    observed: list[tuple[str, str]] = []

    def dependencies(root: Path) -> bool:
        observed.append(((root / "VERSION").read_text(), (root / "requirements.txt").read_text()))
        return True

    result = run_update_transaction(
        release,
        install,
        tmp_path / "backups",
        install_dependencies=dependencies,
        run_migrations=lambda _: True,
        install_services=lambda _: True,
        stop_services=lambda: True,
        start_services=lambda: True,
        health_check=lambda: True,
        rollback_services_dir=tmp_path / "units",
    )
    assert observed == [("3.0.0\n", "streamlit==1.63.0\n")]
    assert result["state"] == "completed"
    assert (install / "VERSION").read_text(encoding="utf-8") == "3.2.2\n"
    assert (install / ".commit_hash").read_text(encoding="utf-8") == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"


@pytest.mark.parametrize(
    "failed_gate",
    ("dependencies", "migrations", "services", "start", "health"),
)
def test_every_hard_gate_recovers_the_pre_update_installation(tmp_path: Path, failed_gate: str) -> None:
    install = _installation(tmp_path / "install")
    release = _release(tmp_path / "release", revision="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    _write(release / "app/main.py", "new")
    _release_manifest(release, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")

    failed_once = False

    def gate(name: str) -> bool:
        nonlocal failed_once
        if name == failed_gate and not failed_once:
            failed_once = True
            return False
        return True

    with pytest.raises(UpdateTransactionError, match="recovery succeeded"):
        run_update_transaction(
            release,
            install,
            tmp_path / "backups",
            install_dependencies=lambda _: gate("dependencies"),
            run_migrations=lambda _: gate("migrations"),
            install_services=lambda _: gate("services"),
            stop_services=lambda: True,
            start_services=lambda: gate("start"),
            health_check=lambda: gate("health"),
            rollback_services_dir=tmp_path / "units",
        )
    record = json.loads(next((tmp_path / "backups/transactions").glob("*.json")).read_text(encoding="utf-8"))
    assert record["state"] == "failed"
    assert record["recovery"]["state"] == "completed"
    assert (install / "app/main.py").read_text(encoding="utf-8") == "x"


def test_keyboard_interrupt_recovers_and_records_the_interrupted_phase(tmp_path: Path) -> None:
    install = _installation(tmp_path / "install")
    release = _release(tmp_path / "release", revision="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    _release_manifest(release, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    with pytest.raises(KeyboardInterrupt):
        run_update_transaction(
            release,
            install,
            tmp_path / "backups",
            install_dependencies=lambda _: (_ for _ in ()).throw(KeyboardInterrupt()),
            run_migrations=lambda _: True,
            install_services=lambda _: True,
            stop_services=lambda: True,
            start_services=lambda: True,
            health_check=lambda: True,
            rollback_services_dir=tmp_path / "units",
        )
    record = json.loads(next((tmp_path / "backups/transactions").glob("*.json")).read_text(encoding="utf-8"))
    assert record["failed_phase"] == "release_installed"
    assert record["recovery"]["state"] == "completed"


def test_normal_cli_update_uses_the_verified_release_transaction(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install = _installation(tmp_path / "install")
    release = _release(tmp_path / "release", revision="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    _write(release / "requirements.txt", "streamlit==1.63.0\n")
    _release_manifest(release, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    observed: list[tuple[str, str]] = []
    current_user = pwd.getpwuid(os.getuid()).pw_name
    monkeypatch.setenv("INSTALL_DIR", str(install))
    monkeypatch.setenv("BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setenv("MASCLONER_RELEASE_DIR", str(release))
    monkeypatch.setenv("MASCLONER_SYSTEMD_DIR", str(tmp_path / "units"))
    monkeypatch.setattr(update_command, "require_root", lambda: None)
    monkeypatch.setattr(update_command, "get_mascloner_user", lambda: current_user)
    def record_dependencies(root: Path, _user: str, _layout: object = None) -> bool:
        observed.append(
            ((root / "VERSION").read_text(encoding="utf-8"), (root / "requirements.txt").read_text(encoding="utf-8"))
        )
        return True

    monkeypatch.setattr(update_command, "update_dependencies", record_dependencies)
    monkeypatch.setattr(update_command, "run_migrations", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(update_command, "update_systemd_services", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(update_command, "stop_all_services", lambda *_args: [("mascloner-api", "inactive", "stopped"), ("mascloner-ui", "inactive", "stopped"), ("mascloner-tunnel", "not_installed", "already stopped")])
    monkeypatch.setattr(update_command, "start_all_services", lambda *_args: [("mascloner-api", "active", "started"), ("mascloner-ui", "active", "started"), ("mascloner-tunnel", "not_installed", "started")])
    monkeypatch.setattr(update_command, "run_health_checks", lambda *_args: [("API", True, "ok"), ("UI", True, "ok")])
    result = CliRunner().invoke(cli_app, ["update", "--yes"])
    assert result.exit_code == 0, result.output
    assert observed == [("3.0.0\n", "streamlit==1.63.0\n")]


def test_standalone_bridge_upgrades_7f_shaped_fixture_from_checked_archive(tmp_path: Path) -> None:
    """Exercise the bridge seam with a 7f22b48-shaped isolated installation.

    This is intentionally not presented as a rehearsal against a full
    production installation image; release qualification needs that separate
    disposable-copy evidence.
    """
    install = _installation(tmp_path / "install", revision="7f22b48bd2c159d998120a39fd672e818910973a")
    (install / "VERSION").unlink()
    release = _release(tmp_path / "release", revision="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    _write(release / "app/main.py", "new")
    project_root = Path(__file__).resolve().parents[1]
    for relative in ("ops/cli/recovery.py", "ops/cli/transaction.py", "ops/cli/__init__.py"):
        source = project_root / relative
        target = release / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    _release_manifest(release, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    archive = tmp_path / "mascloner-3.2.2.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(release, arcname="mascloner-release")
    bridge = project_root / "ops/scripts/upgrade_v3_2.py"
    current_user = pwd.getpwuid(os.getuid()).pw_name
    invocation = f'''\
import importlib.util, sys
spec = importlib.util.spec_from_file_location("bridge", {str(bridge)!r})
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
bridge.require_root = lambda: None
bridge.command_ok = lambda *args, **kwargs: True
bridge.healthy = lambda: True
sys.argv = ["upgrade_v3_2.py", "--release-archive", {str(archive)!r}, "--sha256", {sha256_file(archive)!r}, "--install-dir", {str(install)!r}, "--backup-dir", {str(tmp_path / 'backups')!r}, "--systemd-dir", {str(tmp_path / 'units')!r}, "--user", {current_user!r}]
raise SystemExit(bridge.main())
'''
    result = subprocess.run([sys.executable, "-c", invocation], capture_output=True, text=True, cwd=project_root)
    assert result.returncode == 0, result.stderr
    assert "Installed 3.2.2 (bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb)" in result.stdout
    assert (install / "VERSION").read_text(encoding="utf-8") == "3.2.2\n"
    assert (install / ".commit_hash").read_text(encoding="utf-8") == "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"


def test_bridge_checksum_failure_leaves_v3_0_fixture_unchanged(tmp_path: Path) -> None:
    install = _installation(tmp_path / "install", revision="7f22b48bd2c159d998120a39fd672e818910973a")
    (install / "VERSION").unlink()
    archive = tmp_path / "bad.tar.gz"
    with tarfile.open(archive, "w:gz") as bundle:
        bundle.add(install, arcname="mascloner-release")
    bridge = Path(__file__).resolve().parents[1] / "ops/scripts/upgrade_v3_2.py"
    invocation = f'''\
import importlib.util, sys
spec = importlib.util.spec_from_file_location("bridge", {str(bridge)!r})
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
bridge.require_root = lambda: None
sys.argv = ["upgrade_v3_2.py", "--release-archive", {str(archive)!r}, "--sha256", "0" * 64, "--install-dir", {str(install)!r}]
bridge.main()
'''
    result = subprocess.run([sys.executable, "-c", invocation], capture_output=True, text=True, cwd=bridge.parents[2])
    assert result.returncode != 0
    assert not (install / "VERSION").exists()
    assert (install / ".commit_hash").read_text(encoding="utf-8").startswith("7f22b48")


def test_release_manifest_rejects_an_added_uninventoried_file(tmp_path: Path) -> None:
    release = _release(tmp_path / "release", revision="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    _release_manifest(release, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    _write(release / "app/injected.py", "unexpected")
    with pytest.raises(UpdateTransactionError, match="complete payload inventory"):
        validate_release(release)


@pytest.mark.parametrize("revision", ["main", "HEAD", "7f22b48", "A" * 40])
def test_release_manifest_rejects_mutable_or_noncanonical_revision(tmp_path: Path, revision: str) -> None:
    release = _release(tmp_path / "release", revision=revision)
    _release_manifest(release, revision)
    with pytest.raises(UpdateTransactionError, match="immutable revision"):
        validate_release(release)


def test_failed_recovery_does_not_publish_unqualified_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install = _installation(tmp_path / "install")
    release = _release(tmp_path / "release")
    _release_manifest(release, "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb")
    monkeypatch.setattr(
        transaction_module,
        "restore_recovery_bundle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RecoveryBundleError("recovery unavailable")),
    )
    with pytest.raises(UpdateTransactionError, match="recovery failed"):
        run_update_transaction(
            release, install, tmp_path / "backups", install_dependencies=lambda _: False,
            run_migrations=lambda _: True, install_services=lambda _: True, stop_services=lambda: True,
            start_services=lambda: True, health_check=lambda: True,
        )
    assert (install / "VERSION").read_text(encoding="utf-8") == "3.0.0\n"
    assert (install / ".commit_hash").read_text(encoding="utf-8") == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"


def test_partial_identity_publication_restores_both_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    install = _installation(tmp_path / "install")
    release = _release(tmp_path / "release")
    original_replace = Path.replace

    def fail_revision_publish(source: Path, target: Path) -> Path:
        if source.name.startswith(".commit_hash.tmp.") and target.name == ".commit_hash":
            raise OSError("revision publication failed")
        return original_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_revision_publish)
    with pytest.raises(OSError, match="revision publication failed"):
        transaction_module.publish_release_identity(release, install)
    assert (install / "VERSION").read_text(encoding="utf-8") == "3.0.0\n"
    assert (install / ".commit_hash").read_text(encoding="utf-8") == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
