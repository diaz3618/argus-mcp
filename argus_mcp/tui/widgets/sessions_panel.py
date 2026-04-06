"""Session management widget.

Displays active MCP sessions, per-client tool counts, TTL countdown,
and provides kill/refresh actions.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Label, Static

from argus_mcp.tui._error_utils import safe_query

logger = logging.getLogger(__name__)


class SessionsPanel(Widget):
    """Active sessions panel for the dashboard."""

    DEFAULT_CSS = """
    SessionsPanel {
        height: auto;
        max-height: 16;
        border: round $accent;
        padding: 0 1;
    }
    #sessions-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 0;
    }
    #sessions-summary {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    #sessions-table {
        height: auto;
        max-height: 10;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Sessions[/b]", id="sessions-title")
            yield Static("Active: 0    Expired (1h): 0    TTL: —", id="sessions-summary")
            yield DataTable(id="sessions-table")

    def on_mount(self) -> None:
        if table := safe_query(self, "#sessions-table", DataTable):
            table.add_columns("Session ID", "User", "Tools", "Created", "TTL")
            table.cursor_type = "row"
            table.zebra_stripes = True

    def update_sessions(self, sessions: List[Dict[str, Any]], ttl_default: str = "30m") -> None:
        """Refresh the sessions table from session data."""
        table = safe_query(self, "#sessions-table", DataTable)
        if table is None:
            return
        table.clear()

        active = 0
        expired = 0

        for s in sessions:
            sid = s.get("session_id", "?")
            # Truncate session ID for display
            if len(sid) > 16:
                sid = sid[:16] + "…"
            user = s.get("user", "—")
            tools = s.get("tool_count", s.get("tools", "—"))
            created = s.get("created_at", s.get("created", ""))
            if isinstance(created, str) and "T" in created:
                created = created.split("T")[1][:8]
            ttl = s.get("ttl_remaining", "—")
            is_active = s.get("active", True)

            if is_active:
                active += 1
                if isinstance(ttl, (int, float)) and ttl < 120:
                    ttl_display = f"[yellow]{ttl:.0f}s ⚠[/yellow]"
                else:
                    ttl_display = str(ttl)
            else:
                expired += 1
                ttl_display = "[dim]expired[/dim]"

            table.add_row(sid, user, str(tools), str(created), ttl_display)

        summary = f"Active: {active}    Expired (1h): {expired}    TTL: {ttl_default}"
        if w := safe_query(self, "#sessions-summary", Static):
            w.update(summary)


class SessionDetailModal(ModalScreen[Optional[str]]):
    """Modal showing session detail with routing table."""

    DEFAULT_CSS = """
    SessionDetailModal {
        align: center middle;
    }
    #session-detail-dialog {
        width: 72;
        max-height: 30;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #sdm-header {
        text-style: bold;
        text-align: center;
        margin-bottom: 1;
    }
    #sdm-info {
        margin-bottom: 1;
    }
    #sdm-routing-table {
        height: auto;
        max-height: 10;
    }
    #sdm-stats {
        margin-top: 1;
        color: $text-muted;
    }
    #sdm-actions {
        height: 3;
        align: center middle;
        margin-top: 1;
    }
    #sdm-actions Button {
        margin: 0 1;
    }
    """

    BINDINGS = [("escape", "close", "Close")]

    def __init__(self, session: Dict[str, Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._session = session

    def compose(self) -> ComposeResult:
        s = self._session
        sid = s.get("session_id", "?")
        user = s.get("user", "—")
        created = s.get("created_at", "—")
        ttl = s.get("ttl_remaining", "—")

        with Vertical(id="session-detail-dialog"):
            yield Label(f"[b]Session — {sid}[/b]", id="sdm-header")
            yield Static(
                f"  User: {user}    Created: {created}    TTL: {ttl}",
                id="sdm-info",
            )

            yield Label("[b]Routing Table[/b]")
            yield DataTable(id="sdm-routing-table")

            calls = s.get("call_count", 0)
            errors = s.get("error_count", 0)
            avg_lat = s.get("avg_latency_ms", 0)
            yield Static(
                f"  Calls: {calls}  │  Errors: {errors}  │  Avg latency: {avg_lat:.0f}ms",
                id="sdm-stats",
            )

            with Horizontal(id="sdm-actions"):
                yield Button("Kill Session", variant="error", id="btn-session-kill")
                yield Button("Refresh TTL", variant="primary", id="btn-session-refresh")
                yield Button("Close", variant="default", id="btn-session-close")

    def on_mount(self) -> None:
        if table := safe_query(self, "#sdm-routing-table", DataTable):
            table.add_columns("Tool", "→ Backend", "Affinity")
            table.cursor_type = "row"
            table.zebra_stripes = True

            routes = self._session.get("routing_table", self._session.get("routes", []))
            for r in routes:
                tool = r.get("tool", "?")
                backend = r.get("backend", "?")
                affinity = r.get("affinity", "sticky")
                table.add_row(tool, backend, affinity)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-session-kill":
            self.dismiss("kill")
        elif event.button.id == "btn-session-refresh":
            self.dismiss("refresh")
        elif event.button.id == "btn-session-close":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
