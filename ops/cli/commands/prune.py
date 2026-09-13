"""Prune command - Apply history retention policy to expired SyncRuns (ADR 0008)."""

from typing import Optional
import typer
from rich.console import Console
from rich.table import Table

from ops.cli.ui.progress import show_header, show_info, show_success, show_warning

console = Console()


def main(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Simulate retention without deleting records or log files",
    ),
    days: Optional[int] = typer.Option(
        None,
        "--days",
        "-d",
        help="Override retention period in days (defaults to configured RetentionPolicy, 60 days)",
    ),
    batch_size: int = typer.Option(
        100,
        "--batch-size",
        "-b",
        help="Batch size for retention deletions",
    ),
) -> None:
    """Prune expired SyncRun history, FileEvents, and per-run logs."""
    action_str = "Simulating History Pruning (Dry-Run)" if dry_run else "Pruning Expired History"
    show_header("MasCloner Retention", action_str)

    try:
        from app.retention import RetentionService

        service = RetentionService.get_instance()
        report = service.apply_retention(
            retention_days=days,
            dry_run=dry_run,
            batch_size=batch_size,
        )

        if not report.success:
            show_warning(f"Retention operation failed: {report.error}")
            raise typer.Exit(1)

        table = Table(title="Retention Operation Summary", show_header=True)
        table.add_column("Metric", style="bold cyan")
        table.add_column("Value", style="green")

        table.add_row("Mode", "Dry-Run" if report.is_dry_run else "Applied")
        table.add_row("Retention Period", f"{report.retention_days} days")
        table.add_row("Cutoff (UTC)", report.cutoff_utc.strftime("%Y-%m-%d %H:%M:%S UTC"))
        table.add_row("Runs Evaluated", str(report.runs_evaluated))
        table.add_row(
            "Runs Pruned" if not report.is_dry_run else "Runs Targeted",
            str(report.runs_deleted),
        )
        table.add_row(
            "Events Pruned" if not report.is_dry_run else "Events Targeted",
            str(report.events_deleted),
        )
        table.add_row(
            "Log Files Removed" if not report.is_dry_run else "Log Files Targeted",
            str(report.logs_deleted),
        )
        table.add_row("Duration", f"{report.duration_seconds:.2f}s")

        console.print(table)

        if report.log_deletion_failures:
            show_warning(f"Encountered {len(report.log_deletion_failures)} log deletion issue(s):")
            for fail in report.log_deletion_failures:
                console.print(f"  - [yellow]{fail}[/yellow]")

        if report.is_dry_run:
            show_info(f"Dry run complete: {report.runs_deleted} runs would be deleted.")
        else:
            show_success(f"History pruned successfully: {report.runs_deleted} runs removed.")

    except typer.Exit:
        raise
    except Exception as exc:
        show_warning(f"Error during retention operation: {exc}")
        raise typer.Exit(1)
