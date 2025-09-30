"""Two-column layout for live update progress display."""
from contextlib import contextmanager
from typing import List, Optional, Tuple

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

console = Console()


class UpdateLayout:
    """Manages a two-column layout for update progress."""

    def __init__(self):
        self.layout = Layout()
        self.layout.split_row(
            Layout(name="status", ratio=1),
            Layout(name="logs", ratio=2),
        )
        self.log_lines: list[str] = []
        self.status_content = Text("Initializing...", style="yellow")
        self.steps: List[Tuple[str, str]] = []  # (name, status)
        self.current_step_index = -1

    def update_status(self, content) -> None:
        """Update the left status panel."""
        self.status_content = content
        self._refresh()

    def add_log(self, message: str, style: str = "white") -> None:
        """Add a log line to the right panel."""
        self.log_lines.append(f"[{style}]{message}[/{style}]")
        # Keep last 30 lines
        if len(self.log_lines) > 30:
            self.log_lines = self.log_lines[-30:]
        self._refresh()

    def add_step(self, name: str) -> None:
        """Add a step to track."""
        self.steps.append((name, "pending"))
        self._refresh()

    def start_step(self, index: int) -> None:
        """Mark a step as in progress."""
        if 0 <= index < len(self.steps):
            name, _ = self.steps[index]
            self.steps[index] = (name, "in_progress")
            self.current_step_index = index
            self.add_log(f"Starting: {name}", style="blue")
            self._refresh()

    def complete_step(self, index: int, success: bool = True) -> None:
        """Mark a step as complete or failed."""
        if 0 <= index < len(self.steps):
            name, _ = self.steps[index]
            status = "success" if success else "failed"
            self.steps[index] = (name, status)
            if success:
                self.add_log(f"✓ Completed: {name}", style="green")
            else:
                self.add_log(f"✗ Failed: {name}", style="red")
            self._refresh()

    def _render_steps(self) -> Table:
        """Render steps as a table."""
        table = Table.grid(padding=(0, 2))
        table.add_column(justify="center", style="bold")
        table.add_column(justify="left")

        for name, status in self.steps:
            if status == "success":
                icon = "[green]✓[/green]"
                style = "green"
            elif status == "failed":
                icon = "[red]✗[/red]"
                style = "red"
            elif status == "in_progress":
                icon = "[yellow]⠋[/yellow]"
                style = "bold yellow"
            else:
                icon = "[dim]○[/dim]"
                style = "dim"

            text = Text(name, style=style)
            table.add_row(icon, text)

        return table

    def _refresh(self) -> None:
        """Refresh the layout with current content."""
        # Left panel - status with steps
        if self.steps:
            status_content = Group(
                Text("Update Progress", style="bold cyan", justify="center"),
                Text(""),
                self._render_steps()
            )
        else:
            status_content = self.status_content

        status_panel = Panel(
            status_content,
            title="[bold cyan]Status[/bold cyan]",
            border_style="cyan",
        )

        # Right panel - logs
        log_text = Text.from_markup("\n".join(self.log_lines)) if self.log_lines else Text("No logs yet...", style="dim")
        log_panel = Panel(
            log_text,
            title="[bold blue]Activity Log[/bold blue]",
            border_style="blue",
        )

        self.layout["status"].update(status_panel)
        self.layout["logs"].update(log_panel)

    def render(self):
        """Return the layout for rendering."""
        self._refresh()
        return self.layout


@contextmanager
def step_context(layout: UpdateLayout, step_index: int):
    """Context manager for executing a step with automatic status updates."""
    layout.start_step(step_index)
    try:
        yield layout
        layout.complete_step(step_index, success=True)
    except Exception as e:
        layout.complete_step(step_index, success=False)
        raise
