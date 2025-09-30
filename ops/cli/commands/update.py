"""Update command - Update MasCloner to the latest version."""
# Version: 2.2.1
# Last Updated: 2025-09-30

import glob
import shutil
import tempfile
import time
from pathlib import Path
from typing import List, Optional, Tuple

import typer
from rich.live import Live

from ops.cli.ui.layout import UpdateLayout, step_context
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
    show_error,
    show_header,
    show_info,
    show_success,
    show_warning,
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
    install_cli_dependencies,
    require_root,
    run_command,
    start_service,
    stop_service,
)

# Version information
UPDATE_CMD_VERSION = "2.2.1"
UPDATE_CMD_DATE = "2025-09-30"


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
    Update MasCloner to the latest version.
    
    [dim]CLI Update Command v2.2.1 (2025-09-30)[/dim]
    
    This command will:
    - Check for available updates (via git commit comparison)
    - Create a backup of your installation
    - Stop running services
    - Update code and dependencies
    - Clear Python cache files
    - Restart services
    - Run health checks
    """
    start_time = time.time()

    show_header(
        "MasCloner Update",
        f"Safely update your MasCloner installation to the latest version\nCLI Update Command v{UPDATE_CMD_VERSION} ({UPDATE_CMD_DATE})",
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

    # Create layout and setup steps
    layout = UpdateLayout()
    layout.add_step("Check prerequisites")
    layout.add_step("Check for updates")
    layout.add_step("Create backup")
    layout.add_step("Stop services")
    layout.add_step("Update code")
    layout.add_step("Update dependencies")
    layout.add_step("Run migrations")
    layout.add_step("Update services")
    layout.add_step("Start services")
    layout.add_step("Health check")

    current_step = 0
    warnings: List[str] = []
    backup_path: Optional[Path] = None

    # Run the update within a Live context for real-time display
    with Live(layout.render(), refresh_per_second=10) as live:
        try:
            if dry_run:
                layout.add_log("Running in DRY RUN mode - no changes will be made", style="yellow")

            # Step 1: Prerequisites
            with step_context(layout, current_step):
                prereq_ok = check_prerequisites(install_dir, layout)
                if not prereq_ok:
                    raise typer.Exit(1)
            current_step += 1

            # Step 2: Check for updates
            with step_context(layout, current_step):
                has_updates, update_data = check_for_updates(install_dir, git_repo, layout)

            if not has_updates:
                current_step += 1
                layout.add_log("Already up to date! No updates available.", style="green")
                live.stop()
                show_success("Already up to date! No updates available.")
                raise typer.Exit(0)

            # Unpack update data
            temp_dir, changelog, changed_files, remote_commit = update_data
            current_step += 1

            if check_only:
                layout.add_log("Updates are available!", style="green")
                layout.add_log("Run without --check-only to install updates", style="blue")
                if temp_dir:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                live.stop()
                
                # Show changelog
                if changelog:
                    from ops.cli.ui.panels import show_changelog
                    show_changelog("\n".join(changelog))
                
                show_success("Updates are available!")
                show_info("Run without --check-only to install updates")
                raise typer.Exit(0)

            # Display changelog and file changes
            if changelog:
                layout.add_log("=== Release Notes ===", style="bold cyan")
                for commit in changelog[:5]:  # Show first 5 commits in log
                    layout.add_log(f"  • {commit}", style="white")
                if len(changelog) > 5:
                    layout.add_log(f"  ... and {len(changelog) - 5} more commits", style="dim")

            # Confirm update (pause live display for prompt)
            if not yes and not dry_run:
                live.stop()
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
                live.start()

            if dry_run:
                layout.add_log("Dry run complete - stopping here", style="blue")
                if temp_dir:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                live.stop()
                show_info("Dry run complete - stopping here")
                raise typer.Exit(0)

            # Step 3: Create backup
            with step_context(layout, current_step):
                if not skip_backup:
                    backup_path = create_backup(install_dir, backup_dir)
                    if backup_path:
                        layout.add_log(f"Backup created: {backup_path.name}", style="green")
                    else:
                        layout.add_log("Failed to create backup", style="red")
                        raise typer.Exit(1)
                else:
                    layout.add_log("Skipping backup (--skip-backup)", style="yellow")
                    warnings.append("Backup was skipped")
            current_step += 1

            # Step 4: Stop services
            with step_context(layout, current_step):
                services_stopped = stop_all_services(layout)
            current_step += 1

            # Step 5: Update code
            if not services_only and not deps_only:
                with step_context(layout, current_step):
                    if temp_dir:
                        update_success = update_code(install_dir, Path(temp_dir), mascloner_user, layout)
                    else:
                        update_success = False
                    
                    if not update_success:
                        raise typer.Exit(1)
            else:
                layout.complete_step(current_step, success=True)
            current_step += 1

            # Cleanup temp directory
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)
                layout.add_log("Cleaned up temporary files", style="dim")

            # Clear Python bytecode cache
            layout.add_log("Clearing Python cache files...", style="blue")
            clear_python_cache(install_dir, layout)

            # Step 6: Update dependencies
            if not services_only:
                with step_context(layout, current_step):
                    deps_success = update_dependencies(install_dir, mascloner_user, layout)
                    if not deps_success:
                        warnings.append("Dependency update had warnings")
            else:
                layout.complete_step(current_step, success=True)
            current_step += 1

            # Step 7: Run migrations
            if not services_only and not deps_only:
                with step_context(layout, current_step):
                    run_migrations(install_dir, mascloner_user, layout)
            else:
                layout.complete_step(current_step, success=True)
            current_step += 1

            # Step 8: Update systemd services
            with step_context(layout, current_step):
                services_updated = update_systemd_services(install_dir, layout)
            current_step += 1

            # Step 9: Start services
            with step_context(layout, current_step):
                services_started = start_all_services(layout)

            failed_services = [name for name, status, _ in services_started if status != "active"]
            if failed_services:
                warnings.append(f"Failed to start: {', '.join(failed_services)}")
            current_step += 1

            # Step 10: Health check
            with step_context(layout, current_step):
                layout.add_log("Waiting for services to fully initialize...", style="blue")
                time.sleep(5)
                health_checks = run_health_checks(layout)

            failed_checks = [name for name, passed, _ in health_checks if not passed]
            if failed_checks:
                warnings.append(f"Health check failures: {', '.join(failed_checks)}")

            # Update complete - save new commit hash
            commit_file = install_dir / ".commit_hash"
            try:
                commit_file.write_text(remote_commit)
                # Set ownership to mascloner user
                run_command(
                    ["chown", f"{mascloner_user}:{mascloner_user}", str(commit_file)],
                    check=False,
                )
                layout.add_log(f"Saved version: {remote_commit[:8]}", style="dim")
            except Exception as e:
                layout.add_log(f"Warning: Could not save version file: {e}", style="yellow")
            
            duration = time.time() - start_time
            layout.add_log(f"Update completed in {duration:.1f}s", style="bold green")

            # Stop live display and show final summary
            live.stop()

            # Reinstall CLI dependencies and re-link command
            show_info("Finalizing CLI installation...")
            if install_cli_dependencies(install_dir):
                show_success("CLI dependencies verified")
            else:
                show_warning("CLI dependency check failed - run install-cli.sh manually")

            wrapper_path = install_dir / "ops" / "scripts" / "mascloner"
            system_bin = Path("/usr/local/bin/mascloner")

            if wrapper_path.exists():
                run_command(["chmod", "+x", str(wrapper_path)], check=False)
                if system_bin.exists() or system_bin.is_symlink():
                    system_bin.unlink(missing_ok=True)
                system_bin.symlink_to(wrapper_path)
                show_success("CLI command linked at /usr/local/bin/mascloner")
            else:
                show_warning("CLI wrapper missing - unable to refresh mascloner command")

            # Show final summary
            show_completion_summary(
                success=len(failed_services) == 0 and len(failed_checks) == 0,
                duration=duration,
                steps_completed=current_step,
                total_steps=10,
                warnings=warnings if warnings else None,
            )

            next_steps = [
                "🔍 Review the health check results above",
                "🌐 Access your MasCloner UI to verify functionality",
                "📊 Monitor service logs: journalctl -f -u mascloner-api",
            ]
            if backup_path:
                next_steps.append(f"💾 Backup saved at: {backup_path}")
            show_next_steps(next_steps)

        except KeyboardInterrupt:
            live.stop()
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
        except typer.Exit:
            raise
        except Exception as e:
            live.stop()
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


def check_prerequisites(install_dir: Path, layout: Optional[UpdateLayout] = None) -> bool:
    """Check if all prerequisites are met."""
    checks = []
    
    # Check if git is installed
    exit_code, _, _ = run_command(["which", "git"], check=False, capture=True)
    git_ok = exit_code == 0
    checks.append(("Git installed", git_ok))
    if layout:
        layout.add_log(f"Git: {'✓' if git_ok else '✗'}", style="green" if git_ok else "red")

    # Check if systemctl is available
    exit_code, _, _ = run_command(["which", "systemctl"], check=False, capture=True)
    systemctl_ok = exit_code == 0
    checks.append(("SystemD available", systemctl_ok))
    if layout:
        layout.add_log(f"SystemD: {'✓' if systemctl_ok else '✗'}", style="green" if systemctl_ok else "red")

    # Check if .venv exists
    venv_ok = (install_dir / ".venv").exists()
    checks.append(("Virtual environment", venv_ok))
    if layout:
        layout.add_log(f"Virtual env: {'✓' if venv_ok else '✗'}", style="green" if venv_ok else "red")

    all_ok = all(ok for _, ok in checks)
    
    if not all_ok and not layout:
        show_error("Prerequisites check failed")
        for name, ok in checks:
            if not ok:
                show_error(f"  ✗ {name}")
    
    return all_ok


def check_for_updates(
    install_dir: Path, git_repo: str, layout: Optional[UpdateLayout] = None
) -> Tuple[bool, Optional[Tuple]]:
    """Check if updates are available using git commit comparison.
    
    Returns:
        Tuple of (has_updates, update_data)
        where update_data is (temp_dir, changelog, changed_files, remote_commit) or None
    """
    temp_dir = tempfile.mkdtemp(prefix="mascloner_update_")
    
    try:
        # Get current local commit hash from stored file
        commit_file = install_dir / ".commit_hash"
        local_commit = "unknown"
        
        if commit_file.exists():
            try:
                local_commit = commit_file.read_text().strip()
                if layout:
                    layout.add_log(f"Local version: {local_commit[:8]}", style="dim")
            except Exception as e:
                if layout:
                    layout.add_log(f"Warning: Could not read version file: {e}", style="yellow")
        else:
            if layout:
                layout.add_log("No version file found (first install or old version)", style="yellow")
        
        # Clone latest version
        exit_code, _, _ = run_command(
            ["git", "clone", "--depth", "1", git_repo, temp_dir],
            check=False,
            capture=True,
        )
        
        if exit_code != 0:
            if layout:
                layout.add_log("Failed to fetch updates from repository", style="red")
            else:
                show_error("Failed to fetch updates from repository")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False, None

        # Get remote commit hash
        exit_code, remote_commit, _ = run_command(
            ["git", "-C", temp_dir, "rev-parse", "HEAD"],
            check=False,
            capture=True,
        )
        
        if exit_code != 0:
            if layout:
                layout.add_log("Failed to get remote commit hash", style="red")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False, None
        
        remote_commit = remote_commit.strip()
        if layout:
            layout.add_log(f"Remote commit: {remote_commit[:8]}", style="dim")
        
        # Compare commits
        if local_commit == remote_commit:
            if layout:
                layout.add_log("Already at latest version", style="dim")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False, None
        
        # Different commits - show what changed
        if layout:
            layout.add_log(f"Update available: {local_commit[:8]} → {remote_commit[:8]}", style="cyan")
        
        # Get commit messages between versions (release notes)
        changelog = []
        if local_commit != "unknown":
            exit_code, log_output, _ = run_command(
                ["git", "-C", temp_dir, "log", "--oneline", "--no-decorate", f"{local_commit}..{remote_commit}"],
                check=False,
                capture=True,
            )
            
            if exit_code == 0 and log_output.strip():
                changelog = log_output.strip().split('\n')
                if layout:
                    layout.add_log(f"Found {len(changelog)} new commits", style="blue")
        
        # Get changed files between commits
        changed_files = []
        if local_commit != "unknown":
            exit_code, diff_output, _ = run_command(
                ["git", "-C", temp_dir, "diff", "--name-status", f"{local_commit}..{remote_commit}"],
                check=False,
                capture=True,
            )
            
            if exit_code == 0 and diff_output.strip():
                for line in diff_output.strip().split('\n'):
                    parts = line.split('\t', 1)
                    if len(parts) == 2:
                        status, filepath = parts
                        changed_files.append((status, filepath))
                
                if layout:
                    modified = len([f for s, f in changed_files if s == 'M'])
                    added = len([f for s, f in changed_files if s == 'A'])
                    deleted = len([f for s, f in changed_files if s == 'D'])
                    layout.add_log(
                        f"Files: {modified} modified, {added} added, {deleted} deleted",
                        style="cyan"
                    )
        
        # Store changelog, file changes, and remote commit for later use
        return True, (temp_dir, changelog, changed_files, remote_commit)

    except Exception as e:
        if layout:
            layout.add_log(f"Error checking for updates: {e}", style="red")
        else:
            show_error(f"Error checking for updates: {e}")
        shutil.rmtree(temp_dir, ignore_errors=True)
        return False, None


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


def start_all_services(layout: Optional[UpdateLayout] = None) -> List[Tuple[str, str, str]]:
    """Start all MasCloner services."""
    services = ["mascloner-api", "mascloner-ui", "mascloner-tunnel"]
    results = []

    for service in services:
        success = start_service(service)
        time.sleep(0.5)
        is_running, status = check_systemd_service(service)
        action = "started" if is_running else "failed"
        results.append((service, status, action))
        if layout:
            layout.add_log(f"{service}: {action}", style="green" if is_running else "red")

    return results


def update_code(
    install_dir: Path, temp_dir: Path, user: str, layout: Optional[UpdateLayout] = None
) -> bool:
    """Update application code from temp directory."""
    try:
        # Update app directory
        app_src = temp_dir / "app"
        app_dst = install_dir / "app"
        if app_src.exists():
            shutil.rmtree(app_dst, ignore_errors=True)
            shutil.copytree(app_src, app_dst)
            if layout:
                layout.add_log("Updated app/ directory", style="green")

        # Update ops directory
        ops_src = temp_dir / "ops"
        ops_dst = install_dir / "ops"
        if ops_src.exists():
            shutil.rmtree(ops_dst, ignore_errors=True)
            shutil.copytree(ops_src, ops_dst)
            if layout:
                layout.add_log("Updated ops/ directory", style="green")

        # Set ownership
        run_command(
            ["chown", "-R", f"{user}:{user}", str(install_dir)],
            check=False,
        )
        if layout:
            layout.add_log("Set file ownership", style="dim")

        return True
    except Exception as e:
        if layout:
            layout.add_log(f"Failed to update code: {e}", style="red")
        else:
            show_error(f"Failed to update code: {e}")
        return False


def update_dependencies(
    install_dir: Path, user: str, layout: Optional[UpdateLayout] = None
) -> bool:
    """Update Python dependencies."""
    venv_pip = install_dir / ".venv" / "bin" / "pip"
    requirements = install_dir / "requirements.txt"

    if not requirements.exists():
        if layout:
            layout.add_log("No requirements.txt found", style="yellow")
        return True

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


def clear_python_cache(install_dir: Path, layout: Optional[UpdateLayout] = None) -> None:
    """Clear all Python bytecode cache files."""
    cache_count = 0
    
    # Remove all .pyc files
    for pyc_file in glob.glob(str(install_dir / "**" / "*.pyc"), recursive=True):
        try:
            Path(pyc_file).unlink()
            cache_count += 1
        except Exception:
            pass
    
    # Remove all __pycache__ directories
    for pycache_dir in glob.glob(str(install_dir / "**" / "__pycache__"), recursive=True):
        try:
            shutil.rmtree(pycache_dir)
            cache_count += 1
        except Exception:
            pass
    
    if layout:
        if cache_count > 0:
            layout.add_log(f"Removed {cache_count} cache files/directories", style="green")
        else:
            layout.add_log("No cache files to remove", style="dim")


def run_migrations(
    install_dir: Path, user: str, layout: Optional[UpdateLayout] = None
) -> bool:
    """Run database migrations if needed."""
    # For now, we don't have migrations
    # This is a placeholder for future migration support
    if layout:
        layout.add_log("No migrations needed", style="dim")
    return True


def update_systemd_services(
    install_dir: Path, layout: Optional[UpdateLayout] = None
) -> bool:
    """Update systemd service files if needed."""
    service_dir = Path("/etc/systemd/system")
    source_services = install_dir / "ops" / "systemd"

    if not source_services.exists():
        if layout:
            layout.add_log("No service files to update", style="dim")
        return True

    updated = False
    for service_file in source_services.glob("mascloner-*.service"):
        dest = service_dir / service_file.name
        try:
            shutil.copy(service_file, dest)
            updated = True
            if layout:
                layout.add_log(f"Updated {service_file.name}", style="green")
        except Exception as e:
            if layout:
                layout.add_log(f"Failed to update {service_file.name}: {e}", style="yellow")

    if updated:
        run_command(["systemctl", "daemon-reload"], check=False)
        if layout:
            layout.add_log("Reloaded systemd daemon", style="dim")

    return True


def run_health_checks(layout: Optional[UpdateLayout] = None) -> List[Tuple[str, bool, str]]:
    """Run health checks on services with retry logic."""
    checks = []

    # Check API service
    api_running, api_status = check_systemd_service("mascloner-api")
    checks.append(("API Service", api_running, api_status))
    if layout:
        layout.add_log(f"API service: {'✓' if api_running else '✗'}", style="green" if api_running else "red")

    # Check UI service
    ui_running, ui_status = check_systemd_service("mascloner-ui")
    checks.append(("UI Service", ui_running, ui_status))
    if layout:
        layout.add_log(f"UI service: {'✓' if ui_running else '✗'}", style="green" if ui_running else "red")

    # Check API endpoint with retry (may take time to initialize after update)
    api_ok = False
    api_error = None
    for attempt in range(3):
        api_ok = check_http_endpoint("http://127.0.0.1:8787/health", timeout=5)
        if api_ok:
            break
        if layout and attempt < 2:
            layout.add_log(f"API health check attempt {attempt + 1}/3 failed, retrying...", style="yellow")
        time.sleep(2)
    
    # If API health check failed, get detailed diagnostics
    if not api_ok and layout:
        layout.add_log("=== API Health Check Failed - Diagnostics ===", style="bold red")
        
        # Check if port is listening
        exit_code, netstat_out, _ = run_command(
            ["ss", "-tlnp"],
            check=False,
            capture=True,
        )
        if exit_code == 0 and ":8787" in netstat_out:
            # Extract the line with port 8787
            for line in netstat_out.split('\n'):
                if ":8787" in line:
                    layout.add_log(f"Port 8787 status: {line.strip()[:100]}", style="yellow")
                    break
        else:
            layout.add_log("Port 8787 is NOT listening - API not started", style="red")
        
        # Check API service logs
        logs = get_service_logs("mascloner-api", lines=10)
        if logs:
            layout.add_log("Recent API logs:", style="yellow")
            for log_line in logs[-5:]:  # Last 5 lines
                layout.add_log(f"  {log_line[:120]}", style="dim")
        
        # Try to curl the endpoint for more details
        exit_code, curl_out, curl_err = run_command(
            ["curl", "-v", "http://127.0.0.1:8787/health"],
            check=False,
            capture=True,
        )
        if curl_err:
            layout.add_log(f"Connection error: {curl_err[:200]}", style="red")
    
    checks.append(("API Health", api_ok, "http://127.0.0.1:8787/health"))
    if layout:
        layout.add_log(f"API health: {'✓' if api_ok else '✗'}", style="green" if api_ok else "red")

    # Check UI endpoint with retry
    ui_ok = False
    for attempt in range(3):
        ui_ok = check_http_endpoint("http://127.0.0.1:8501", timeout=5)
        if ui_ok:
            break
        if layout and attempt < 2:
            layout.add_log(f"UI health check attempt {attempt + 1}/3 failed, retrying...", style="yellow")
        time.sleep(2)
    
    checks.append(("UI Endpoint", ui_ok, "http://127.0.0.1:8501"))
    if layout:
        layout.add_log(f"UI endpoint: {'✓' if ui_ok else '✗'}", style="green" if ui_ok else "red")

    # Check tunnel service
    tunnel_running, tunnel_status = check_systemd_service("mascloner-tunnel")
    checks.append(("Tunnel Service", tunnel_running, tunnel_status))
    if layout:
        layout.add_log(f"Tunnel service: {'✓' if tunnel_running else '✗'}", style="green" if tunnel_running else "red")

    # Check file tree endpoint with retry
    tree_ok = False
    for attempt in range(3):
        tree_ok = check_http_endpoint("http://127.0.0.1:8787/tree", timeout=5)
        if tree_ok:
            break
        if layout and attempt < 2:
            layout.add_log(f"File tree check attempt {attempt + 1}/3 failed, retrying...", style="yellow")
        time.sleep(2)
    
    checks.append(("File Tree", tree_ok, "http://127.0.0.1:8787/tree"))
    if layout:
        layout.add_log(f"File tree: {'✓' if tree_ok else '✗'}", style="green" if tree_ok else "red")

    return checks