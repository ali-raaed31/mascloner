"""Panel components for displaying information."""
from typing import List, Optional

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.syntax import Syntax
from rich.text import Text

console = Console()


def show_changelog(changelog_content: str, max_lines: int = 30):
    """Display a formatted changelog."""
    md = Markdown(changelog_content)
    panel = Panel(
        md,
        title="[bold cyan]📋 Recent Changes[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    )
    console.print(panel)


def show_next_steps(steps: List[str]):
    """Display next steps after an operation."""
    text = Text()
    for i, step in enumerate(steps, 1):
        text.append(f"{i}. ", style="bold cyan")
        text.append(f"{step}\n")

    panel = Panel(
        text,
        title="[bold green]✅ Next Steps[/bold green]",
        border_style="green",
        padding=(1, 2),
    )
    console.print(panel)


def show_error_recovery(error_msg: str, recovery_steps: List[str]):
    """Display error and recovery information."""
    text = Text()
    text.append("Error: ", style="bold red")
    text.append(f"{error_msg}\n\n", style="red")
    text.append("Recovery Steps:\n", style="bold yellow")

    for i, step in enumerate(recovery_steps, 1):
        text.append(f"{i}. ", style="bold yellow")
        text.append(f"{step}\n")

    panel = Panel(
        text,
        title="[bold red]⚠ Update Failed[/bold red]",
        border_style="red",
        padding=(1, 2),
    )
    console.print(panel)


def show_version_info(current: str, available: str, changes: Optional[str] = None):
    """Display version comparison."""
    text = Text()
    text.append("Current Version:  ", style="bold")
    text.append(f"{current}\n", style="yellow")
    text.append("Available Version: ", style="bold")
    text.append(f"{available}\n", style="green")

    if changes:
        text.append("\n")
        text.append(f"{changes}", style="dim")

    panel = Panel(
        text,
        title="[bold cyan]📦 Version Information[/bold cyan]",
        border_style="cyan",
        padding=(1, 2),
    )
    console.print(panel)


def show_confirmation_prompt(
    title: str, details: List[str], default: bool = False
) -> bool:
    """
    Show a formatted confirmation prompt.
    
    Args:
        title: Main question to ask
        details: Additional details to show
        default: Default answer if user just presses Enter
        
    Returns:
        True if user confirms, False otherwise
    """
    from rich.prompt import Confirm

    # Show details first
    if details:
        text = Text()
        for detail in details:
            text.append(f"• {detail}\n", style="dim")
        console.print(text)

    # Ask for confirmation
    return Confirm.ask(title, default=default, console=console)


def show_service_logs(service_name: str, logs: List[str], error_context: bool = False):
    """Display service logs with syntax highlighting."""
    # Join logs and create syntax-highlighted view
    log_text = "\n".join(logs)

    # Use different styling based on context
    style = "monokai" if error_context else "github-dark"

    syntax = Syntax(
        log_text,
        "log",
        theme=style,
        line_numbers=True,
        word_wrap=True,
    )

    title_style = "red" if error_context else "cyan"
    title = f"[bold {title_style}]📜 {service_name} Logs[/bold {title_style}]"

    panel = Panel(
        syntax,
        title=title,
        border_style=title_style,
        padding=(1, 2),
    )
    console.print(panel)


def show_completion_summary(
    success: bool,
    duration: float,
    steps_completed: int,
    total_steps: int,
    warnings: Optional[List[str]] = None,
):
    """Display operation completion summary."""
    text = Text()

    if success:
        text.append("✓ ", style="bold green")
        text.append("Operation completed successfully!\n\n", style="bold green")
    else:
        text.append("✗ ", style="bold red")
        text.append("Operation failed\n\n", style="bold red")

    text.append("Duration:        ", style="bold")
    text.append(f"{duration:.1f} seconds\n", style="cyan")
    text.append("Steps completed: ", style="bold")
    text.append(f"{steps_completed}/{total_steps}\n", style="cyan")

    if warnings:
        text.append("\n")
        text.append("⚠ Warnings:\n", style="bold yellow")
        for warning in warnings:
            text.append(f"  • {warning}\n", style="yellow")

    border_style = "green" if success else "red"
    title = (
        "[bold green]🎉 Success[/bold green]"
        if success
        else "[bold red]⚠ Failed[/bold red]"
    )

    panel = Panel(
        text,
        title=title,
        border_style=border_style,
        padding=(1, 2),
    )
    console.print(panel)
