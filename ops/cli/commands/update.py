"""Update command - Update MasCloner to the latest version."""
# Version: 3.2.0
# Last Updated: 2026-09-19

import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.request import ProxyHandler, Request, build_opener

import typer
from ops.cli.ui.layout import UpdateLayout
from ops.cli.ui.progress import (
    show_error,
    show_header,
    show_info,
    show_success,
)
from ops.cli.utils import (
    check_systemd_service,
    get_backup_dir,
    get_install_dir,
    get_mascloner_user,
    require_root,
    run_command,
    start_service,
    stop_service,
)
from ops.cli.transaction import (
    UpdateTransactionError,
    check_python_version,
    extract_verified_release,
    run_update_transaction,
    validate_release,
)

# Version information
UPDATE_CMD_VERSION = "3.2.0"
UPDATE_CMD_DATE = "2026-09-19"


def main(
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip confirmation prompts"
    ),
    check_only: bool = typer.Option(
        False, "--check-only", help="Only check for updates, don't install"
    ),
    skip_backup: bool = typer.Option(
        False, "--skip-backup", help="Skip backup creation (not recommended)"
    ),
    services_only: bool = typer.Option(
        False, "--services-only", help="Only update systemd service files"
    ),
    deps_only: bool = typer.Option(
        False, "--deps-only", help="Only update Python dependencies"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Show what would be done without making changes"
    )
):
    """
    Install a checksum-verified, immutable MasCloner release.

    The complete transaction backs up the current installation, installs
    the release and its dependencies, runs migrations, and checks service
    health. A failed phase restores the verified recovery bundle.
    """
    show_header(
        "MasCloner Update",
        f"Safely update your MasCloner installation to the latest version\nCLI Update Command v{UPDATE_CMD_VERSION} ({UPDATE_CMD_DATE})",
    )

    # Check prerequisites
    require_root()

    install_dir = get_install_dir()
    backup_dir = get_backup_dir()
    mascloner_user = get_mascloner_user()

    if not install_dir.exists():
        show_error(f"Installation not found at {install_dir}")
        raise typer.Exit(1)

    # v3.2 update sources are immutable release payloads.  Deliberately do
    # not fall back to a mutable default branch: that was the source of the
    # 3.1 dependency/code mismatch.
    release_dir = os.environ.get("MASCLONER_RELEASE_DIR")
    release_archive = os.environ.get("MASCLONER_RELEASE_ARCHIVE")
    release_sha256 = os.environ.get("MASCLONER_RELEASE_SHA256")
    if release_dir or release_archive:
        try:
            unsupported_modes = [
                flag
                for enabled, flag in (
                    (skip_backup, "--skip-backup"),
                    (services_only, "--services-only"),
                    (deps_only, "--deps-only"),
                )
                if enabled
            ]
            if unsupported_modes:
                raise UpdateTransactionError(
                    ", ".join(unsupported_modes)
                    + " cannot be used with verified v3.2 updates; run the complete transaction or use --check-only"
                )
            def install(source: Path) -> dict:
                if check_only or dry_run:
                    manifest = validate_release(source)
                    check_python_version(install_dir / ".venv" / "bin" / "python")
                    installed_revision = (install_dir / ".commit_hash").read_text(encoding="utf-8").strip()
                    state = "already current" if installed_revision == manifest["revision"] else "update available"
                    show_info(
                        f"Verified release {manifest['version']} ({manifest['revision'][:12]}): {state}. "
                        "No files or services were changed."
                    )
                    return {"source": {"version": manifest["version"], "revision": manifest["revision"]}, "state": state}
                return run_update_transaction(
                    source,
                    install_dir,
                    backup_dir,
                    install_dependencies=lambda root: update_dependencies(root, mascloner_user),
                    run_migrations=lambda root: run_migrations(root, mascloner_user),
                    install_services=update_systemd_services,
                    stop_services=lambda: _services_stopped(stop_all_services()),
                    start_services=lambda: _services_started(start_all_services()),
                    health_check=lambda: all(ok for _, ok, _ in run_health_checks()),
                    rollback_services_dir=Path(os.environ.get("MASCLONER_SYSTEMD_DIR", "/etc/systemd/system")),
                    owner=mascloner_user,
                )

            if release_archive:
                if not release_sha256:
                    raise UpdateTransactionError("MASCLONER_RELEASE_SHA256 is required with MASCLONER_RELEASE_ARCHIVE")
                with tempfile.TemporaryDirectory(prefix="mascloner-release-") as temporary:
                    source_dir = extract_verified_release(Path(release_archive), release_sha256, Path(temporary))
                    transaction = install(source_dir)
            else:
                # The directory form is only appropriate for a local/offline
                # artifact; RELEASE.json still verifies every payload file.
                assert release_dir is not None
                transaction = install(Path(release_dir))
        except UpdateTransactionError as exc:
            show_error(str(exc))
            raise typer.Exit(1)
        if transaction["state"] == "completed":
            show_success(
                f"Installed verified release {transaction['source']['version']} "
                f"({transaction['source']['revision'][:12]})"
            )
        else:
            show_info(
                f"Verified release {transaction['source']['version']} "
                f"({transaction['source']['revision'][:12]}): {transaction['state']}"
            )
        return
    show_error(
        "No immutable release source configured. Set MASCLONER_RELEASE_ARCHIVE and "
        "MASCLONER_RELEASE_SHA256, or MASCLONER_RELEASE_DIR for a local verified payload. "
        "Check-only and dry-run also require that immutable source."
    )
    raise typer.Exit(1)

def stop_all_services(layout: Optional[UpdateLayout] = None) -> List[Tuple[str, str, str]]:
    """Stop all MasCloner services."""
    services = ["mascloner-api", "mascloner-ui", "mascloner-tunnel"]
    results = []

    for service in services:
        is_running, status = check_systemd_service(service)
        if is_running:
            success = stop_service(service)
            action = "stopped" if success else "failed"
            results.append((service, "inactive" if success else "active", action))
            if layout:
                layout.add_log(f"{service}: {action}", style="green" if success else "red")
        else:
            results.append((service, status, "already stopped"))
            if layout:
                layout.add_log(f"{service}: already stopped", style="dim")

    return results


def _services_stopped(results: List[Tuple[str, str, str]]) -> bool:
    """Turn the presentation-oriented service result into a hard update gate."""
    states = {service: (status, action) for service, status, action in results}
    required = ("mascloner-api", "mascloner-ui")
    if any(states.get(service, ("missing", "failed"))[0] not in {"inactive", "stopped"} for service in required):
        return False
    return all(action != "failed" for _, _, action in results)


def start_all_services(layout: Optional[UpdateLayout] = None) -> List[Tuple[str, str, str]]:
    """Start all MasCloner services."""
    services = ["mascloner-api", "mascloner-ui", "mascloner-tunnel"]
    results = []

    for service in services:
        success = start_service(service)
        time.sleep(0.5)
        is_running, status = check_systemd_service(service)
        action = "started" if success and is_running else "failed"
        results.append((service, status, action))
        if layout:
            layout.add_log(f"{service}: {action}", style="green" if is_running else "red")

    return results


def _services_started(results: List[Tuple[str, str, str]]) -> bool:
    states = {service: status for service, status, _ in results}
    if any(states.get(service) != "active" for service in ("mascloner-api", "mascloner-ui")):
        return False
    return states.get("mascloner-tunnel") in {"active", "not_installed"}



def update_dependencies(
    install_dir: Path, user: str, layout: Optional[UpdateLayout] = None
) -> bool:
    """Update Python dependencies."""
    venv_pip = install_dir / ".venv" / "bin" / "pip"
    requirements = install_dir / "requirements.txt"

    if not requirements.exists():
        if layout:
            layout.add_log("Required requirements.txt is missing", style="red")
        return False

    try:
        exit_code, _, _ = run_command(
            ["sudo", "-u", user, str(venv_pip), "install", "-r", str(requirements)],
            check=False,
            capture=True,
        )
        
        if exit_code == 0:
            if layout:
                layout.add_log("Dependencies updated", style="green")
            return True
        else:
            if layout:
                layout.add_log("Some dependencies may have failed", style="yellow")
            return False
    except Exception as e:
        if layout:
            layout.add_log(f"Error updating dependencies: {e}", style="red")
        return False



def run_migrations(
    install_dir: Path, user: str, layout: Optional[UpdateLayout] = None
) -> bool:
    """Run the compatible-baseline schema classifier as a hard update gate."""
    python = install_dir / ".venv" / "bin" / "python"
    if not python.is_file():
        if layout:
            layout.add_log("Virtual-environment Python is missing", style="red")
        return False
    script = (
        "from pathlib import Path; from dotenv import load_dotenv; "
        f"root = Path({str(install_dir)!r}); load_dotenv(root / '.env'); "
        "from app.api.db import upgrade_database_to_head; import os, sys; "
        "sys.exit(0 if upgrade_database_to_head(os.environ.get('MASCLONER_DB_PATH', str(root / 'data/mascloner.db'))) else 1)"
    )
    exit_code, _, stderr = run_command(
        ["sudo", "-u", user, str(python), "-c", script],
        check=False,
        capture=True,
        cwd=str(install_dir),
    )
    if exit_code == 0:
        if layout:
            layout.add_log("Migrations completed successfully", style="green")
        return True
    if layout:
        layout.add_log(f"Migration failed: {stderr[:160]}", style="red")
    return False


def update_systemd_services(
    install_dir: Path, layout: Optional[UpdateLayout] = None
) -> bool:
    """Update systemd service files if needed."""
    service_dir = Path(os.environ.get("MASCLONER_SYSTEMD_DIR", "/etc/systemd/system"))
    source_services = install_dir / "ops" / "systemd"

    if not source_services.exists():
        if layout:
            layout.add_log("Required service files are missing", style="red")
        return False

    updated = False
    failed = False
    for service_file in source_services.glob("mascloner-*.service"):
        dest = service_dir / service_file.name
        try:
            shutil.copy(service_file, dest)
            updated = True
            if layout:
                layout.add_log(f"Updated {service_file.name}", style="green")
        except Exception as e:
            failed = True
            if layout:
                layout.add_log(f"Failed to update {service_file.name}: {e}", style="red")

    if updated:
        exit_code, _, _ = run_command(["systemctl", "daemon-reload"], check=False)
        if exit_code != 0:
            failed = True
        if layout:
            layout.add_log("Reloaded systemd daemon", style="dim")

    return not failed


def _check_endpoint_with_retry(
    name: str,
    url: str,
    *,
    timeout: int = 5,
    attempts: int = 10,
    delay: float = 3.0,
    layout: Optional[UpdateLayout] = None,
) -> Tuple[bool, str]:
    """Probe an HTTP endpoint with retry logic, bypassing proxies."""

    opener = build_opener(ProxyHandler({}))
    last_error: Optional[str] = None

    for attempt in range(1, attempts + 1):
        try:
            request = Request(url, method="GET")
            response = opener.open(request, timeout=timeout)
            status_code = getattr(response, "status", None)
            if status_code is None and hasattr(response, "getcode"):
                status_code = response.getcode()
            response.close()

            detail = f"{url} (HTTP {status_code})" if status_code else url
            if layout:
                suffix = f" after {attempt} attempt{'s' if attempt > 1 else ''}" if attempt > 1 else ""
                layout.add_log(f"{name} healthy{suffix}", style="green")
            return True, detail
        except Exception as exc:  # pragma: no cover - network timing
            last_error = str(exc)
            if layout and attempt < attempts:
                layout.add_log(
                    f"{name} check {attempt}/{attempts} failed: {last_error}",
                    style="yellow",
                )
            if attempt < attempts:
                time.sleep(delay)

    if layout:
        layout.add_log(
            f"{name} unhealthy after {attempts} attempts: {last_error or 'no response'}",
            style="red",
        )
    return False, f"{url} ({last_error or 'no response'})"


def run_health_checks(layout: Optional[UpdateLayout] = None) -> List[Tuple[str, bool, str]]:
    """Run post-update health checks using HTTP endpoints only."""

    endpoints: List[Tuple[str, str]] = [
        ("API Health", "http://127.0.0.1:8787/health"),
        ("API Status", "http://127.0.0.1:8787/status"),
        ("UI", "http://127.0.0.1:8501"),
    ]

    checks: List[Tuple[str, bool, str]] = []
    for name, url in endpoints:
        ok, detail = _check_endpoint_with_retry(
            name,
            url,
            timeout=5,
            attempts=10,
            delay=3.0,
            layout=layout,
        )
        checks.append((name, ok, detail))

    return checks
