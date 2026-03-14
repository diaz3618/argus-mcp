"""Audit log viewer screen — structured event log with filters and export.

Shows real-time scrolling audit events with filtering by user, server,
method, and time range. Supports export to JSON.
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


class AuditLogScreen(ArgusScreen):
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
        self._events: List[Dict[str, Any]] = []
        self._paused: bool = False
        self._filter_user: str = ""
        self._filter_server: str = ""

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
        """Set up audit table columns."""
        try:
            table = self.query_one("#audit-table", DataTable)
            table.add_columns("Time", "User", "Method", "Tool", "Server", "ms", "Status")
            table.cursor_type = "row"
            table.zebra_stripes = True
        except NoMatches:
            pass

    def on_show(self) -> None:
        """Load events from app-level cached data."""
        app = self.app
        # Try to get events from the last poll
        events = getattr(app, "_last_events", None)
        if events is not None:
            event_list = getattr(events, "events", [])
            self._events = [e.model_dump() if hasattr(e, "model_dump") else e for e in event_list]
        self._refresh_table()

    def _refresh_table(self) -> None:
        """Rebuild the table with current filters applied."""
        try:
            table = self.query_one("#audit-table", DataTable)
            table.clear()

            filtered = self._apply_filters(self._events)
            errors = 0
            denied = 0

            for evt in filtered:
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

                if status in ("error", "failed"):
                    errors += 1
                    status_display = f"[red]✕ {status}[/red]"
                elif status == "denied":
                    denied += 1
                    status_display = "[yellow]⚠ denied[/yellow]"
                else:
                    status_display = "[green]✓[/green]"

                table.add_row(ts, user, method, tool, server, lat_str, status_display)

            stats = f"Events: {len(filtered)}  │  Errors: {errors}  │  Denied: {denied}"
            self.query_one("#audit-stats", Static).update(stats)
        except NoMatches:
            logger.debug("Cannot refresh audit table", exc_info=True)

    def _apply_filters(self, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Apply user/server/method filters."""
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

    def on_input_changed(self, event: Input.Changed) -> None:
        """Update filter when user/server inputs change."""
        if event.input.id == "audit-user-filter":
            self._filter_user = event.value.strip()
            self._refresh_table()
        elif event.input.id == "audit-server-filter":
            self._filter_server = event.value.strip()
            self._refresh_table()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Re-filter when method dropdown changes."""
        if event.select.id == "audit-method-filter":
            self._refresh_table()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-audit-pause":
            self.action_toggle_pause()
        elif event.button.id == "btn-audit-export":
            self.action_export_log()

    def add_event(self, event: Dict[str, Any]) -> None:
        """Append a new audit event (called from app polling)."""
        if self._paused:
            return
        self._events.append(event)
        self._refresh_table()

    def action_focus_search(self) -> None:
        try:
            self.query_one("#audit-user-filter", Input).focus()
        except NoMatches:
            pass

    def action_go_back(self) -> None:
        self.app.switch_mode("dashboard")

    def action_toggle_pause(self) -> None:
        self._paused = not self._paused
        try:
            btn = self.query_one("#btn-audit-pause", Button)
            btn.label = "▶ Resume" if self._paused else "⏸ Pause"
        except NoMatches:
            pass

    def action_toggle_filter(self) -> None:
        self.action_focus_search()

    def action_export_log(self) -> None:
        """Export visible events as JSON to a file."""
        filtered = self._apply_filters(self._events)
        try:
            path = "audit_export.json"
            with open(path, "w") as f:
                _json.dump(filtered, f, indent=2, default=str)
            self.notify(
                f"Exported {len(filtered)} events to {path}", title="Export", severity="information"
            )
        except OSError as exc:
            self.notify(f"Export failed: {exc}", title="Error", severity="error")
