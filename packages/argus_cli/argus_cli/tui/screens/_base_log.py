"""Base log viewer — shared structure for audit & server log screens.

Provides :class:`BaseLogScreen` with common DataTable setup, pause/resume,
event caching, export to JSON, and a template-method interface so
subclasses supply only the parts that differ.
"""

from __future__ import annotations

import json as _json
import logging
from pathlib import Path
from typing import Any

from textual.css.query import NoMatches
from textual.widgets import Button, DataTable

from argus_cli.tui.screens.base import ArgusScreen

logger = logging.getLogger(__name__)


class BaseLogScreen(ArgusScreen):
    """Abstract base for tabular log viewers with filtering.

    Subclasses must override:

    * :meth:`_table_id` — CSS id of the ``DataTable``
    * :meth:`_pause_button_id`
    * :meth:`_export_button_id`
    * :meth:`_stats_id`
    * :meth:`_columns` — list of column header strings
    * :meth:`_event_to_row` — convert one event dict → tuple of cell strings
    * :meth:`_apply_filters` — return filtered subset of events
    * :meth:`_compute_stats` — return a status-bar string for filtered events
    * :meth:`_export_filename` — file name for JSON export
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._events: list[dict[str, Any]] = []
        self._paused: bool = False

    def _table_id(self) -> str:
        raise NotImplementedError

    def _pause_button_id(self) -> str:
        raise NotImplementedError

    def _export_button_id(self) -> str:
        raise NotImplementedError

    def _stats_id(self) -> str:
        raise NotImplementedError

    def _columns(self) -> list[str]:
        raise NotImplementedError

    def _event_to_row(self, evt: dict[str, Any]) -> tuple:
        raise NotImplementedError

    def _apply_filters(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        raise NotImplementedError

    def _compute_stats(self, filtered: list[dict[str, Any]]) -> str:
        raise NotImplementedError

    def _export_filename(self) -> str:
        raise NotImplementedError

    def _setup_table(self) -> None:
        """Add columns and configure the DataTable."""
        try:
            table = self.query_one(f"#{self._table_id()}", DataTable)
            table.add_columns(*self._columns())
            table.cursor_type = "row"
            table.zebra_stripes = True
        except NoMatches:
            pass

    def _load_events_from_app(self) -> None:
        """Pull cached events from the app."""
        events = self.app.last_events
        if events is not None:
            event_list = getattr(events, "events", [])
            self._events = [e.model_dump() if hasattr(e, "model_dump") else e for e in event_list]

    def _refresh_table(self) -> None:
        """Rebuild the table applying current filters."""
        try:
            table = self.query_one(f"#{self._table_id()}", DataTable)
            table.clear()

            filtered = self._apply_filters(self._events)
            for evt in filtered:
                table.add_row(*self._event_to_row(evt))

            from textual.widgets import Static

            self.query_one(f"#{self._stats_id()}", Static).update(self._compute_stats(filtered))
        except NoMatches:
            logger.debug("Cannot refresh log table", exc_info=True)

    def add_event(self, event: dict[str, Any]) -> None:
        """Append a new event (called from app polling)."""
        if self._paused:
            return
        self._events.append(event)
        self._refresh_table()

    def action_go_back(self) -> None:
        self.app.switch_mode("dashboard")

    def action_toggle_pause(self) -> None:
        self._paused = not self._paused
        try:
            btn = self.query_one(f"#{self._pause_button_id()}", Button)
            btn.label = "▶ Resume" if self._paused else "⏸ Pause"
        except NoMatches:
            pass

    def action_export_log(self) -> None:
        """Export filtered events to JSON."""
        filtered = self._apply_filters(self._events)
        if not filtered:
            self.notify("No events to export", severity="warning", timeout=3)
            return
        try:
            out = Path.home() / ".config" / "argus-mcp" / self._export_filename()
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(_json.dumps(filtered, indent=2, default=str))
            self.notify(f"Exported {len(filtered)} events → {out}", timeout=4)
        except OSError as exc:
            self.notify(f"Export failed: {exc}", severity="error", timeout=5)

    @staticmethod
    def _format_status(status: str) -> str:
        """Return Rich-markup for a status value."""
        if status in ("error", "failed"):
            return f"[red]✕ {status}[/red]"
        if status == "denied":
            return "[yellow]⚠ denied[/yellow]"
        return "[green]✓[/green]"
