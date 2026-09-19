"""Rollback command - Restore from a backup."""
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from ops.cli.ui.panels import show_confirmation_prompt, show_error_recovery, show_next_steps
from ops.cli.ui.progress import show_error, show_header, show_info, show_success
from ops.cli.utils import (
    get_backup_dir,
    get_file_size_human,
    get_install_dir,
    get_mascloner_user,
    require_root,
    run_command,
    start_service,
    stop_service,
)
from ops.cli.recovery import restore_recovery_bundle

console = Console()


def main(
    backup_file: Optional[str] = typer.Argument(None, help="Backup file to restore from"),
    list_backups: bool = typer.Option(
        False, "--list", "-l", help="List available backups"
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Skip confirmation prompts"
    ),
):
    """
    Rollback to a previous backup.
    
    This will:
    - Stop all services
    - Restore files from backup
    - Restart services
    
    Use --list to see available backups.
    """
    require_root()

    backup_dir = get_backup_dir()
    install_dir = get_install_dir()

    if list_backups:
        list_available_backups(backup_dir)
        return

    show_header("MasCloner Rollback", "Restore from a previous backup")

    # Get list of backups
    backups = get_backup_list(backup_dir)

    if not backups:
        show_error("No backups found")
        show_info(f"Backup directory: {backup_dir}")
        raise typer.Exit(1)

    # If no backup specified, show list and ask
    if not backup_file:
        console.print("\n[bold]Available Backups:[/bold]\n")
        table = Table(show_header=True, header_style="bold blue")
        table.add_column("#", style="cyan", width=4)
        table.add_column("Backup File", style="cyan")
        table.add_column("Size", justify="right")
        table.add_column("Date", style="dim")

        for i, (backup_path, size, date) in enumerate(backups, 1):
            table.add_row(
                str(i),
                backup_path.name,
                size,
                date,
            )

        console.print(table)
        console.print()

        # Ask which backup to restore
        choice = typer.prompt(
            "Enter backup number to restore (or 'q' to quit)",
            type=str,
        )

        if choice.lower() == "q":
            show_info("Rollback cancelled")
            raise typer.Exit(0)

        try:
            idx = int(choice) - 1
            if idx < 0 or idx >= len(backups):
                show_error("Invalid backup number")
                raise typer.Exit(1)
            backup_file = str(backups[idx][0])
        except ValueError:
            show_error("Invalid input")
            raise typer.Exit(1)

    # Validate backup file
    backup_path = Path(backup_file)
    if not backup_path.exists():
        # Try in backup directory
        backup_path = backup_dir / backup_file
        if not backup_path.exists():
            show_error(f"Backup not found: {backup_file}")
            raise typer.Exit(1)

    # Confirm rollback
    if not yes:
        details = [
            f"Backup: {backup_path.name}",
            f"Size: {get_file_size_human(backup_path)}",
            "All services will be stopped",
            "Current installation will be replaced",
        ]
        if not show_confirmation_prompt(
            "⚠️  This will replace your current installation. Continue?",
            details,
            default=False,
        ):
            show_info("Rollback cancelled")
            raise typer.Exit(0)

    try:
        # Validation is deliberately inside restore_recovery_bundle and happens
        # before this callback stops a service or changes the installation.
        mascloner_user = get_mascloner_user()
        with console.status("[bold blue]Validating and restoring recovery bundle...", spinner="dots"):
            restore_recovery_bundle(
                backup_path,
                install_dir,
                stop_services=_stop_all_services,
                reload_services=_reload_systemd,
                start_services=_start_all_services,
                health_check=_health_check,
                owner=mascloner_user,
            )

        show_success("Verified recovery bundle restored and services are healthy")

        # Show completion
        console.print()
        show_success("✅ Rollback completed successfully!")

        next_steps = [
            "🔍 Check service status: sudo mascloner status",
            "🌐 Access your MasCloner UI to verify",
            "📊 Monitor logs: journalctl -f -u mascloner-api",
        ]
        show_next_steps(next_steps)

    except Exception as e:
        console.print()
        show_error(f"Rollback failed: {e}")
        show_error_recovery(
            str(e),
            [
                "Services may be in an inconsistent state",
                "Try restoring manually",
                "Check system logs for details",
            ],
        )
        raise typer.Exit(1)


def _stop_all_services() -> bool:
    outcomes = [stop_service(service) for service in ("mascloner-api", "mascloner-ui", "mascloner-tunnel")]
    return all(outcomes)


def _start_all_services() -> bool:
    outcomes = []
    for service in ("mascloner-api", "mascloner-ui", "mascloner-tunnel"):
        outcomes.append(start_service(service))
        time.sleep(0.5)
    return all(outcomes)


def _reload_systemd() -> bool:
    exit_code, _, _ = run_command(["systemctl", "daemon-reload"], check=False)
    return exit_code == 0


def _health_check() -> bool:
    from ops.cli.commands.update import run_health_checks

    return all(passed for _, passed, _ in run_health_checks())


def get_backup_list(backup_dir: Path) -> List[tuple[Path, str, str]]:
    """Get list of available backups with metadata."""
    backups: List[tuple[Path, str, str]] = []

    if not backup_dir.exists():
        return backups

    for backup_file in sorted(backup_dir.glob("mascloner-recovery-*.tar.gz"), reverse=True):
        size = get_file_size_human(backup_file)
        date_str = datetime.fromtimestamp(backup_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M")

        backups.append((backup_file, size, date_str))

    return backups


def list_available_backups(backup_dir: Path):
    """List all available backups."""
    show_header("Available Backups", f"Location: {backup_dir}")

    backups = get_backup_list(backup_dir)

    if not backups:
        show_info("No backups found")
        return

    table = Table(show_header=True, header_style="bold blue")
    table.add_column("Backup File", style="cyan")
    table.add_column("Size", justify="right")
    table.add_column("Date", style="dim")

    for backup_path, size, date in backups:
        table.add_row(backup_path.name, size, date)

    console.print(table)
    console.print(f"\n[dim]Total backups: {len(backups)}[/dim]")
