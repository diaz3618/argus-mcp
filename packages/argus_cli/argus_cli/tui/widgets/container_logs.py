"""Container log viewer — displays streaming logs with severity coloring."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widget import Widget
from textual.widgets import Input, RichLog, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult


# Map severity keywords to Rich markup styles
_SEVERITY_STYLES = {
    "error": "bold red",
    "err": "bold red",
    "fatal": "bold red",
    "panic": "bold red",
    "warn": "yellow",
    "warning": "yellow",
    "info": "blue",
    "debug": "dim",
    "trace": "dim italic",
}


def _style_log_line(line: str) -> str:
    """Apply Rich markup based on severity keywords in the log line."""
    lower = line.lower()
    for keyword, style in _SEVERITY_STYLES.items():
        if keyword in lower:
            return f"[{style}]{line}[/{style}]"
    return line


class ContainerLogViewer(Widget):
    """Scrolling log viewer with severity coloring and search.

    Supports multiple containers — logs are prefixed with the container
    name to distinguish sources.
    """

    DEFAULT_CSS = """
    ContainerLogViewer {
        height: 1fr;
    }
    ContainerLogViewer RichLog {
        height: 1fr;
        border: round $panel-lighten-2;
    }
    ContainerLogViewer #log-search-bar {
        dock: top;
        height: 3;
        padding: 0 1;
    }
    ContainerLogViewer #log-header {
        dock: top;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._search_query: str = ""

    def compose(self) -> ComposeResult:
        yield Static("[b]Container Logs[/b]", id="log-header")
        yield Input(
            placeholder="Search logs… (text filter)",
            id="log-search-input",
        )
        yield RichLog(id="container-log", highlight=True, markup=True, wrap=True)

    def append_log(
        self,
        line: str,
        *,
        container_name: str = "",
        stream: str = "",
    ) -> None:
        """Append a log line to the viewer.

        Parameters
        ----------
        line:
            The log text.
        container_name:
            Optional container name prefix.
        stream:
            Optional stream identifier (stdout/stderr).
        """
        if self._search_query and self._search_query not in line.lower():
            return
        prefix = ""
        if container_name:
            prefix = f"[bold cyan]{container_name}[/bold cyan] │ "
        if stream == "stderr":
            prefix += "[red]ERR[/red] "
        styled = _style_log_line(line)
        log_widget = self.query_one("#container-log", RichLog)
        log_widget.write(f"{prefix}{styled}")

    def clear_logs(self) -> None:
        """Clear all log content."""
        log_widget = self.query_one("#container-log", RichLog)
        log_widget.clear()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "log-search-input":
            self._search_query = event.value.strip().lower()
