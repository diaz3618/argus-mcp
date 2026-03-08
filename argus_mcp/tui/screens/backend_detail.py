"""Backend detail modal — shows full lifecycle status for a backend server.

Displays phase, conditions log, health metrics, capabilities count,
and actions (restart, disconnect, force health check).
Launched by pressing Enter on a backend row in the Dashboard.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Label, Static

# Phase → (icon, color)
_PHASE_STYLE: Dict[str, tuple] = {
    "pending": ("◌", "dim"),
    "initializing": ("⟳", "yellow"),
    "ready": ("●", "green"),
    "degraded": ("◑", "dark_orange"),
    "failed": ("✕", "red"),
    "shutting_down": ("◑", "cyan"),
}


class BackendDetailModal(ModalScreen[Optional[str]]):
    """Modal showing full lifecycle detail for a single backend.

    Returns the backend name if user clicks Restart, or ``None`` if
    dismissed.
    """

    DEFAULT_CSS = """
    BackendDetailModal {
        align: center middle;
    }
    #backend-detail-dialog {
        width: 80;
        max-width: 90%;
        height: auto;
        max-height: 85%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #backend-detail-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    #backend-detail-meta {
        margin-bottom: 1;
    }
    #backend-detail-health {
        margin-bottom: 1;
    }
    #backend-detail-conditions {
        height: auto;
        max-height: 14;
        margin-bottom: 1;
    }
    #backend-detail-actions {
        height: 3;
        align: right middle;
    }
    #backend-detail-actions Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("r", "restart", "Restart"),
    ]

    def __init__(self, backend: Dict[str, Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._backend = backend

    def compose(self) -> ComposeResult:
        b = self._backend
        phase = b.get("phase", "pending")
        icon, color = _PHASE_STYLE.get(phase, ("?", "dim"))
        name = b.get("name", "unknown")

        with Vertical(id="backend-detail-dialog"):
            yield Label(
                f"[b]{name}[/b]  [{color}]{icon} {phase.title()}[/{color}]",
                id="backend-detail-title",
            )

            # Metadata
            transport = b.get("type", "unknown")
            transport_colors = {
                "stdio": "cyan",
                "sse": "yellow",
                "streamable-http": "green",
                "streamable_http": "green",
            }
            tc = transport_colors.get(transport, "white")
            meta_lines = [
                f"Transport: [{tc}]{transport}[/{tc}]",
                f"Group: {b.get('group', '—')}",
                f"State: {b.get('state', '—')}",
            ]
            connected_at = b.get("connected_at")
            if connected_at:
                meta_lines.append(f"Connected at: {connected_at}")
            error = b.get("error")
            if error:
                meta_lines.append(f"[red]Error: {error}[/red]")

            # Capabilities summary
            caps = b.get("capabilities", {})
            if caps:
                tools_count = len(caps.get("tools", []))
                resources_count = len(caps.get("resources", []))
                prompts_count = len(caps.get("prompts", []))
                meta_lines.append(
                    f"Capabilities: {tools_count} tools, "
                    f"{resources_count} resources, {prompts_count} prompts"
                )

            # Labels
            labels = b.get("labels", {})
            if labels:
                lbl_parts = [f"{k}={v}" for k, v in labels.items()]
                meta_lines.append(f"Labels: {', '.join(lbl_parts)}")

            yield Static("\n".join(meta_lines), id="backend-detail-meta")

            # Health
            health = b.get("health", {})
            if health:
                h_status = health.get("status", "unknown")
                latency = health.get("latency_ms")
                last_check = health.get("last_check", "—")
                h_color = (
                    "green"
                    if h_status == "healthy"
                    else "red"
                    if h_status == "unhealthy"
                    else "yellow"
                )
                h_lines = [
                    f"[b]Health:[/b] [{h_color}]{h_status}[/{h_color}]",
                    f"Latency: {f'{latency:.0f}ms' if latency else '—'}",
                    f"Last check: {last_check}",
                ]
                yield Static("\n".join(h_lines), id="backend-detail-health")

            # Conditions log
            conditions = b.get("conditions", [])
            if conditions:
                yield Label("[b]Conditions[/b]")
                with VerticalScroll():
                    yield DataTable(id="backend-detail-conditions")

            # Action buttons
            with Horizontal(id="backend-detail-actions"):
                yield Button("Restart", variant="warning", id="btn-backend-restart")
                yield Button("Disconnect", variant="error", id="btn-backend-disconnect")
                yield Button("Close", variant="default", id="btn-backend-close")

    def on_mount(self) -> None:
        """Populate the conditions table."""
        conditions = self._backend.get("conditions", [])
        if not conditions:
            return
        try:
            table = self.query_one("#backend-detail-conditions", DataTable)
            table.add_columns("Time", "Type", "Status", "Message")
            table.cursor_type = "row"
            for c in conditions:
                ts = str(c.get("timestamp", ""))
                if "T" in ts:
                    ts = ts.split("T")[1][:8]  # HH:MM:SS
                ctype = c.get("type", "")
                cstatus = c.get("status", "")
                msg = c.get("message", "")
                if len(msg) > 60:
                    msg = msg[:57] + "…"
                table.add_row(ts, ctype, cstatus, msg)
        except NoMatches:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-backend-restart":
            self.action_restart()
        elif event.button.id == "btn-backend-disconnect":
            self.dismiss("disconnect")
        elif event.button.id == "btn-backend-close":
            self.action_cancel()

    def action_restart(self) -> None:
        """Dismiss with "restart" to signal the caller."""
        self.dismiss("restart")

    def action_cancel(self) -> None:
        self.dismiss(None)
