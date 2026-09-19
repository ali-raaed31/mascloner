#!/usr/bin/env python3
"""One-time bridge from the unmodified v3.0 CLI updater to v3.2.

Run this script directly, rather than ``mascloner update``, on installations
whose updater predates v3.2.  The release archive digest is checked before its
Python code is imported, so the installed v3.0 updater is never executed.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-archive", type=Path, required=True)
    parser.add_argument("--sha256", required=True, help="SHA-256 from the v3.2 release checksums file")
    parser.add_argument("--install-dir", type=Path, default=Path("/srv/mascloner"))
    parser.add_argument("--backup-dir", type=Path, default=Path("/var/backups/mascloner"))
    parser.add_argument("--user", default="mascloner")
    parser.add_argument("--systemd-dir", type=Path, default=Path("/etc/systemd/system"))
    return parser.parse_args()


def require_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit("run this bridge as root, for example: sudo python3 upgrade_v3_2.py ...")


def command_ok(command: list[str], *, cwd: Path | None = None) -> bool:
    return subprocess.run(command, cwd=cwd, check=False).returncode == 0


def archive_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_checked_archive(archive_path: Path, expected_sha256: str, destination: Path) -> Path:
    if archive_digest(archive_path) != expected_sha256.lower():
        raise SystemExit("release archive SHA-256 does not match the supplied checksum")
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        roots = {Path(member.name).parts[0] for member in members if member.name}
        if len(roots) != 1:
            raise SystemExit("release archive must contain exactly one top-level directory")
        for member in members:
            path = Path(member.name)
            if path.is_absolute() or ".." in path.parts or member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise SystemExit(f"unsafe release archive member: {member.name}")
        archive.extractall(destination, filter="data")
    return destination / next(iter(roots))


def managed_services() -> tuple[str, ...]:
    required = ("mascloner-api", "mascloner-ui")
    if not all(command_ok(["systemctl", "cat", f"{service}.service"]) for service in required):
        return ()
    services = list(required)
    if command_ok(["systemctl", "cat", "mascloner-tunnel.service"]):
        services.append("mascloner-tunnel")
    return tuple(services)


def services_stopped() -> bool:
    services = managed_services()
    if not services:
        return False
    outcomes = [command_ok(["systemctl", "stop", f"{service}.service"]) for service in services]
    return all(outcomes)


def services_started() -> bool:
    services = managed_services()
    if not services:
        return False
    outcomes = []
    for service in services:
        outcomes.append(command_ok(["systemctl", "start", f"{service}.service"]))
    if not all(outcomes):
        return False
    return all(command_ok(["systemctl", "is-active", "--quiet", f"{service}.service"]) for service in services)


def healthy() -> bool:
    opener = build_opener(ProxyHandler({}))
    urls = ("http://127.0.0.1:8787/health", "http://127.0.0.1:8787/status", "http://127.0.0.1:8501")
    for _ in range(12):
        passed = True
        for url in urls:
            try:
                response = opener.open(Request(url, method="GET"), timeout=5)
                response.close()
            except Exception:
                passed = False
                break
        if passed:
            return True
        time.sleep(5)
    return False


def main() -> int:
    args = parse_args()
    require_root()
    if not args.release_archive.is_file():
        raise SystemExit(f"release archive not found: {args.release_archive}")
    if not args.install_dir.is_dir():
        raise SystemExit(f"installation not found: {args.install_dir}")

    # Import exclusively from a checksum-verified extraction.  This prevents
    # accidental execution of the old installed update module.
    with tempfile.TemporaryDirectory(prefix="mascloner-v3_2-bridge-") as temp:
        temporary_root = Path(temp)
        release_dir = extract_checked_archive(args.release_archive, args.sha256, temporary_root / "release")
        sys.path.insert(0, str(release_dir))
        sys.dont_write_bytecode = True
        from ops.cli.transaction import run_update_transaction

        def dependencies(root: Path) -> bool:
            return command_ok(["sudo", "-u", args.user, str(root / ".venv/bin/pip"), "install", "-r", str(root / "requirements.txt")])

        def migrations(root: Path) -> bool:
            script = (
                "from pathlib import Path; from dotenv import load_dotenv; "
                f"root = Path({str(root)!r}); load_dotenv(root / '.env'); "
                "from app.api.db import upgrade_database_to_head; import os, sys; "
                "sys.exit(0 if upgrade_database_to_head(os.environ.get('MASCLONER_DB_PATH', str(root / 'data/mascloner.db'))) else 1)"
            )
            return command_ok(["sudo", "-u", args.user, str(root / ".venv/bin/python"), "-c", script], cwd=root)

        def install_services(root: Path) -> bool:
            try:
                args.systemd_dir.mkdir(parents=True, exist_ok=True)
                for unit in (root / "ops/systemd").glob("mascloner-*.service"):
                    shutil.copy2(unit, args.systemd_dir / unit.name)
            except OSError:
                return False
            return command_ok(["systemctl", "daemon-reload"])

        result = run_update_transaction(
            release_dir,
            args.install_dir,
            args.backup_dir,
            install_dependencies=dependencies,
            run_migrations=migrations,
            install_services=install_services,
            stop_services=services_stopped,
            start_services=services_started,
            health_check=healthy,
            rollback_services_dir=args.systemd_dir,
            owner=args.user,
        )
    print(f"Installed {result['source']['version']} ({result['source']['revision']})")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
