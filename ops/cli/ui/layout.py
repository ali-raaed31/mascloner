"""Two-column layout for live update progress display."""
from contextlib import contextmanager
from typing import Optional

from rich.console import Console, Group
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.spinner import Spinner
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

    def update_status(self, content) -> None:
        """Update the left status panel."""
        self.status_content = content
        self._refresh()

    def add_log(self, message: str, style: str = "white") -> None:
        """Add a log line to the right panel."""
        self.log_lines.append(f"[{style}]{message}[/{style}]")
        # Keep last 20 lines
        if len(self.log_lines) > 20:
            self.log_lines = self.log_lines[-20:]
        self._refresh()

    def _refresh(self) -> None:
        """Refresh the layout with current content."""
        # Left panel - status
        status_panel = Panel(
            self.status_content,
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
def live_spinner(layout: UpdateLayout, message: str):
    """Context manager for live spinner with layout updates."""
    spinner = Spinner("dots", text=message, style="bold blue")
    
    # Create a group with spinner and layout
    def make_renderable():
        return Group(spinner, layout.render())
    
    with Live(make_renderable(), console=console, refresh_per_second=10) as live:
        layout.add_log(f"⏳ {message}...", style="blue")
        try:
            yield layout
            layout.add_log(f"✓ {message} - Done", style="green")
        except Exception as e:
            layout.add_log(f"✗ {message} - Failed: {e}", style="red")
            raise
        finally:
            live.update(layout.render())
