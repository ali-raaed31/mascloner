#!/usr/bin/env python3
"""
MasCloner CLI - Main entry point for the command-line interface.

This provides a modern, user-friendly CLI with Rich UI components.
"""
import sys

import typer
from click.exceptions import ClickException
from rich.console import Console

from ops.cli.commands import update, status, rollback

# Initialize Typer app
app = typer.Typer(
    name="mascloner",
    help="MasCloner - Google Drive to Nextcloud sync management CLI",
    add_completion=True,
    rich_markup_mode="rich",
)

# Initialize Rich console
console = Console()

# Register commands
app.command(name="update")(update.main)
app.command(name="status")(status.main)
app.command(name="rollback")(rollback.main)


@app.callback()
def callback():
    """
    MasCloner CLI - Manage your MasCloner installation.
    
    Use 'mascloner COMMAND --help' for more information on a command.
    """
    pass


def cli():
    """Entry point for the CLI."""
    try:
        app()
    except typer.Exit as exc:
        raise SystemExit(exc.exit_code)
    except KeyboardInterrupt:
        console.print("\n[yellow]⚠ Operation cancelled by user[/yellow]")
        sys.exit(130)
    except ClickException as exc:
        console.print(f"[red]✗ {exc.format_message()}[/red]")
        sys.exit(exc.exit_code)
    except Exception as e:
        console.print(f"[red]✗ Error: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    cli()
