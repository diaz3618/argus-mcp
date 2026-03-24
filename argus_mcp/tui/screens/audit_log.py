"""Audit log viewer screen — structured event log with filters and export.

Shows real-time scrolling audit events with filtering by user, server,
method, and time range. Supports export to JSON.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, DataTable, Input, Label, Select, Static

from argus_mcp.tui.screens._base_log import BaseLogScreen

logger = logging.getLogger(__name__)


class AuditLogScreen(BaseLogScreen):
    """Dedicated audit log viewer with filtering and export."""

    INITIAL_FOCUS = "#audit-table"

    BINDINGS = [
        ("slash", "focus_search", "Search"),
        ("escape", "go_back", "Back"),
        ("f", "toggle_filter", "Filter"),
        ("e", "export_log", "Export JSON"),
        ("p", "toggle_pause", "Pause/Resume"),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._filter_user: str = ""
        self._filter_server: str = ""

    def _table_id(self) -> str:
        return "audit-table"

    def _pause_button_id(self) -> str:
        return "btn-audit-pause"

    def _export_button_id(self) -> str:
        return "btn-audit-export"

    def _stats_id(self) -> str:
        return "audit-stats"

    def _columns(self) -> List[str]:
        return ["Time", "User", "Method", "Tool", "Server", "ms", "Status"]

    def _event_to_row(self, evt: Dict[str, Any]) -> tuple:
        ts = str(evt.get("timestamp", ""))
        if "T" in ts:
            ts = ts.split("T")[1][:8]
        user = evt.get("user", "—")
        method = evt.get("method", evt.get("type", "—"))
        tool = evt.get("tool", evt.get("name", "—"))
        server = evt.get("server", evt.get("backend", "—"))
        latency = evt.get("latency_ms", evt.get("duration_ms"))
        lat_str = f"{latency:.0f}" if latency else "—"
        status = evt.get("status", "ok")
        return (ts, user, method, tool, server, lat_str, self._format_status(status))

    def _apply_filters(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        result = events

        # Method filter
        try:
            method_sel = self.query_one("#audit-method-filter", Select)
            method_val = method_sel.value
            if method_val and method_val != "all":
                result = [e for e in result if e.get("method", e.get("type")) == method_val]
        except NoMatches:
            pass

        # User filter
        if self._filter_user:
            q = self._filter_user.lower()
            result = [e for e in result if q in (e.get("user", "") or "").lower()]

        # Server filter
        if self._filter_server:
            q = self._filter_server.lower()
            result = [
                e
                for e in result
                if q in (e.get("server", "") or e.get("backend", "") or "").lower()
            ]

        return result

    def _compute_stats(self, filtered: List[Dict[str, Any]]) -> str:
        errors = sum(1 for e in filtered if e.get("status") in ("error", "failed"))
        denied = sum(1 for e in filtered if e.get("status") == "denied")
        return f"Events: {len(filtered)}  │  Errors: {errors}  │  Denied: {denied}"

    def _export_filename(self) -> str:
        return "audit-export.json"

    def compose_content(self) -> ComposeResult:
        with Vertical(id="audit-layout"):
            yield Static("[b]Audit Log[/b]  •  Structured event history", id="audit-title")

            with Horizontal(id="audit-filter-bar"):
                yield Label("Filter:", classes="setting-label")
                yield Select(
                    [
                        ("All", "all"),
                        ("tools/call", "tools/call"),
                        ("tools/list", "tools/list"),
                        ("resources/read", "resources/read"),
                        ("prompts/get", "prompts/get"),
                        ("denied", "denied"),
                    ],
                    value="all",
                    id="audit-method-filter",
                    allow_blank=False,
                )
                yield Input(placeholder="User…", id="audit-user-filter")
                yield Input(placeholder="Server…", id="audit-server-filter")
                yield Button(
                    "⏸ Pause" if not self._paused else "▶ Resume",
                    id="btn-audit-pause",
                    variant="default",
                )

            yield DataTable(id="audit-table")

            with Horizontal(id="audit-status-bar"):
                yield Static("Events: 0  │  Errors: 0  │  Denied: 0", id="audit-stats")
                yield Button("Export JSON", id="btn-audit-export", variant="primary")

    def on_mount(self) -> None:
        self._setup_table()

    def on_show(self) -> None:
        self._load_events_from_app()
        self._refresh_table()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "audit-user-filter":
            self._filter_user = event.value.strip()
            self._refresh_table()
        elif event.input.id == "audit-server-filter":
            self._filter_server = event.value.strip()
            self._refresh_table()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "audit-method-filter":
            self._refresh_table()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-audit-pause":
            self.action_toggle_pause()
        elif event.button.id == "btn-audit-export":
            self.action_export_log()

    def action_focus_search(self) -> None:
        try:
            self.query_one("#audit-user-filter", Input).focus()
        except NoMatches:
            pass

    def action_toggle_filter(self) -> None:
        self.action_focus_search()
