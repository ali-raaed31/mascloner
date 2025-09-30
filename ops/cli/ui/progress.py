"""Progress indicators and status components."""
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import List, Optional

from rich.align import Align
from rich.console import Console, Group
from rich.layout import Layout
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


@dataclass
class LogBuffer:
    """Collects log lines for the right-hand panel."""

    max_lines: int = 50
    lines: List[str] = field(default_factory=list)

    def add(self, message: str) -> None:
        self.lines.append(message)
        if len(self.lines) > self.max_lines:
            self.lines = self.lines[-self.max_lines :]

    def render(self) -> Panel:
        content = "\n".join(self.lines) if self.lines else "(log output will appear here)"
        return Panel(
            content,
            title="[bold blue]Live Log[/bold blue]",
            title_align="left",
            border_style="blue",
            padding=(1, 2),
        )


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


class StepIndicator:
    """Shows current step in a multi-step process."""

    def __init__(self, total_steps: int):
        self.total_steps = total_steps
        self.current_step = 0
        self.steps: List[tuple[str, str]] = []  # (name, status)

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

    def render(self) -> Panel:
        table = Table.grid(padding=(0, 1))
        table.add_column(justify="center", style="bold")
        table.add_column(justify="left")

        for name, status in self.steps:
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

        return Panel(
            table,
            title="[bold cyan]Update Steps[/bold cyan]",
            border_style="cyan",
            padding=(0, 1),
        )


class UpdateLayout:
    """Live two-column layout with status on left and log on right."""

    def __init__(self):
        self.log_buffer = LogBuffer()
        self.step_indicator = StepIndicator(total_steps=10)
        self.progress = UpdateProgress()
        self.status_panels: List[Panel] = []

        self.layout = Layout()
        self.layout.split_column(
            Layout(name="header", size=5),
            Layout(name="body"),
        )
        self.layout["body"].split_row(
            Layout(name="left"),
            Layout(name="right", ratio=1),
        )

    def set_header(self, title: str, subtitle: Optional[str] = None):
        header = show_header(title, subtitle, return_panel=True)
        self.layout["header"].update(header)

    def update_left(self):
        content = [self.step_indicator.render()]
        if self.status_panels:
            content.extend(self.status_panels)
        content.append(Panel(self.progress.progress, title="[bold cyan]Progress[/bold cyan]"))
        group = Group(*content)
        self.layout["left"].update(group)

    def update_right(self):
        self.layout["right"].update(self.log_buffer.render())

    def log(self, message: str):
        self.log_buffer.add(message)
        self.update_right()

    @contextmanager
    def live(self):
        self.update_left()
        self.update_right()
        with Live(self.layout, console=console, refresh_per_second=10):
            yield self


@contextmanager
def spinner(message: str):
    """Show a spinner with a message."""
    with console.status(f"[bold blue]{message}...", spinner="dots"):
        yield


def show_header(title: str, subtitle: Optional[str] = None, return_panel: bool = False):
    """Display a formatted header."""
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
