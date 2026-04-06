"""Health checks & circuit breaker widget.

Displays per-backend health indicators, circuit-breaker state,
probe history, and latency. Provides server lifecycle controls
(reconnect, reload, shutdown) per-backend and globally.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, DataTable, Label, Static

from argus_mcp.tui._error_utils import safe_query

logger = logging.getLogger(__name__)

# Map circuit state to display
_CIRCUIT_DISPLAY = {
    "closed": "[green]CLOSED[/green]",
    "open": "[red]OPEN[/red]",
    "half-open": "[yellow]HALF-OPEN[/yellow]",
}


class HealthPanel(Widget):
    """Shows backend health status, circuit breaker state, and latency.

    Feed data via :meth:`update_from_backends` with a list of backend
    dicts (from the management API ``/manage/v1/backends`` response).

    Provides lifecycle action buttons:
    - **Reconnect** — reconnect the selected backend
    - **Reload Config** — hot-reload configuration (add/remove/change backends)
    - **Shutdown Server** — gracefully shut down the entire Argus server
    """

    class BackendReconnect(Message):
        """Posted when the user wants to reconnect a specific backend."""

        def __init__(self, backend_name: str) -> None:
            self.backend_name = backend_name
            super().__init__()

    class ReloadRequested(Message):
        """Posted when the user clicks Reload Config."""

    class ShutdownRequested(Message):
        """Posted when the user clicks Shutdown Server."""

    class AddBackendRequested(Message):
        """Posted when the user clicks Add Backend."""

    class RestartRequested(Message):
        """Posted when the user clicks Restart Server."""

    DEFAULT_CSS = """
    HealthPanel {
        height: auto;
        max-height: 28;
        border: round $accent;
        padding: 0 1;
    }
    #health-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 0;
    }
    #health-summary {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    #health-table {
        height: auto;
        max-height: 10;
    }
    #health-actions-bar {
        height: 3;
        padding: 0 1;
        margin-top: 1;
    }
    #health-actions-bar Button {
        margin-right: 1;
    }
    #health-action-status {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    #circuit-breaker-info {
        height: auto;
        max-height: 4;
        padding: 0 1;
        margin-top: 1;
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._backend_names: List[str] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Health Status[/b]", id="health-title")
            yield Static("Healthy: 0  Degraded: 0  Unhealthy: 0", id="health-summary")
            yield DataTable(id="health-table")
            with Horizontal(id="health-actions-bar"):
                yield Button("Reconnect", id="btn-health-reconnect", variant="warning")
                yield Button("Add Backend", id="btn-health-add-backend", variant="success")
                yield Button("Reload Config", id="btn-health-reload", variant="primary")
                yield Button("Restart Server", id="btn-health-restart", variant="warning")
                yield Button("Shutdown Server", id="btn-health-shutdown", variant="error")
            yield Static("", id="health-action-status")
            yield Static("", id="circuit-breaker-info")

    def on_mount(self) -> None:
        if table := safe_query(self, "#health-table", DataTable):
            table.add_columns("Server", "State", "Circuit", "Last Ping", "Latency")
            table.cursor_type = "row"
            table.zebra_stripes = True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle action button presses."""
        btn_id = event.button.id
        if btn_id == "btn-health-reconnect":
            self._action_reconnect_selected()
        elif btn_id == "btn-health-add-backend":
            self.post_message(self.AddBackendRequested())
        elif btn_id == "btn-health-reload":
            self.post_message(self.ReloadRequested())
        elif btn_id == "btn-health-restart":
            self.post_message(self.RestartRequested())
        elif btn_id == "btn-health-shutdown":
            self.post_message(self.ShutdownRequested())

    def _action_reconnect_selected(self) -> None:
        """Reconnect the backend selected in the table."""
        name = self._get_selected_backend()
        if name is None:
            self.app.notify("Select a backend row first.", severity="warning")
            return
        self.post_message(self.BackendReconnect(backend_name=name))

    def _get_selected_backend(self) -> Optional[str]:
        """Return the backend name at the currently highlighted row."""
        if table := safe_query(self, "#health-table", DataTable):
            idx = table.cursor_row
            if 0 <= idx < len(self._backend_names):
                return self._backend_names[idx]
        return None

    def set_action_status(self, text: str) -> None:
        """Update the action status line below the buttons."""
        if w := safe_query(self, "#health-action-status", Static):
            w.update(text)

    @staticmethod
    def _classify_backend(b: Dict[str, Any]) -> tuple:
        """Return (name, state_display, category, circuit_display, last_check, lat_str, circuit_info)."""
        name = b.get("name", "?")
        phase = b.get("phase", "unknown").lower()
        health = b.get("health", {})
        health_status = health.get("status", "unknown") if health else "unknown"
        last_check = health.get("last_check", "—") if health else "—"
        latency = health.get("latency_ms") if health else None
        lat_str = f"{latency:.0f}ms" if latency else "—"
        circuit = b.get("circuit_state", "closed")

        if phase == "ready" or health_status == "healthy":
            category = "healthy"
            state_display = "[green]● healthy[/green]"
        elif phase == "degraded" or health_status == "degraded":
            category = "degraded"
            state_display = "[yellow]◑ degraded[/yellow]"
        else:
            category = "unhealthy"
            state_display = "[red]✕ unhealthy[/red]"

        circuit_display = _CIRCUIT_DISPLAY.get(circuit, f"[dim]{circuit}[/dim]")

        if isinstance(last_check, str) and "T" in last_check:
            last_check = last_check.split("T")[1][:8]

        circuit_info = None
        if circuit and circuit != "closed":
            failures = b.get("failure_count", "?")
            cooldown = b.get("cooldown_remaining", "?")
            circuit_info = (
                f"  {name}: {circuit.upper()} — {failures} failures, cooldown: {cooldown}s"
            )

        return (
            name,
            state_display,
            category,
            circuit_display,
            str(last_check),
            lat_str,
            circuit_info,
        )

    def update_from_backends(self, backends: List[Dict[str, Any]]) -> None:
        """Refresh the health table from backend data."""
        table = safe_query(self, "#health-table", DataTable)
        if table is None:
            return
        table.clear()
        self._backend_names.clear()

        healthy = degraded = unhealthy = 0
        circuit_info_lines = []

        for b in backends:
            (
                name,
                state_display,
                category,
                circuit_display,
                last_check,
                lat_str,
                circuit_info,
            ) = self._classify_backend(b)
            self._backend_names.append(name)

            if category == "healthy":
                healthy += 1
            elif category == "degraded":
                degraded += 1
            else:
                unhealthy += 1

            table.add_row(name, state_display, circuit_display, last_check, lat_str)

            if circuit_info:
                circuit_info_lines.append(circuit_info)

        summary = f"Healthy: {healthy}   Degraded: {degraded}   Unhealthy: {unhealthy}"
        if sw := safe_query(self, "#health-summary", Static):
            sw.update(summary)

        if cw := safe_query(self, "#circuit-breaker-info", Static):
            if circuit_info_lines:
                cw.update("[b]Circuit Breakers:[/b]\n" + "\n".join(circuit_info_lines))
            else:
                cw.update("")
