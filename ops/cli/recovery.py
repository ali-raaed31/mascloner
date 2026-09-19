"""Verified recovery bundles used by the updater and rollback command.

The bundle deliberately has a small, explicit format.  It is produced before
an update mutates the installation and it is validated *before* rollback stops
a service.  Keeping this code independent of the running application makes it
usable while the application itself is damaged.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import stat
import tarfile
import pwd
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable


BUNDLE_FORMAT = 1
PAYLOAD_ROOT = "payload"
MANIFEST_NAME = "manifest.json"
REQUIRED_RUNTIME_PATHS = (
    "app",
    "ops",
    "alembic",
    "alembic.ini",
    "requirements.txt",
    ".commit_hash",
    ".env",
    "etc/rclone.conf",
    ".venv",
)
MANAGED_RUNTIME_PATHS = (
    "app",
    "ops",
    "alembic",
    "alembic.ini",
    "requirements.txt",
    "VERSION",
    ".commit_hash",
    ".env",
    ".env.example",
    ".venv",
    "tests",
    "data",
    "etc",
)
SERVICES = ("mascloner-api", "mascloner-ui", "mascloner-tunnel")


class RecoveryBundleError(RuntimeError):
    """The requested recovery operation cannot safely continue."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_path(source: Path, destination: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, destination, symlinks=False)
    else:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination, follow_symlinks=False)


def set_tree_owner(root: Path, user: str | None) -> None:
    """Restore runtime ownership before services run as the MasCloner user."""
    if user is None:
        return
    try:
        account = pwd.getpwnam(user)
    except KeyError as exc:
        raise RecoveryBundleError(f"recovery owner does not exist: {user}") from exc
    for path in [root, *root.rglob("*")]:
        if not path.is_symlink():
            os.chown(path, account.pw_uid, account.pw_gid)


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) in {"", "."}:
        raise RecoveryBundleError(f"unsafe bundle member: {value!r}")
    return path


def _verify_sqlite(db_path: Path) -> None:
    if not db_path.is_file():
        raise RecoveryBundleError("recovery database artifact is missing")
    try:
        connection = sqlite3.connect(str(db_path))
        try:
            if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise RecoveryBundleError("recovery database integrity check failed")
            if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
                raise RecoveryBundleError("recovery database foreign-key check failed")
            connection.execute("SELECT count(*) FROM config").fetchone()
            connection.execute("SELECT count(*) FROM runs").fetchone()
            connection.execute("SELECT count(*) FROM file_events").fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise RecoveryBundleError(f"recovery database cannot be read: {exc}") from exc


def _online_sqlite_backup(source: Path, target: Path) -> None:
    if not source.is_file():
        raise RecoveryBundleError(f"live database is missing: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.tmp.{os.getpid()}")
    try:
        source_connection = sqlite3.connect(str(source), timeout=30)
        target_connection = sqlite3.connect(str(temporary))
        try:
            source_connection.backup(target_connection, pages=100)
            target_connection.commit()
        finally:
            target_connection.close()
            source_connection.close()
        os.chmod(temporary, 0o600)
        _verify_sqlite(temporary)
        temporary.replace(target)
        os.chmod(target, 0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _inventory(payload: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in sorted(payload.rglob("*")):
        if item.is_file():
            result[item.relative_to(payload).as_posix()] = _sha256(item)
    return result


def _required_present(payload: Path) -> None:
    missing = [path for path in REQUIRED_RUNTIME_PATHS if not (payload / path).exists()]
    if missing:
        raise RecoveryBundleError("installation is incomplete; cannot create recovery bundle: " + ", ".join(missing))


def _installed_version(install_dir: Path) -> str:
    version_path = install_dir / "VERSION"
    if version_path.is_file():
        return version_path.read_text(encoding="utf-8").strip()
    revision_path = install_dir / ".commit_hash"
    revision = revision_path.read_text(encoding="utf-8").strip() if revision_path.is_file() else ""
    # v3.0's updater did not reliably install VERSION.  Preserve that absence
    # in the payload while retaining the known source identity in the manifest.
    if revision.startswith("7f22b48"):
        return "3.0.0 (inferred from 7f22b48)"
    return "unknown (VERSION absent)"


def create_recovery_bundle(
    install_dir: Path,
    backup_dir: Path,
    *,
    service_dir: Path | None = None,
) -> Path:
    """Create a verified, private recovery bundle without tarring a live WAL DB."""
    install_dir = install_dir.resolve()
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(backup_dir, 0o700)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final_path = backup_dir / f"mascloner-recovery-{timestamp}.tar.gz"
    if final_path.exists():
        raise RecoveryBundleError(f"recovery bundle already exists: {final_path}")

    with tempfile.TemporaryDirectory(prefix="mascloner-recovery-", dir=backup_dir) as work:
        work_path = Path(work)
        payload = work_path / PAYLOAD_ROOT
        payload.mkdir(mode=0o700)
        _required_present(install_dir)

        for relative in MANAGED_RUNTIME_PATHS:
            source = install_dir / relative
            if relative == "data":
                continue
            if source.exists():
                _copy_path(source, payload / relative)
        _online_sqlite_backup(install_dir / "data" / "mascloner.db", payload / "data" / "mascloner.db")

        release_service_source = install_dir / "ops" / "systemd"
        if not release_service_source.is_dir():
            raise RecoveryBundleError("installed service definitions are missing")
        service_source = service_dir or Path(os.environ.get("MASCLONER_SYSTEMD_DIR", "/etc/systemd/system"))
        bundle_services = payload / "systemd"
        bundle_services.mkdir()
        for service in SERVICES:
            source = service_source / f"{service}.service"
            if not source.is_file():
                source = release_service_source / f"{service}.service"
            if source.is_file():
                _copy_path(source, bundle_services / source.name)

        manifest = {
            "format": BUNDLE_FORMAT,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": {
                "version": _installed_version(install_dir),
                "revision": (install_dir / ".commit_hash").read_text(encoding="utf-8").strip(),
            },
            "database": {"path": "data/mascloner.db", "verified": True},
            "inventory": _inventory(payload),
        }
        manifest_path = work_path / MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(manifest_path, 0o600)

        temporary_bundle = backup_dir / f".{final_path.name}.tmp.{os.getpid()}"
        try:
            with tarfile.open(temporary_bundle, "w:gz", format=tarfile.PAX_FORMAT) as archive:
                archive.add(manifest_path, arcname=MANIFEST_NAME, recursive=False)
                archive.add(payload, arcname=PAYLOAD_ROOT, recursive=True, filter=_tar_filter)
            os.chmod(temporary_bundle, 0o600)
            validate_recovery_bundle(temporary_bundle)
            temporary_bundle.replace(final_path)
            os.chmod(final_path, 0o600)
        except Exception:
            temporary_bundle.unlink(missing_ok=True)
            raise
    return final_path


def _tar_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    if "__pycache__" in PurePosixPath(info.name).parts or info.name.endswith(".pyc"):
        return None
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def _validate_members(archive: tarfile.TarFile) -> None:
    names: set[str] = set()
    for member in archive.getmembers():
        _safe_relative(member.name)
        if member.name in names:
            raise RecoveryBundleError(f"duplicate archive member: {member.name}")
        names.add(member.name)
        if member.issym() or member.islnk() or member.isdev() or member.isfifo():
            raise RecoveryBundleError(f"unsafe archive member type: {member.name}")
        if not (member.isdir() or member.isfile()):
            raise RecoveryBundleError(f"unsupported archive member type: {member.name}")
    if MANIFEST_NAME not in names:
        raise RecoveryBundleError("bundle manifest is missing")


def validate_recovery_bundle(bundle_path: Path, extract_to: Path | None = None) -> tuple[dict[str, Any], Path | None]:
    """Validate a bundle before service interruption; optionally extract safely."""
    if not bundle_path.is_file():
        raise RecoveryBundleError(f"recovery bundle does not exist: {bundle_path}")
    with tarfile.open(bundle_path, "r:gz") as archive:
        _validate_members(archive)
        manifest_file = archive.extractfile(MANIFEST_NAME)
        if manifest_file is None:
            raise RecoveryBundleError("bundle manifest is unreadable")
        try:
            manifest = json.load(manifest_file)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RecoveryBundleError("bundle manifest is invalid JSON") from exc
        if manifest.get("format") != BUNDLE_FORMAT or not isinstance(manifest.get("inventory"), dict):
            raise RecoveryBundleError("unsupported or invalid recovery bundle format")
        source_identity = manifest.get("source")
        database = manifest.get("database")
        if (
            not isinstance(source_identity, dict)
            or not isinstance(source_identity.get("version"), str)
            or not source_identity["version"]
            or not isinstance(source_identity.get("revision"), str)
            or not source_identity["revision"]
            or not isinstance(database, dict)
            or database.get("path") != "data/mascloner.db"
            or database.get("verified") is not True
        ):
            raise RecoveryBundleError("bundle manifest is missing required source or database identity")
        if not manifest["inventory"]:
            raise RecoveryBundleError("bundle manifest inventory is empty")
        for name, digest in manifest["inventory"].items():
            if not isinstance(name, str) or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise RecoveryBundleError("bundle manifest has an invalid checksum entry")
        names = {member.name for member in archive.getmembers() if member.isfile()}
        expected = {f"{PAYLOAD_ROOT}/{name}" for name in manifest["inventory"]}
        if expected != names - {MANIFEST_NAME}:
            raise RecoveryBundleError("bundle inventory does not match archive payload")
        for name, digest in manifest["inventory"].items():
            _safe_relative(name)
            source = archive.extractfile(f"{PAYLOAD_ROOT}/{name}")
            if source is None:
                raise RecoveryBundleError(f"bundle payload is missing: {name}")
            hasher = hashlib.sha256()
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                hasher.update(chunk)
            if hasher.hexdigest() != digest:
                raise RecoveryBundleError(f"bundle checksum mismatch: {name}")
        for required in REQUIRED_RUNTIME_PATHS + ("data/mascloner.db", "systemd"):
            prefix = f"{PAYLOAD_ROOT}/{required}"
            if not any(name == prefix or name.startswith(prefix + "/") for name in names):
                raise RecoveryBundleError(f"bundle required payload is missing: {required}")
        if extract_to is not None:
            extract_to.mkdir(parents=True, exist_ok=False, mode=0o700)
            for member in archive.getmembers():
                destination = extract_to / _safe_relative(member.name)
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    content = archive.extractfile(member)
                    if content is None:
                        raise RecoveryBundleError(f"could not extract {member.name}")
                    with destination.open("wb") as target:
                        shutil.copyfileobj(content, target)
                    os.chmod(destination, stat.S_IMODE(member.mode) & 0o700 or 0o600)
    return manifest, extract_to


def restore_recovery_bundle(
    bundle_path: Path,
    install_dir: Path,
    *,
    service_dir: Path = Path("/etc/systemd/system"),
    stop_services: Callable[[], bool] | None = None,
    reload_services: Callable[[], bool] | None = None,
    start_services: Callable[[], bool] | None = None,
    health_check: Callable[[], bool] | None = None,
    owner: str | None = None,
) -> dict[str, Any]:
    """Restore a verified bundle using a private staging tree.

    Validation and extraction occur before the caller stops services.  The
    replacement is exact for all managed installation paths so stale files from
    a failed release cannot survive a rollback.
    """
    install_dir = install_dir.resolve()
    with tempfile.TemporaryDirectory(prefix="mascloner-restore-", dir=install_dir.parent) as work:
        staging = Path(work) / "bundle"
        manifest, _ = validate_recovery_bundle(bundle_path, staging)
        payload = staging / PAYLOAD_ROOT
        _verify_sqlite(payload / "data" / "mascloner.db")
        if stop_services is not None and not stop_services():
            raise RecoveryBundleError("could not stop all services before rollback")

        for relative in MANAGED_RUNTIME_PATHS:
            target = install_dir / relative
            if target.exists() or target.is_symlink():
                if target.is_dir() and not target.is_symlink():
                    shutil.rmtree(target)
                else:
                    target.unlink()
        for relative in MANAGED_RUNTIME_PATHS:
            source = payload / relative
            if source.exists():
                _copy_path(source, install_dir / relative)

        set_tree_owner(install_dir, owner)

        service_dir.mkdir(parents=True, exist_ok=True)
        for service in SERVICES:
            destination = service_dir / f"{service}.service"
            source = payload / "systemd" / destination.name
            if source.exists():
                shutil.copy2(source, destination)
            else:
                destination.unlink(missing_ok=True)
        _verify_sqlite(install_dir / "data" / "mascloner.db")
        if reload_services is not None and not reload_services():
            raise RecoveryBundleError("systemd daemon reload failed after rollback")
        if start_services is not None and not start_services():
            raise RecoveryBundleError("restored services did not start")
        if health_check is not None and not health_check():
            raise RecoveryBundleError("restored API/UI health check failed")
    return {"source": manifest["source"], "bundle": str(bundle_path), "restored": True}
