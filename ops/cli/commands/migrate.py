"""Migrate command - Backup-first v3 architecture migration and rollback (Issue #14)."""

from pathlib import Path
from typing import Optional
import typer
from rich.console import Console
from rich.table import Table

from ops.cli.ui.progress import show_header, show_info, show_success, show_warning

console = Console()


def main(
    check: bool = typer.Option(
        False,
        "--check",
        "-c",
        help="Run preflight checks only",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        "-d",
        help="Perform true dry-run: calculate mappings and verify with zero disk/DB mutations",
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        "-a",
        help="Execute the full backup-first migration and cutover",
    ),
    rollback_bundle: Optional[str] = typer.Option(
        None,
        "--rollback",
        "-r",
        help="Path to recovery bundle to restore from",
    ),
) -> None:
    """Execute backup-first v3 architecture migration or rollback."""
    from app.migration import MigrationMode, MigrationService

    service = MigrationService()

    if rollback_bundle:
        show_header("MasCloner Migration", "Restoring from Recovery Bundle (Rollback)")
        report = service.rollback(Path(rollback_bundle))
        if not report.success:
            show_warning(f"Rollback failed: {report.error}")
            raise typer.Exit(1)
        show_success(f"Rollback completed successfully from {rollback_bundle}")
        return

    if check:
        mode = MigrationMode.CHECK
        title_action = "Running Preflight Checks"
    elif dry_run:
        mode = MigrationMode.DRY_RUN
        title_action = "Simulating Migration (Dry-Run)"
    elif apply:
        mode = MigrationMode.APPLY
        title_action = "Applying Architecture Migration"
    else:
        # Default to dry-run for safety if not specified
        mode = MigrationMode.DRY_RUN
        title_action = "Simulating Migration (Default Dry-Run)"

    show_header("MasCloner Migration", title_action)

    report = service.run_migration(mode=mode)

    # 1. Preflight table
    if report.preflight:
        pf_table = Table(title="Preflight Checks", show_header=True)
        pf_table.add_column("Check", style="bold cyan")
        pf_table.add_column("Status")
        pf_table.add_column("Details", style="dim")

        pf = report.preflight
        pf_table.add_row("Topology", "[green]PASS[/green]" if pf.topology_ok else "[red]FAIL[/red]", "Local disk storage")
        pf_table.add_row("Free Space", "[green]PASS[/green]" if pf.free_space_ok else "[red]FAIL[/red]", f"{pf.free_space_mb:.1f} MB free")
        pf_table.add_row("Permissions", "[green]PASS[/green]" if pf.permissions_ok else "[red]FAIL[/red]", "Data/etc/logs writable")
        pf_table.add_row("Database Integrity", "[green]PASS[/green]" if pf.database_integrity_ok else "[red]FAIL[/red]", "PRAGMA integrity check")
        pf_table.add_row("No Active Runs", "[green]PASS[/green]" if pf.no_active_runs_ok else "[yellow]ATTENTION[/yellow]", "No in-flight executions")

        console.print(pf_table)

    # 2. Recovery bundle info
    if report.recovery_bundle:
        rb = report.recovery_bundle
        console.print(f"\n[bold green]✓ Verified Recovery Bundle Created:[/bold green] [cyan]{rb.bundle_dir}[/cyan]")
        console.print(f"  - Database: {rb.database_backup_path}")
        console.print(f"  - Preserved .env: {rb.env_backup_path}")
        if rb.rclone_backup_path:
            console.print(f"  - Preserved rclone.conf: {rb.rclone_backup_path}")

    # 3. Settings table
    if report.migrated_settings:
        ms_table = Table(title="Effective Migrated Settings (Redacted)", show_header=True)
        ms_table.add_column("Component", style="bold cyan")
        ms_table.add_column("Settings", style="green")

        for comp, vals in report.migrated_settings.items():
            ms_table.add_row(comp, str(vals))

        console.print(ms_table)

    if mode == MigrationMode.CHECK:
        if report.preflight and report.preflight.is_healthy:
            show_success("All preflight checks passed. Ready for migration.")
        elif report.preflight and (
            report.preflight.topology_ok
            and report.preflight.free_space_ok
            and report.preflight.permissions_ok
            and report.preflight.database_integrity_ok
        ):
            show_info("Preflight checks passed (active runs detected; apply will quiesce them).")
        else:
            show_warning("Preflight checks failed.")
            raise typer.Exit(1)
        return

    if not report.success:
        show_warning(f"Migration operation failed: {report.error}")
        raise typer.Exit(1)
    elif mode == MigrationMode.DRY_RUN:
        show_info("Dry-run complete: 0 persistent mutations made. Run with --apply to execute.")
    elif mode == MigrationMode.APPLY:
        show_success("Migration cutover completed successfully!")
        if report.recovery_bundle:
            console.print(f"[dim]To rollback if needed: mascloner migrate --rollback {report.recovery_bundle.bundle_dir}[/dim]")
