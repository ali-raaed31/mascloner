"""Update command - Update MasCloner to the latest version."""
import shutil
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Tuple

import typer
from rich.console import Console

from ops.cli.ui.panels import (
    show_changelog,
    show_completion_summary,
    show_confirmation_prompt,
    show_error_recovery,
    show_next_steps,
    show_service_logs,
    show_version_info,
)
from ops.cli.ui.progress import (
    StepIndicator,
    show_error,
    show_header,
    show_info,
    show_success,
    show_warning,
    spinner,
)
from ops.cli.ui.tables import (
    create_backup_info_table,
    create_file_changes_table,
    create_health_check_table,
    create_service_status_table,
)
from ops.cli.utils import (
    check_http_endpoint,
    check_systemd_service,
    compare_directories,
    create_backup,
    get_backup_dir,
    get_file_size_human,
    get_git_repo,
    get_install_dir,
    get_mascloner_user,
    get_service_logs,
    require_root,
    run_command,
    start_service,
    stop_service,
)

console = Console()


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
    ),
):
    """
    Update MasCloner to the latest version.
    
    This command will:
    - Check for available updates
    - Create a backup of your installation
    - Stop running services
    - Update code and dependencies
    - Restart services
    - Run health checks
    """
    start_time = time.time()

    # Show header
    show_header(
        "MasCloner Update",
        "Safely update your MasCloner installation to the latest version",
    )

    # Check prerequisites
    require_root()

    install_dir = get_install_dir()
    backup_dir = get_backup_dir()
    git_repo = get_git_repo()
    mascloner_user = get_mascloner_user()

    if not install_dir.exists():
        show_error(f"Installation not found at {install_dir}")
        raise typer.Exit(1)

    if dry_run:
        show_info("Running in DRY RUN mode - no changes will be made")
        console.print()

    # Initialize step tracker
    steps = StepIndicator(10)
    steps.add_step("Check prerequisites")
    steps.add_step("Check for updates")
    steps.add_step("Create backup")
    steps.add_step("Stop services")
    steps.add_step("Update code")
    steps.add_step("Update dependencies")
    steps.add_step("Run migrations")
    steps.add_step("Update services")
    steps.add_step("Start services")
    steps.add_step("Health check")

    current_step = 0
    warnings: List[str] = []
    backup_path: Optional[Path] = None

    try:
        # Step 1: Prerequisites
        steps.start_step(current_step)
        console.print(steps.render())
        with spinner("Checking prerequisites"):
            prereq_ok = check_prerequisites(install_dir)
        if not prereq_ok:
            steps.complete_step(current_step, success=False)
            console.print(steps.render())
            raise typer.Exit(1)
        steps.complete_step(current_step, success=True)
        current_step += 1
        console.print(steps.render())

        # Step 2: Check for updates
        steps.start_step(current_step)
        console.print(steps.render())
        with spinner("Checking for updates"):
            has_updates, temp_dir = check_for_updates(install_dir, git_repo)

        if not has_updates:
            steps.complete_step(current_step, success=True)
            console.print(steps.render())
            console.print()
            show_success("Already up to date! No updates available.")
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise typer.Exit(0)

        steps.complete_step(current_step, success=True)
        current_step += 1
        console.print(steps.render())

        if check_only:
            show_success("Updates are available!")
            show_info("Run without --check-only to install updates")
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise typer.Exit(0)

        # Show what will be updated
        console.print()
        if temp_dir:
            added, removed, modified = compare_directories(
                install_dir / "app", Path(temp_dir) / "app"
            )
            table = create_file_changes_table(added, removed, modified)
            console.print(table)
            console.print()

        # Confirm update
        if not yes and not dry_run:
            details = [
                "Services will be temporarily stopped",
                "A backup will be created automatically",
                "Update typically takes 1-2 minutes",
            ]
            if not show_confirmation_prompt("Proceed with update?", details, default=True):
                show_info("Update cancelled")
                if temp_dir:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                raise typer.Exit(0)

        if dry_run:
            show_info("Dry run complete - stopping here")
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)
            raise typer.Exit(0)

        # Step 3: Create backup
        steps.start_step(current_step)
        console.print(steps.render())
        if not skip_backup:
            with spinner("Creating backup"):
                backup_path = create_backup(install_dir, backup_dir)

            if backup_path:
                show_success(f"Backup created: {backup_path}")
                # Show backup info
                backup_table = create_backup_info_table(
                    str(backup_path),
                    get_file_size_human(backup_path),
                    0,  # Could count files if needed
                )
                console.print(backup_table)
                steps.complete_step(current_step, success=True)
            else:
                show_error("Failed to create backup")
                steps.complete_step(current_step, success=False)
                raise typer.Exit(1)
        else:
            show_warning("Skipping backup (--skip-backup)")
            warnings.append("Backup was skipped")
            steps.complete_step(current_step, success=True)
        current_step += 1
        console.print(steps.render())

        # Step 4: Stop services
        steps.start_step(current_step)
        console.print(steps.render())
        with spinner("Stopping services"):
            services_stopped = stop_all_services()

        service_table = create_service_status_table(
            [(name, status, action) for name, status, action in services_stopped]
        )
        console.print(service_table)
        steps.complete_step(current_step, success=True)
        current_step += 1
        console.print(steps.render())

        # Step 5: Update code
        if not services_only and not deps_only:
            steps.start_step(current_step)
            console.print(steps.render())
            with spinner("Updating application code"):
                if temp_dir:
                    update_success = update_code(install_dir, Path(temp_dir), mascloner_user)
                else:
                    update_success = False

            if update_success:
                show_success("Code updated successfully")
                steps.complete_step(current_step, success=True)
            else:
                show_error("Failed to update code")
                steps.complete_step(current_step, success=False)
                raise typer.Exit(1)
        else:
            steps.complete_step(current_step, success=True)
        current_step += 1
        console.print(steps.render())

        # Cleanup temp directory
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)

        # Step 6: Update dependencies
        if not services_only:
            steps.start_step(current_step)
            console.print(steps.render())
            with spinner("Updating Python dependencies"):
                deps_success = update_dependencies(install_dir, mascloner_user)

            if deps_success:
                show_success("Dependencies updated")
                steps.complete_step(current_step, success=True)
            else:
                show_warning("Some dependencies may have failed to update")
                warnings.append("Dependency update had warnings")
                steps.complete_step(current_step, success=True)
        else:
            steps.complete_step(current_step, success=True)
        current_step += 1
        console.print(steps.render())

        # Step 7: Run migrations
        if not services_only and not deps_only:
            steps.start_step(current_step)
            console.print(steps.render())
            with spinner("Running database migrations"):
                migration_success = run_migrations(install_dir, mascloner_user)

            if migration_success:
                show_success("Migrations completed")
                steps.complete_step(current_step, success=True)
            else:
                show_info("No migrations needed")
                steps.complete_step(current_step, success=True)
        else:
            steps.complete_step(current_step, success=True)
        current_step += 1
        console.print(steps.render())

        # Step 8: Update systemd services
        steps.start_step(current_step)
        console.print(steps.render())
        with spinner("Updating systemd services"):
            services_updated = update_systemd_services(install_dir)

        if services_updated:
            show_success("SystemD services updated")
        else:
            show_info("No service updates needed")
        steps.complete_step(current_step, success=True)
        current_step += 1
        console.print(steps.render())

        # Step 9: Start services
        steps.start_step(current_step)
        console.print(steps.render())
        with spinner("Starting services"):
            time.sleep(2)  # Brief pause
            services_started = start_all_services()

        failed_services = [name for name, status, _ in services_started if status != "active"]
        if failed_services:
            show_warning(f"Some services failed to start: {', '.join(failed_services)}")
            warnings.append(f"Failed to start: {', '.join(failed_services)}")
            # Show logs for failed services
            for service in failed_services:
                logs = get_service_logs(service)
                if logs:
                    show_service_logs(service, logs, error_context=True)
            steps.complete_step(current_step, success=False)
        else:
            show_success("All services started successfully")
            steps.complete_step(current_step, success=True)
        current_step += 1
        console.print(steps.render())

        # Step 10: Health check
        steps.start_step(current_step)
        console.print(steps.render())
        with spinner("Running health checks"):
            time.sleep(5)  # Wait for services to initialize
            health_checks = run_health_checks()

        health_table = create_health_check_table(health_checks)
        console.print(health_table)

        failed_checks = [name for name, passed, _ in health_checks if not passed]
        if failed_checks:
            warnings.append(f"Health check failures: {', '.join(failed_checks)}")
            steps.complete_step(current_step, success=False)
        else:
            steps.complete_step(current_step, success=True)
        current_step += 1
        console.print(steps.render())

        # Show completion
        console.print()
        duration = time.time() - start_time
        show_completion_summary(
            success=len(failed_services) == 0 and len(failed_checks) == 0,
            duration=duration,
            steps_completed=current_step,
            total_steps=10,
            warnings=warnings if warnings else None,
        )

        # Show next steps
        next_steps = [
            "🔍 Review the health check results above",
            "🌐 Access your MasCloner UI to verify functionality",
            "📊 Monitor service logs: journalctl -f -u mascloner-api",
        ]
        if backup_path:
            next_steps.append(f"💾 Backup saved at: {backup_path}")
        show_next_steps(next_steps)

    except KeyboardInterrupt:
        console.print()
        show_error("Update interrupted by user")
        if backup_path:
            show_error_recovery(
                "Update was interrupted",
                [
                    "Services may be in an inconsistent state",
                    f"Restore from backup: {backup_path}",
                    "Or retry the update",
                ],
            )
        raise typer.Exit(130)
    except Exception as e:
        console.print()
        show_error(f"Update failed: {e}")
        if backup_path:
            show_error_recovery(
                str(e),
                [
                    f"Restore from backup: {backup_path}",
                    "Check logs: journalctl -u mascloner-api",
                    "Contact support if issue persists",
                ],
            )
        raise typer.Exit(1)


def check_prerequisites(install_dir: Path) -> bool:
    """Check if all prerequisites are met."""
    checks = []

    # Check git
    exit_code, _, _ = run_command(["which", "git"], check=False)
    if exit_code != 0:
        show_error("Git is not installed")
        return False

    # Check virtual environment
    venv_path = install_dir / ".venv"
    if not venv_path.exists():
        show_error(f"Virtual environment not found at {venv_path}")
        return False

    show_success("Prerequisites check passed")
    return True


def check_for_updates(install_dir: Path, git_repo: str) -> Tuple[bool, Optional[str]]:
    """
    Check if updates are available.
    
    Returns:
        Tuple of (has_updates, temp_directory)
    """
    temp_dir = tempfile.mkdtemp(prefix="mascloner-update-")

    try:
        # Clone repository
        exit_code, _, stderr = run_command(
            ["git", "clone", "--quiet", "--depth", "1", git_repo, temp_dir],
            check=False,
        )

        if exit_code != 0:
            show_error(f"Failed to fetch updates: {stderr}")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False, None

        # Compare app directories
        added, removed, modified = compare_directories(
            install_dir / "app", Path(temp_dir) / "app"
        )

        has_changes = bool(added or removed or modified)

        if not has_changes:
            # Also check requirements.txt
            req_old = install_dir / "requirements.txt"
            req_new = Path(temp_dir) / "requirements.txt"

            if req_old.exists() and req_new.exists():
                if req_old.read_text() != req_new.read_text():
                    has_changes = True

        return has_changes, temp_dir

    except Exception as e:
        show_error(f"Error checking for updates: {e}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return False, None


def stop_all_services() -> List[Tuple[str, str, str]]:
    """Stop all MasCloner services."""
    services = ["mascloner-api", "mascloner-ui", "mascloner-tunnel"]
    results = []

    for service in services:
        is_active, status = check_systemd_service(service)

        if status == "not_installed":
            results.append((service, "not_installed", "skipped"))
            continue

        if not is_active:
            results.append((service, "stopped", "already stopped"))
            continue

        success = stop_service(service)
        time.sleep(1)  # Brief pause

        if success:
            results.append((service, "stopped", "stopped"))
        else:
            results.append((service, "failed", "failed to stop"))

    return results


def start_all_services() -> List[Tuple[str, str, str]]:
    """Start all MasCloner services."""
    services = ["mascloner-api", "mascloner-ui", "mascloner-tunnel"]
    results = []

    for service in services:
        _, status = check_systemd_service(service)

        if status == "not_installed":
            results.append((service, "not_installed", "skipped"))
            continue

        success = start_service(service)
        time.sleep(3)  # Wait for service to start

        # Verify it started
        is_active, new_status = check_systemd_service(service)

        if is_active:
            results.append((service, "active", "started"))
        else:
            results.append((service, new_status, "failed to start"))

    return results


def update_code(install_dir: Path, temp_dir: Path, mascloner_user: str) -> bool:
    """Update application code from temporary directory."""
    try:
        # Preserve important paths
        preserve_paths = ["data", "logs", "etc", ".env", ".venv"]

        backup_temp = Path(tempfile.mkdtemp(prefix="mascloner-preserve-"))

        # Backup preserved paths
        for path_name in preserve_paths:
            source = install_dir / path_name
            if source.exists():
                dest = backup_temp / path_name
                if source.is_dir():
                    shutil.copytree(source, dest)
                else:
                    shutil.copy2(source, dest)

        # Remove old code
        for item in ["app", "ops", "requirements.txt"]:
            target = install_dir / item
            if target.exists():
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()

        # Copy new code
        for item in ["app", "ops", "requirements.txt", "README.md"]:
            source = temp_dir / item
            if source.exists():
                dest = install_dir / item
                if source.is_dir():
                    shutil.copytree(source, dest)
                else:
                    shutil.copy2(source, dest)

        # Restore preserved paths
        for path_name in preserve_paths:
            source = backup_temp / path_name
            if source.exists():
                dest = install_dir / path_name
                if dest.exists():
                    if dest.is_dir():
                        shutil.rmtree(dest)
                    else:
                        dest.unlink()
                if source.is_dir():
                    shutil.copytree(source, dest)
                else:
                    shutil.copy2(source, dest)

        # Set ownership
        run_command(
            ["chown", "-R", f"{mascloner_user}:{mascloner_user}", str(install_dir)],
            check=False,
        )

        # Cleanup
        shutil.rmtree(backup_temp, ignore_errors=True)

        return True
    except Exception as e:
        show_error(f"Error updating code: {e}")
        return False


def update_dependencies(install_dir: Path, mascloner_user: str) -> bool:
    """Update Python dependencies."""
    venv_python = install_dir / ".venv" / "bin" / "python"
    venv_pip = install_dir / ".venv" / "bin" / "pip"
    requirements = install_dir / "requirements.txt"

    if not requirements.exists():
        return False

    # Update pip
    exit_code, _, _ = run_command(
        ["sudo", "-u", mascloner_user, str(venv_pip), "install", "--upgrade", "pip"],
        check=False,
    )

    # Update dependencies
    exit_code, _, _ = run_command(
        [
            "sudo",
            "-u",
            mascloner_user,
            str(venv_pip),
            "install",
            "-r",
            str(requirements),
            "--upgrade",
        ],
        check=False,
    )

    return exit_code == 0


def run_migrations(install_dir: Path, mascloner_user: str) -> bool:
    """Run database migrations if available."""
    migrate_script = install_dir / "ops" / "scripts" / "migrate.py"

    if not migrate_script.exists():
        return False

    venv_python = install_dir / ".venv" / "bin" / "python"

    exit_code, _, _ = run_command(
        ["sudo", "-u", mascloner_user, str(venv_python), str(migrate_script)],
        check=False,
    )

    return exit_code == 0


def update_systemd_services(install_dir: Path) -> bool:
    """Update systemd service files if they've changed."""
    service_dir = install_dir / "ops" / "systemd"
    updated = False

    if not service_dir.exists():
        return False

    for service_file in service_dir.glob("*.service"):
        dest = Path("/etc/systemd/system") / service_file.name

        # Check if different
        if not dest.exists() or dest.read_text() != service_file.read_text():
            shutil.copy2(service_file, dest)
            updated = True

    if updated:
        run_command(["systemctl", "daemon-reload"], check=False)

    return updated


def run_health_checks() -> List[Tuple[str, bool, str]]:
    """Run post-update health checks."""
    checks = []

    # API health
    api_ok = check_http_endpoint("http://127.0.0.1:8787/health", timeout=10)
    checks.append(("API Health", api_ok, "http://127.0.0.1:8787/health"))

    # UI health
    ui_ok = check_http_endpoint("http://127.0.0.1:8501", timeout=10)
    checks.append(("UI Health", ui_ok, "http://127.0.0.1:8501"))

    # Database endpoint
    db_ok = check_http_endpoint("http://127.0.0.1:8787/status", timeout=10)
    checks.append(("Database", db_ok, "http://127.0.0.1:8787/status"))

    # File tree endpoint
    tree_ok = check_http_endpoint("http://127.0.0.1:8787/tree", timeout=10)
    checks.append(("File Tree", tree_ok, "http://127.0.0.1:8787/tree"))

    return checks
