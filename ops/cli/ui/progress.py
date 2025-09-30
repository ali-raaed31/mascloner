"""Progress indicators and status components."""
from contextlib import contextmanager
from typing import Optional

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Table
from rich.text import Text

console = Console()


class UpdateProgress:
    """Manages progress display for update operations."""

    def __init__(self):
        self.progress = Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=console,
        )
        self.tasks: dict[str, TaskID] = {}
        self.live: Optional[Live] = None

    def add_task(self, name: str, description: str, total: float = 100.0) -> TaskID:
        """Add a progress task."""
        task_id = self.progress.add_task(description, total=total)
        self.tasks[name] = task_id
        return task_id

    def update(self, name: str, advance: float = 1.0, description: Optional[str] = None):
        """Update a progress task."""
        if name in self.tasks:
            kwargs = {"advance": advance}
            if description:
                kwargs["description"] = description
            self.progress.update(self.tasks[name], **kwargs)

    def complete(self, name: str, description: Optional[str] = None):
        """Mark a task as complete."""
        if name in self.tasks:
            kwargs = {"completed": 100}
            if description:
                kwargs["description"] = description
            self.progress.update(self.tasks[name], **kwargs)

    @contextmanager
    def live_context(self):
        """Context manager for live progress updates."""
        with self.progress:
            yield self


class StepIndicator:
    """Shows current step in a multi-step process."""

    def __init__(self, total_steps: int):
        self.total_steps = total_steps
        self.current_step = 0
        self.steps: list[tuple[str, str]] = []  # (name, status)

    def add_step(self, name: str):
        """Add a step to track."""
        self.steps.append((name, "pending"))

    def start_step(self, step_index: int):
        """Mark a step as in progress."""
        self.current_step = step_index
        if step_index < len(self.steps):
            name, _ = self.steps[step_index]
            self.steps[step_index] = (name, "in_progress")

    def complete_step(self, step_index: int, success: bool = True):
        """Mark a step as complete."""
        if step_index < len(self.steps):
            name, _ = self.steps[step_index]
            status = "success" if success else "failed"
            self.steps[step_index] = (name, status)

    def render(self) -> Table:
        """Render the step indicator as a table."""
        table = Table.grid(padding=(0, 2))
        table.add_column(justify="center", style="bold")
        table.add_column(justify="left")

        for i, (name, status) in enumerate(self.steps):
            if status == "success":
                icon = "[green]✓[/green]"
            elif status == "failed":
                icon = "[red]✗[/red]"
            elif status == "in_progress":
                icon = "[yellow]⠋[/yellow]"
            else:
                icon = "[dim]○[/dim]"

            step_text = Text(name)
            if status == "in_progress":
                step_text.stylize("bold yellow")
            elif status == "success":
                step_text.stylize("green")
            elif status == "failed":
                step_text.stylize("red")
            else:
                step_text.stylize("dim")

            table.add_row(icon, step_text)

        return table


@contextmanager
def spinner(message: str):
    """Show a spinner with a message."""
    with console.status(f"[bold blue]{message}...", spinner="dots"):
        yield


def show_header(title: str, subtitle: Optional[str] = None):
    """Display a formatted header."""
    text = Text()
    text.append(title, style="bold cyan")
    if subtitle:
        text.append("\n")
        text.append(subtitle, style="dim")

    panel = Panel(
        text,
        border_style="cyan",
        padding=(1, 2),
    )
    console.print(panel)


def show_success(message: str):
    """Display a success message."""
    console.print(f"[green]✓[/green] {message}")


def show_error(message: str):
    """Display an error message."""
    console.print(f"[red]✗[/red] {message}")


def show_warning(message: str):
    """Display a warning message."""
    console.print(f"[yellow]⚠[/yellow] {message}")


def show_info(message: str):
    """Display an info message."""
    console.print(f"[blue]ℹ[/blue] {message}")
