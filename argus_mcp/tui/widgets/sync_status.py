"""Background sync status widget — config hot-reload indicator.

Shows live sync events, config file hash, and change detection status.
Also provides sync configuration for the settings screen.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import DataTable, Label, Static

from argus_mcp.tui._error_utils import safe_query

logger = logging.getLogger(__name__)


class SyncStatusWidget(Widget):
    """Background sync status indicator for dashboard footer."""

    DEFAULT_CSS = """
    SyncStatusWidget {
        height: auto;
        max-height: 10;
        border: round $accent;
        padding: 0 1;
    }
    #sync-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 0;
    }
    #sync-status-line {
        height: 1;
        color: $text-muted;
    }
    #sync-events {
        height: auto;
        max-height: 6;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._sync_events: List[Dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Config Sync[/b]", id="sync-title")
            yield Static(
                "Config: —   Hash: —   Last sync: —   [dim]● idle[/dim]",
                id="sync-status-line",
            )
            yield DataTable(id="sync-events")

    def on_mount(self) -> None:
        if table := safe_query(self, "#sync-events", DataTable):
            table.add_columns("Time", "Event", "Details")
            table.cursor_type = "none"
            table.zebra_stripes = True

    def update_sync_status(
        self,
        config_file: str = "",
        config_hash: str = "",
        last_sync: str = "",
        is_live: bool = False,
    ) -> None:
        """Update the sync status line."""
        hash_short = config_hash[:8] + "…" if len(config_hash) > 8 else config_hash
        state = "[green]● live[/green]" if is_live else "[dim]● idle[/dim]"
        if w := safe_query(self, "#sync-status-line", Static):
            w.update(
                f"Config: {config_file}   Hash: {hash_short}   Last sync: {last_sync}   {state}"
            )

    def add_sync_event(self, event: Dict[str, Any]) -> None:
        """Add a sync event to the table."""
        self._sync_events.insert(0, event)
        # Keep only last 20
        self._sync_events = self._sync_events[:20]
        self._refresh_events()

    def _refresh_events(self) -> None:
        if table := safe_query(self, "#sync-events", DataTable):
            table.clear()
            for evt in self._sync_events:
                time = evt.get("time", "—")
                event_type = evt.get("type", "—")
                details = evt.get("details", "")

                if event_type == "changed":
                    event_display = "[yellow]⟳ changed[/yellow]"
                elif event_type == "no-change":
                    event_display = "[green]✓ no changes[/green]"
                elif event_type == "error":
                    event_display = "[red]✕ error[/red]"
                else:
                    event_display = event_type

                table.add_row(str(time), event_display, details)


class SyncConfigPanel(Widget):
    """Sync configuration panel for settings."""

    DEFAULT_CSS = """
    SyncConfigPanel {
        height: auto;
        max-height: 14;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        from textual.widgets import Checkbox, Input, Select

        with Vertical():
            yield Label("[b]Background Sync[/b]")

            with Horizontal(classes="setting-row"):
                yield Label("Hot Reload:", classes="setting-label")
                yield Checkbox("Enabled", value=True, id="sync-enabled-check")

            with Horizontal(classes="setting-row"):
                yield Label("Watch file:", classes="setting-label")
                yield Static("config.yaml", id="sync-watch-file")

            with Horizontal(classes="setting-row"):
                yield Label("Interval (s):", classes="setting-label")
                yield Input(placeholder="120", id="sync-interval-input", type="number")

            with Horizontal(classes="setting-row"):
                yield Label("Change Detection:", classes="setting-label")
                yield Select(
                    [
                        ("hash — SHA-256 comparison", "hash"),
                        ("mtime — file modification time", "mtime"),
                        ("inotify — OS file watcher", "inotify"),
                    ],
                    value="hash",
                    id="sync-detection-select",
                    allow_blank=False,
                )

            with Horizontal(classes="setting-row"):
                yield Label("On failure:", classes="setting-label")
                yield Select(
                    [
                        ("exponential backoff", "backoff"),
                        ("fixed interval", "fixed"),
                        ("stop", "stop"),
                    ],
                    value="backoff",
                    id="sync-failure-select",
                    allow_blank=False,
                )
