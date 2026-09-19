"""Immutable release installation and fail-closed update transactions."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from ops.cli.recovery import (
    MANAGED_RUNTIME_PATHS,
    create_recovery_bundle,
    restore_recovery_bundle,
    set_tree_owner,
)


RELEASE_MANIFEST = "RELEASE.json"
REQUIRED_RELEASE_PATHS = (
    "app",
    "ops",
    "alembic",
    "alembic.ini",
    "requirements.txt",
    "VERSION",
    ".commit_hash",
    "ops/systemd/mascloner-api.service",
    "ops/systemd/mascloner-ui.service",
)


class UpdateTransactionError(RuntimeError):
    """An update did not qualify and was recovered or needs recovery."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)


def validate_release(source_dir: Path) -> dict[str, Any]:
    """Validate the signed-by-checksum release payload before mutating a host."""
    manifest_path = source_dir / RELEASE_MANIFEST
    if not manifest_path.is_file():
        raise UpdateTransactionError(f"release manifest is missing: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UpdateTransactionError("release manifest is invalid") from exc
    if (
        manifest.get("format") != 1
        or not isinstance(manifest.get("version"), str)
        or not manifest["version"].strip()
        or not isinstance(manifest.get("revision"), str)
        or not manifest["revision"].strip()
        or any(character.isspace() for character in manifest["revision"])
    ):
        raise UpdateTransactionError("release manifest needs format 1, version, and immutable revision")
    inventory = manifest.get("inventory")
    if not isinstance(inventory, dict) or not inventory:
        raise UpdateTransactionError("release manifest needs a non-empty checksum inventory")
    for required in REQUIRED_RELEASE_PATHS:
        if not (source_dir / required).exists():
            raise UpdateTransactionError(f"release payload is missing required path: {required}")
    actual_files = {
        path.relative_to(source_dir).as_posix()
        for path in source_dir.rglob("*")
        if path.is_file() and path.name != RELEASE_MANIFEST
    }
    if set(inventory) != actual_files:
        raise UpdateTransactionError("release manifest inventory is not a complete payload inventory")
    if (source_dir / "VERSION").read_text(encoding="utf-8").strip() != manifest["version"]:
        raise UpdateTransactionError("release manifest version does not match VERSION")
    if (source_dir / ".commit_hash").read_text(encoding="utf-8").strip() != manifest["revision"]:
        raise UpdateTransactionError("release manifest revision does not match .commit_hash")
    for relative, expected in inventory.items():
        candidate = source_dir / relative
        if not isinstance(relative, str) or not isinstance(expected, str) or not candidate.is_file():
            raise UpdateTransactionError(f"release inventory entry is invalid: {relative!r}")
        if candidate.resolve().parent != source_dir.resolve() and source_dir.resolve() not in candidate.resolve().parents:
            raise UpdateTransactionError(f"release inventory escapes payload: {relative!r}")
        if sha256_file(candidate) != expected:
            raise UpdateTransactionError(f"release checksum mismatch: {relative}")
    return manifest


def extract_verified_release(archive_path: Path, expected_sha256: str, destination: Path) -> Path:
    """Verify an externally supplied archive digest and extract it safely."""
    if sha256_file(archive_path) != expected_sha256.lower():
        raise UpdateTransactionError("release archive SHA-256 does not match the supplied checksum")
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        roots: set[str] = set()
        names: set[str] = set()
        for member in members:
            path = PurePosixPath(member.name)
            if (
                not member.name
                or path.is_absolute()
                or ".." in path.parts
                or not path.parts
                or not (member.isdir() or member.isfile())
            ):
                raise UpdateTransactionError(f"unsafe release archive member: {member.name}")
            canonical_name = path.as_posix()
            if canonical_name in names:
                raise UpdateTransactionError(f"duplicate release archive member: {member.name}")
            names.add(canonical_name)
            roots.add(path.parts[0])
        if len(roots) != 1:
            raise UpdateTransactionError("release archive must contain exactly one top-level directory")
        for member in members:
            target = destination.joinpath(*PurePosixPath(member.name).parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                raise UpdateTransactionError(f"unreadable release archive member: {member.name}")
            with source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
            os.chmod(target, member.mode & 0o755 or 0o600)
    return destination / next(iter(roots))


def check_python_version(python: Path) -> tuple[int, int]:
    import subprocess

    try:
        result = subprocess.run(
            [str(python), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            check=True,
            capture_output=True,
            text=True,
        )
        major, minor = result.stdout.strip().split(".", maxsplit=1)
        version = (int(major), int(minor))
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise UpdateTransactionError(f"could not determine installed Python version at {python}") from exc
    if version < (3, 10):
        raise UpdateTransactionError(
            f"Python {version[0]}.{version[1]} is incompatible; create a Python 3.10+ virtual environment before updating"
        )
    return version


def install_release(source_dir: Path, install_dir: Path) -> None:
    """Replace release-owned paths together while retaining operator data and venv."""
    release_paths = tuple(path for path in MANAGED_RUNTIME_PATHS if path not in {".venv", "data", "etc", ".env"})
    for relative in release_paths:
        target = install_dir / relative
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        elif target.exists() or target.is_symlink():
            target.unlink()
    for relative in release_paths:
        source = source_dir / relative
        if source.is_dir():
            shutil.copytree(source, install_dir / relative, symlinks=False)
        elif source.is_file():
            shutil.copy2(source, install_dir / relative)


def run_update_transaction(
    source_dir: Path,
    install_dir: Path,
    backup_dir: Path,
    *,
    install_dependencies: Callable[[Path], bool],
    run_migrations: Callable[[Path], bool],
    install_services: Callable[[Path], bool],
    stop_services: Callable[[], bool],
    start_services: Callable[[], bool],
    health_check: Callable[[], bool],
    rollback_services_dir: Path = Path("/etc/systemd/system"),
    owner: str | None = None,
) -> dict[str, Any]:
    """Install an immutable release or restore the exact pre-update bundle."""
    source_dir = source_dir.resolve()
    install_dir = install_dir.resolve()
    manifest = validate_release(source_dir)
    python_version = check_python_version(install_dir / ".venv" / "bin" / "python")
    transaction_dir = backup_dir / "transactions"
    if transaction_dir.exists():
        for previous_path in sorted(transaction_dir.glob("*.json")):
            try:
                previous = json.loads(previous_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raise UpdateTransactionError(f"unreadable prior update transaction: {previous_path}")
            recovery = previous.get("recovery", {})
            if previous.get("state") == "incomplete" or (
                previous.get("state") == "failed"
                and previous.get("failed_phase") != "validated"
                and recovery.get("state") != "completed"
            ):
                recovery_reference = previous.get("recovery_bundle", "no verified recovery bundle recorded")
                raise UpdateTransactionError(
                    f"unresolved prior update transaction: {previous_path}; recover from {recovery_reference} before updating"
                )
    transaction_path = transaction_dir / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}.json"
    transaction: dict[str, Any] = {
        "format": 1,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "state": "incomplete",
        "phase": "validated",
        "source": {"version": manifest["version"], "revision": manifest["revision"]},
        "python": f"{python_version[0]}.{python_version[1]}",
    }
    _write_json(transaction_path, transaction)
    bundle: Path | None = None
    try:
        bundle = create_recovery_bundle(install_dir, backup_dir)
        transaction.update({"phase": "backup_created", "recovery_bundle": str(bundle)})
        _write_json(transaction_path, transaction)
        if not stop_services():
            raise UpdateTransactionError("could not stop all services")
        transaction["phase"] = "services_stopped"
        _write_json(transaction_path, transaction)
        install_release(source_dir, install_dir)
        set_tree_owner(install_dir, owner)
        transaction["phase"] = "release_installed"
        _write_json(transaction_path, transaction)
        if not install_dependencies(install_dir):
            raise UpdateTransactionError("dependency installation failed")
        transaction["phase"] = "dependencies_installed"
        _write_json(transaction_path, transaction)
        if not run_migrations(install_dir):
            raise UpdateTransactionError("database migration failed")
        transaction["phase"] = "migrations_applied"
        _write_json(transaction_path, transaction)
        if not install_services(install_dir):
            raise UpdateTransactionError("systemd unit installation failed")
        transaction["phase"] = "services_installed"
        _write_json(transaction_path, transaction)
        if not start_services():
            raise UpdateTransactionError("service start failed")
        if not health_check():
            raise UpdateTransactionError("API/UI health checks failed")
        transaction.update({"state": "completed", "phase": "qualified", "completed_at": datetime.now(timezone.utc).isoformat()})
        _write_json(transaction_path, transaction)
        return transaction
    except BaseException as exc:
        transaction.update({"state": "failed", "failure": str(exc), "failed_phase": transaction["phase"]})
        if bundle is None and transaction["phase"] == "validated":
            transaction["recovery"] = {"state": "not_required", "reason": "no installation mutation occurred"}
        elif bundle is not None:
            try:
                result = restore_recovery_bundle(
                    bundle,
                    install_dir,
                    service_dir=rollback_services_dir,
                    stop_services=stop_services,
                    reload_services=lambda: install_services(install_dir),
                    start_services=start_services,
                    health_check=health_check,
                    owner=owner,
                )
                transaction["recovery"] = {"state": "completed", **result}
            except Exception as rollback_exc:
                transaction["recovery"] = {"state": "failed", "reason": str(rollback_exc)}
        _write_json(transaction_path, transaction)
        if isinstance(exc, KeyboardInterrupt):
            raise
        recovery = transaction.get("recovery", {})
        suffix = "; recovery succeeded" if recovery.get("state") == "completed" else "; recovery failed"
        raise UpdateTransactionError(f"update failed during {transaction['failed_phase']}: {exc}{suffix}") from exc
