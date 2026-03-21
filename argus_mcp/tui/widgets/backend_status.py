"""Backend connection status widget."""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import DataTable, Static

from argus_mcp._error_utils import safe_query

logger = logging.getLogger(__name__)

_PHASE_STYLE: Dict[str, tuple] = {
    "pending": ("◌", "dim"),
    "initializing": ("⟳", "yellow"),
    "ready": ("●", "green"),
    "degraded": ("◑", "dark_orange"),
    "failed": ("✕", "red"),
    "shutting_down": ("◑", "cyan"),
}

# Transport type → display badge
_TRANSPORT_BADGE: Dict[str, str] = {
    "stdio": "[cyan]stdio[/cyan]",
    "sse": "[yellow]SSE[/yellow]",
    "streamable-http": "[green]StreamableHTTP[/green]",
    "streamable_http": "[green]StreamableHTTP[/green]",
}

_PHASE_SUMMARY: Dict[str, str] = {
    "ready": "●",
    "degraded": "◑",
    "failed": "✕",
    "pending": "◌",
    "initializing": "⟳",
    "shutting_down": "◑",
}


class BackendStatusWidget(Widget):
    """Compact panel showing per-backend lifecycle phases.

    Fires :class:`BackendSelected` when a row is highlighted/selected
    so the app can open a detail modal.
    """

    class BackendSelected(Message):
        """Fired when the user selects a backend row."""

        def __init__(self, backend: Dict[str, Any]) -> None:
            super().__init__()
            self.backend = backend

    connected: reactive[int] = reactive(0)
    total: reactive[int] = reactive(0)
    backend_details: reactive[list] = reactive(list, always_update=True)

    def compose(self) -> ComposeResult:
        yield Static("Backend Services", id="backend-title")
        yield DataTable(id="backend-table")
        yield Static("", id="backend-detail")

    def on_mount(self) -> None:
        """Set up the backends DataTable columns."""
        if table := safe_query(self, "#backend-table", DataTable):
            table.add_columns("", "Name", "Transport", "Phase", "Latency")
            table.cursor_type = "row"
            table.zebra_stripes = True
        self._refresh_display()

    def update_from_backends(self, backends: List[Dict[str, Any]]) -> None:
        """Populate widget from management API backend list."""
        self.backend_details = backends
        self.total = len(backends)
        self.connected = sum(1 for b in backends if b.get("phase") in ("ready", "degraded"))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Emit BackendSelected when user presses Enter on a row."""
        if event.row_key and event.row_key.value:
            name = str(event.row_key.value)
            backend = next(
                (b for b in self.backend_details if b.get("name") == name),
                None,
            )
            if backend:
                self.post_message(self.BackendSelected(backend))

    def _populate_backend_table(self, details: List[Dict[str, Any]], table: DataTable) -> None:
        """Fill the backend table with rows from *details*."""
        table.clear()
        for b in details:
            phase = b.get("phase", "pending")
            icon, color = _PHASE_STYLE.get(phase, ("?", "dim"))
            name = b.get("name", "?")
            transport = b.get("type", "?")
            transport_plain = {
                "stdio": "stdio",
                "sse": "SSE",
                "streamable-http": "StreamableHTTP",
                "streamable_http": "StreamableHTTP",
            }.get(transport, transport)
            latency = b.get("last_latency_ms")
            if latency is None:
                health = b.get("health", {})
                latency = health.get("latency_ms") if isinstance(health, dict) else None
            lat_str = f"{latency:.0f}ms" if latency else "—"
            table.add_row(
                f"[{color}]{icon}[/{color}]",
                name,
                transport_plain,
                phase.title(),
                lat_str,
                key=name,
            )

    @staticmethod
    def _build_phase_summary(details: List[Dict[str, Any]]) -> str:
        """Return a Rich-formatted phase summary string."""
        counts: Dict[str, int] = {}
        for b in details:
            p = b.get("phase", "pending")
            counts[p] = counts.get(p, 0) + 1
        parts: list[str] = []
        for phase_key in ("ready", "degraded", "failed", "pending", "initializing"):
            cnt = counts.get(phase_key, 0)
            if cnt > 0:
                icon_char = _PHASE_SUMMARY.get(phase_key, "?")
                _, color = _PHASE_STYLE.get(phase_key, ("?", "dim"))
                parts.append(f"[{color}]{icon_char} {phase_key.title()}={cnt}[/{color}]")
        return "  ".join(parts)

    def _compute_connection_detail(self) -> tuple[str, str]:
        """Return ``(detail_text, color)`` describing connection status."""
        if self.total == 0:
            return "No backends configured", "dim"
        if self.connected == self.total:
            return f"All {self.total} connected", "green"
        if self.connected == 0:
            return f"0 / {self.total} connected", "red"
        return f"{self.connected} / {self.total} connected", "yellow"

    def _refresh_display(self) -> None:
        table = safe_query(self, "#backend-table", DataTable)
        if table is None:
            return
        details = self.backend_details

        if details:
            self._populate_backend_table(details, table)
            summary = self._build_phase_summary(details)
        else:
            bar_parts: list[str] = []
            for i in range(self.total):
                if i < self.connected:
                    bar_parts.append("[green]●[/green]")
                else:
                    bar_parts.append("[red]○[/red]")
            summary = " ".join(bar_parts) if bar_parts else "—"

        detail, color = self._compute_connection_detail()

        if details:
            detail_text = f"[{color}]{detail}[/{color}]  │  {summary}"
        else:
            detail_text = f"[{color}]{detail}[/{color}]"
        if w := safe_query(self, "#backend-detail", Static):
            w.update(detail_text)

    def watch_connected(self) -> None:
        self._refresh_display()

    def watch_total(self) -> None:
        self._refresh_display()

    def watch_backend_details(self) -> None:
        self._refresh_display()
