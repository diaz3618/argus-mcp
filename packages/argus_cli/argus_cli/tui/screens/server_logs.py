"""Per-server operational logs — structured event log with server filtering.

Shows real-time scrolling events filtered by backend/server with
correlation ID tracking, latency analysis, and method filtering.
"""

from __future__ import annotations

import contextlib
import json as _json
import logging
from typing import TYPE_CHECKING, Any

from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, DataTable, Input, Label, Select, Static

from argus_cli.tui.screens._base_log import BaseLogScreen

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class ServerLogsScreen(BaseLogScreen):
    """Per-server operational log viewer with filtering and correlation IDs."""

    INITIAL_FOCUS = "#srvlog-table"

    BINDINGS = [
        ("slash", "focus_search", "Search"),
        ("escape", "go_back", "Back"),
        ("c", "toggle_correlation", "Correlation"),
        ("e", "export_log", "Export JSON"),
        ("p", "toggle_pause", "Pause/Resume"),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._filter_search: str = ""
        self._show_correlation: bool = True

    def _table_id(self) -> str:
        return "srvlog-table"

    def _pause_button_id(self) -> str:
        return "btn-srvlog-pause"

    def _export_button_id(self) -> str:
        return "btn-srvlog-export"

    def _stats_id(self) -> str:
        return "srvlog-stats"

    def _columns(self) -> list[str]:
        return ["Time", "Server", "Method", "Tool", "Corr-ID", "ms", "Status"]

    def _event_to_row(self, evt: dict[str, Any]) -> tuple:
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
        lat_str = f"{latency:.0f}" if latency is not None else "—"
        status = evt.get("status", "ok")
        return (ts, server, method, tool, corr_id, lat_str, self._format_status(status))

    def _apply_filters(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        result = events
        result = self._filter_by_server(result)
        result = self._filter_by_method(result)
        result = self._filter_by_text(result)
        return result

    def _compute_stats(self, filtered: list[dict[str, Any]]) -> str:
        errors = 0
        total_latency = 0.0
        latency_count = 0
        for e in filtered:
            if e.get("status") in ("error", "failed", "denied"):
                errors += 1
            lat = e.get("latency_ms", e.get("duration_ms"))
            if lat is not None:
                total_latency += float(lat)
                latency_count += 1
        avg_ms = f"{total_latency / latency_count:.1f}" if latency_count else "—"
        return f"Events: {len(filtered)}  │  Avg ms: {avg_ms}  │  Errors: {errors}"

    def _export_filename(self) -> str:
        return "server-logs-export.json"

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
        self._setup_table()
        self._populate_server_dropdown()

    def on_show(self) -> None:
        self._load_events_from_app()
        self._populate_server_dropdown()
        self._refresh_table()

    def _populate_server_dropdown(self) -> None:
        """Fill the server dropdown from current events and server manager."""
        servers: set[str] = set()

        for evt in self._events:
            srv = evt.get("server") or evt.get("backend") or ""
            if srv:
                servers.add(srv)

        mgr = self.app.server_manager
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

    def _filter_by_server(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        try:
            srv_sel = self.query_one("#srvlog-server-filter", Select)
            srv_val = srv_sel.value
            if srv_val and srv_val != "all":
                return [e for e in events if (e.get("server") or e.get("backend") or "") == srv_val]
        except NoMatches:
            pass
        return events

    def _filter_by_method(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        try:
            method_sel = self.query_one("#srvlog-method-filter", Select)
            method_val = method_sel.value
            if method_val and method_val != "all":
                if method_val == "error":
                    return [e for e in events if e.get("status") in ("error", "failed")]
                return [e for e in events if e.get("method", e.get("type")) == method_val]
        except NoMatches:
            pass
        return events

    def _filter_by_text(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self._filter_search:
            return events
        q = self._filter_search.lower()
        return [e for e in events if q in _json.dumps(e, default=str).lower()]

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "srvlog-search":
            self._filter_search = event.value.strip()
            self._refresh_table()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id in ("srvlog-server-filter", "srvlog-method-filter"):
            self._refresh_table()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-srvlog-pause":
            self.action_toggle_pause()
        elif event.button.id == "btn-srvlog-export":
            self.action_export_log()

    def action_focus_search(self) -> None:
        with contextlib.suppress(NoMatches):
            self.query_one("#srvlog-search", Input).focus()

    def action_toggle_correlation(self) -> None:
        """Toggle correlation ID column visibility."""
        self._show_correlation = not self._show_correlation
        self.notify(
            f"Correlation IDs: {'shown' if self._show_correlation else 'hidden'}",
            timeout=2,
        )
        self._refresh_table()
