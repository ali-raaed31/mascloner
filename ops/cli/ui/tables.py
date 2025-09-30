"""Table components for displaying structured data."""
from typing import List, Tuple

from rich.console import Console
from rich.table import Table

console = Console()


def create_service_status_table(services: List[Tuple[str, str, str]]) -> Table:
    """
    Create a table showing service status.
    
    Args:
        services: List of (service_name, status, action) tuples
    """
    table = Table(
        title="Service Status",
        title_style="bold cyan",
        show_header=True,
        header_style="bold blue",
    )

    table.add_column("Service", style="cyan", no_wrap=True)
    table.add_column("Status", justify="center")
    table.add_column("Action", style="dim")

    for service_name, status, action in services:
        # Style status based on value
        if status == "active":
            status_str = "[green]● active[/green]"
        elif status == "stopped":
            status_str = "[red]● stopped[/red]"
        elif status == "failed":
            status_str = "[red]✗ failed[/red]"
        else:
            status_str = f"[yellow]● {status}[/yellow]"

        table.add_row(service_name, status_str, action)

    return table


def create_file_changes_table(
    added: List[str], removed: List[str], modified: List[str]
) -> Table:
    """
    Create a table showing file changes.
    
    Args:
        added: List of added files
        removed: List of removed files
        modified: List of modified files
    """
    table = Table(
        title="File Changes",
        title_style="bold cyan",
        show_header=True,
        header_style="bold blue",
    )

    table.add_column("Type", style="bold", width=10)
    table.add_column("Count", justify="right", style="cyan")
    table.add_column("Examples (showing max 5)", style="dim")

    if added:
        examples = "\n".join(f"+ {f}" for f in added[:5])
        table.add_row("[green]Added[/green]", str(len(added)), examples)

    if removed:
        examples = "\n".join(f"- {f}" for f in removed[:5])
        table.add_row("[red]Removed[/red]", str(len(removed)), examples)

    if modified:
        examples = "\n".join(f"~ {f}" for f in modified[:5])
        table.add_row("[yellow]Modified[/yellow]", str(len(modified)), examples)

    if not added and not removed and not modified:
        table.add_row("[dim]No changes[/dim]", "0", "")

    return table


def create_update_summary_table(
    version_from: str, version_to: str, files_changed: int, services_restarted: int
) -> Table:
    """Create a summary table for the update."""
    table = Table(
        title="Update Summary",
        title_style="bold cyan",
        show_header=False,
        box=None,
        padding=(0, 1),
    )

    table.add_column("Key", style="bold blue")
    table.add_column("Value", style="cyan")

    table.add_row("From Version", version_from)
    table.add_row("To Version", version_to)
    table.add_row("Files Changed", str(files_changed))
    table.add_row("Services Restarted", str(services_restarted))

    return table


def create_health_check_table(checks: List[Tuple[str, bool, str]]) -> Table:
    """
    Create a health check results table.
    
    Args:
        checks: List of (check_name, passed, details) tuples
    """
    table = Table(
        title="Health Check Results",
        title_style="bold cyan",
        show_header=True,
        header_style="bold blue",
    )

    table.add_column("Check", style="cyan")
    table.add_column("Status", justify="center", width=10)
    table.add_column("Details", style="dim")

    for check_name, passed, details in checks:
        status = "[green]✓ PASS[/green]" if passed else "[red]✗ FAIL[/red]"
        table.add_row(check_name, status, details)

    return table


def create_backup_info_table(backup_path: str, size: str, files: int) -> Table:
    """Create a backup information table."""
    table = Table(
        title="Backup Information",
        title_style="bold cyan",
        show_header=False,
        box=None,
        padding=(0, 1),
    )

    table.add_column("Key", style="bold blue")
    table.add_column("Value", style="cyan")

    table.add_row("Location", backup_path)
    table.add_row("Size", size)
    table.add_row("Files", str(files))

    return table
