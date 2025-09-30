"""Status command - Check MasCloner installation status."""
import typer
from rich.console import Console
from rich.table import Table

from ops.cli.ui.progress import show_header, show_info, show_success, show_warning
from ops.cli.ui.tables import create_service_status_table
from ops.cli.utils import (
    check_http_endpoint,
    check_systemd_service,
    get_current_version,
    get_install_dir,
)

console = Console()


def main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show detailed information")
):
    """
    Check the status of your MasCloner installation.
    
    Shows:
    - Current version
    - Service status
    - Health check results
    - Configuration status
    """
    show_header("MasCloner Status", "Current installation status")

    install_dir = get_install_dir()

    if not install_dir.exists():
        show_warning(f"Installation not found at {install_dir}")
        raise typer.Exit(1)

    # Show version
    version = get_current_version(install_dir)
    console.print(f"\n[bold]Version:[/bold] [cyan]{version}[/cyan]")
    console.print(f"[bold]Installation:[/bold] [cyan]{install_dir}[/cyan]\n")

    # Check services
    services = ["mascloner-api", "mascloner-ui", "mascloner-tunnel"]
    service_statuses = []

    for service in services:
        is_active, status = check_systemd_service(service)
        action = "Running" if is_active else "Stopped"
        service_statuses.append((service, status, action))

    table = create_service_status_table(service_statuses)
    console.print(table)
    console.print()

    # Run health checks
    show_info("Running health checks...")
    health_checks = []

    # API
    api_ok = check_http_endpoint("http://127.0.0.1:8787/health", timeout=5)
    health_checks.append(("API", api_ok))

    # UI
    ui_ok = check_http_endpoint("http://127.0.0.1:8501", timeout=5)
    health_checks.append(("UI", ui_ok))

    # Database
    db_ok = check_http_endpoint("http://127.0.0.1:8787/status", timeout=5)
    health_checks.append(("Database", db_ok))

    # Show health check results
    health_table = Table(title="Health Checks", title_style="bold cyan")
    health_table.add_column("Component", style="cyan")
    health_table.add_column("Status", justify="center")

    for component, ok in health_checks:
        status = "[green]✓ Healthy[/green]" if ok else "[red]✗ Unhealthy[/red]"
        health_table.add_row(component, status)

    console.print(health_table)
    console.print()

    # Overall status
    all_services_ok = all(status == "active" for _, status, _ in service_statuses if status != "not_installed")
    all_health_ok = all(ok for _, ok in health_checks)

    if all_services_ok and all_health_ok:
        show_success("All systems operational")
    elif all_services_ok:
        show_warning("Services running but some health checks failed")
    else:
        show_warning("Some services are not running")

    if verbose:
        console.print("\n[bold]Additional Information:[/bold]")
        console.print(f"  Config: {install_dir / 'etc'}")
        console.print(f"  Data: {install_dir / 'data'}")
        console.print(f"  Logs: {install_dir / 'logs'}")
        console.print(f"  Virtual env: {install_dir / '.venv'}")
