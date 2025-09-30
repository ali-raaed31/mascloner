"""Messaging helpers for CLI output."""
from typing import Optional

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()


def show_header(title: str, subtitle: Optional[str] = None, return_panel: bool = False):
    """Display or return a header panel."""
    text = Text()
    text.append(title, style="bold cyan")
    if subtitle:
        text.append("\n")
        text.append(subtitle, style="dim")

    panel = Panel(
        Align.center(text, vertical="middle"),
        border_style="cyan",
        padding=(1, 2),
    )

    if return_panel:
        return panel

    console.print(panel)


def show_success(message: str):
    console.print(f"[green]✓[/green] {message}")


def show_error(message: str):
    console.print(f"[red]✗[/red] {message}")


def show_warning(message: str):
    console.print(f"[yellow]⚠[/yellow] {message}")


def show_info(message: str):
    console.print(f"[blue]ℹ[/blue] {message}")
