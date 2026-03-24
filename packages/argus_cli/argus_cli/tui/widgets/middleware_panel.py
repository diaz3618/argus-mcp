"""Middleware pipeline widget — visual pipeline editor.

Shows the ordered middleware chain with per-layer toggle,
status, and request flow visualization.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import DataTable, Label, Static

from argus_cli.tui._error_utils import safe_query

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)

# Default middleware layers in order
_DEFAULT_LAYERS = [
    {"name": "Recovery", "always_on": True, "status": "enabled"},
    {"name": "Header Validation", "always_on": False, "status": "enabled"},
    {"name": "Authentication", "always_on": False, "status": "enabled"},
    {"name": "Authorization", "always_on": False, "status": "enabled"},
    {"name": "Audit Logger", "always_on": False, "status": "enabled"},
    {"name": "Telemetry", "always_on": False, "status": "enabled"},
    {"name": "Discovery", "always_on": False, "status": "enabled"},
    {"name": "MCP Parsing", "always_on": True, "status": "enabled"},
    {"name": "Tool Filter", "always_on": False, "status": "enabled"},
    {"name": "Tool Call Filter", "always_on": False, "status": "disabled"},
    {"name": "Backend Router", "always_on": True, "status": "enabled"},
]


class MiddlewarePipelineWidget(Widget):
    """Visual middleware pipeline editor."""

    DEFAULT_CSS = """
    MiddlewarePipelineWidget {
        height: auto;
        max-height: 20;
        border: round $accent;
        padding: 0 1;
    }
    #mw-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 0;
    }
    #mw-info {
        height: 1;
        color: $text-muted;
    }
    #mw-table {
        height: auto;
        max-height: 14;
    }
    #mw-summary {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._layers: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Middleware Pipeline[/b]", id="mw-title")
            yield Static(
                "Request flows top → bottom.  Toggle to disable.",
                id="mw-info",
            )
            yield DataTable(id="mw-table")
            yield Static("", id="mw-summary")

    def on_mount(self) -> None:
        if table := safe_query(self, "#mw-table", DataTable):
            table.add_columns("#", "Layer", "Status", "Note")
            table.cursor_type = "row"
            table.zebra_stripes = True
        if not self._layers:
            self.update_pipeline(_DEFAULT_LAYERS)

    def update_pipeline(self, layers: list[dict[str, Any]]) -> None:
        """Refresh the pipeline table with layer data."""
        self._layers = layers
        table = safe_query(self, "#mw-table", DataTable)
        if table is None:
            return
        table.clear()

        active = 0
        total = len(layers)

        for i, layer in enumerate(layers, 1):
            name = layer.get("name", "?")
            always_on = layer.get("always_on", False)
            status = layer.get("status", "enabled")
            note = layer.get("note", "")

            if always_on:
                status_display = "[green][✓][/green] always on"
                active += 1
            elif status == "enabled":
                status_display = "[green][✓][/green]"
                active += 1
                if note:
                    status_display += f" {note}"
            else:
                status_display = "[dim][ ] disabled[/dim]"

            table.add_row(str(i), name, status_display, note if not always_on else "")

        custom = sum(1 for layer in layers if layer.get("custom", False))
        summary = f"Active: {active}/{total} │ Custom middleware: {custom}"
        if w := safe_query(self, "#mw-summary", Static):
            w.update(summary)
