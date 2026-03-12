"""Per-server operational logs — structured event log with server filtering.

Shows real-time scrolling events filtered by backend/server with
correlation ID tracking, latency analysis, and method filtering.
"""

from __future__ import annotations

import json as _json
import logging
from typing import Any, Dict, List

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, DataTable, Input, Label, Select, Static

from argus_mcp.tui.screens.base import ArgusScreen

logger = logging.getLogger(__name__)


class ServerLogsScreen(ArgusScreen):
    """Per-server operational log viewer with filtering and correlation IDs."""

    BINDINGS = [
        ("slash", "focus_search", "Search"),
        ("escape", "go_back", "Back"),
        ("c", "toggle_correlation", "Correlation"),
        ("e", "export_log", "Export JSON"),
        ("p", "toggle_pause", "Pause/Resume"),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._events: List[Dict[str, Any]] = []
        self._paused: bool = False
        self._filter_server: str = ""
        self._filter_method: str = "all"
        self._filter_search: str = ""
        self._show_correlation: bool = True

    def compose_content(self) -> ComposeResult:
        with Vertical(id="srvlog-layout"):
            yield Static(
                "[b]Server Logs[/b]  •  Per-server operational events",
                id="srvlog-title",
            )

            with Horizontal(id="srvlog-filter-bar"):
                yield Label("Server:", classes="setting-label")
                yield Select(
                    [("All Servers", "all")],
                    value="all",
                    id="srvlog-server-filter",
                    allow_blank=False,
                )
                yield Label("Method:", classes="setting-label")
                yield Select(
                    [
                        ("All", "all"),
                        ("tools/call", "tools/call"),
                        ("tools/list", "tools/list"),
                        ("resources/read", "resources/read"),
                        ("prompts/get", "prompts/get"),
                        ("denied", "denied"),
                        ("error", "error"),
                    ],
                    value="all",
                    id="srvlog-method-filter",
                    allow_blank=False,
                )
                yield Input(placeholder="Search…", id="srvlog-search")
                yield Button(
                    "⏸ Pause" if not self._paused else "▶ Resume",
                    id="btn-srvlog-pause",
                    variant="default",
                )

            yield DataTable(id="srvlog-table")

            with Horizontal(id="srvlog-status-bar"):
                yield Static(
                    "Events: 0  │  Avg ms: —  │  Errors: 0",
                    id="srvlog-stats",
                )
                yield Button("Export JSON", id="btn-srvlog-export", variant="primary")

    def on_mount(self) -> None:
        """Set up columns and populate server dropdown."""
        try:
            table = self.query_one("#srvlog-table", DataTable)
            columns = ["Time", "Server", "Method", "Tool", "Corr-ID", "ms", "Status"]
            table.add_columns(*columns)
            table.cursor_type = "row"
            table.zebra_stripes = True
        except NoMatches:
            pass
        self._populate_server_dropdown()

    def on_show(self) -> None:
        """Load events from app-level cached data."""
        app = self.app
        events = getattr(app, "_last_events", None)
        if events is not None:
            event_list = getattr(events, "events", [])
            self._events = [e.model_dump() if hasattr(e, "model_dump") else e for e in event_list]
        self._populate_server_dropdown()
        self._refresh_table()

    def _populate_server_dropdown(self) -> None:
        """Fill the server dropdown from current events and server manager."""
        servers: set[str] = set()

        # Gather server names from events
        for evt in self._events:
            srv = evt.get("server") or evt.get("backend") or ""
            if srv:
                servers.add(srv)

        # Also pull from server manager if available
        mgr = getattr(self.app, "_server_manager", None)
        if mgr is not None:
            entries = getattr(mgr, "entries", {})
            for name in entries:
                servers.add(name)

        options: list[tuple[str, str]] = [("All Servers", "all")]
        for s in sorted(servers):
            options.append((s, s))

        try:
            sel = self.query_one("#srvlog-server-filter", Select)
            sel.set_options(options)
        except NoMatches:
            pass

    def _refresh_table(self) -> None:
        """Rebuild the table with current filters applied."""
        try:
            table = self.query_one("#srvlog-table", DataTable)
            table.clear()

            filtered = self._apply_filters(self._events)
            errors = 0
            total_latency = 0.0
            latency_count = 0

            for evt in filtered:
                ts = str(evt.get("timestamp", ""))
                if "T" in ts:
                    ts = ts.split("T")[1][:12]  # Include ms precision
                server = evt.get("server", evt.get("backend", "—"))
                method = evt.get("method", evt.get("type", "—"))
                tool = evt.get("tool", evt.get("name", "—"))
                corr_id = evt.get("correlation_id", evt.get("session_id", "—"))
                if corr_id and len(corr_id) > 8:
                    corr_id = corr_id[:8] + "…"
                latency = evt.get("latency_ms", evt.get("duration_ms"))
                if latency is not None:
                    lat_str = f"{latency:.0f}"
                    total_latency += float(latency)
                    latency_count += 1
                else:
                    lat_str = "—"
                status = evt.get("status", "ok")

                if status in ("error", "failed"):
                    errors += 1
                    status_display = f"[red]✕ {status}[/red]"
                elif status == "denied":
                    errors += 1
                    status_display = "[yellow]⚠ denied[/yellow]"
                else:
                    status_display = "[green]✓[/green]"

                table.add_row(ts, server, method, tool, corr_id, lat_str, status_display)

            avg_ms = f"{total_latency / latency_count:.1f}" if latency_count else "—"
            stats = f"Events: {len(filtered)}  │  Avg ms: {avg_ms}  │  Errors: {errors}"
            self.query_one("#srvlog-stats", Static).update(stats)
        except NoMatches:
            logger.debug("Cannot refresh server logs table", exc_info=True)

    def _apply_filters(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply server/method/search filters."""
        result = events

        # Server filter
        try:
            srv_sel = self.query_one("#srvlog-server-filter", Select)
            srv_val = srv_sel.value
            if srv_val and srv_val != "all":
                result = [
                    e for e in result if (e.get("server") or e.get("backend") or "") == srv_val
                ]
        except NoMatches:
            pass

        # Method filter
        try:
            method_sel = self.query_one("#srvlog-method-filter", Select)
            method_val = method_sel.value
            if method_val and method_val != "all":
                if method_val == "error":
                    result = [e for e in result if e.get("status") in ("error", "failed")]
                else:
                    result = [e for e in result if e.get("method", e.get("type")) == method_val]
        except NoMatches:
            pass

        # Text search
        if self._filter_search:
            q = self._filter_search.lower()
            result = [e for e in result if q in _json.dumps(e, default=str).lower()]

        return result

    def on_input_changed(self, event: Input.Changed) -> None:
        """Update search filter on input change."""
        if event.input.id == "srvlog-search":
            self._filter_search = event.value.strip()
            self._refresh_table()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Re-filter when server or method dropdown changes."""
        if event.select.id in ("srvlog-server-filter", "srvlog-method-filter"):
            self._refresh_table()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-srvlog-pause":
            self.action_toggle_pause()
        elif event.button.id == "btn-srvlog-export":
            self.action_export_log()

    def add_event(self, event: Dict[str, Any]) -> None:
        """Append a new event (called from app polling)."""
        if self._paused:
            return
        self._events.append(event)
        self._refresh_table()

    def action_focus_search(self) -> None:
        try:
            self.query_one("#srvlog-search", Input).focus()
        except NoMatches:
            pass

    def action_go_back(self) -> None:
        self.app.switch_mode("dashboard")

    def action_toggle_pause(self) -> None:
        self._paused = not self._paused
        try:
            btn = self.query_one("#btn-srvlog-pause", Button)
            btn.label = "▶ Resume" if self._paused else "⏸ Pause"
        except NoMatches:
            pass

    def action_toggle_correlation(self) -> None:
        """Toggle correlation ID column visibility."""
        self._show_correlation = not self._show_correlation
        self.notify(
            f"Correlation IDs: {'shown' if self._show_correlation else 'hidden'}",
            timeout=2,
        )
        self._refresh_table()

    def action_export_log(self) -> None:
        """Export filtered events to JSON."""
        filtered = self._apply_filters(self._events)
        if not filtered:
            self.notify("No events to export", severity="warning", timeout=3)
            return
        try:
            from pathlib import Path

            out = Path.home() / ".config" / "argus-mcp" / "server-logs-export.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(_json.dumps(filtered, indent=2, default=str))
            self.notify(f"Exported {len(filtered)} events → {out}", timeout=4)
        except OSError as exc:
            self.notify(f"Export failed: {exc}", severity="error", timeout=5)
