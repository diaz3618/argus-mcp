"""Registry browser widget — server catalog with search and details.

Displays a ``DataTable`` of servers from the registry with
a search input and server detail panel.
"""

from __future__ import annotations

import logging
from typing import List

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import DataTable, Input, Label, Static

from argus_mcp._error_utils import safe_query
from argus_mcp.registry.models import ServerEntry

logger = logging.getLogger(__name__)


class ServerSelected(Message):
    """Posted when a server row is highlighted in the browser table."""

    def __init__(self, entry: ServerEntry) -> None:
        super().__init__()
        self.entry = entry


class InstallRequested(Message):
    """Posted when the user requests to install a server."""

    def __init__(self, entry: ServerEntry) -> None:
        super().__init__()
        self.entry = entry


class RegistryBrowserWidget(Widget):
    """Interactive registry browser with search bar and results table.

    Attributes
    ----------
    entries : list[ServerEntry]
        All entries currently loaded from the registry.
    filtered : list[ServerEntry]
        Subset matching the current search query.
    """

    DEFAULT_CSS = """
    RegistryBrowserWidget {
        height: 1fr;
        layout: vertical;
    }
    RegistryBrowserWidget #registry-search-bar {
        height: 3;
        padding: 0 1;
    }
    RegistryBrowserWidget #registry-search {
        width: 1fr;
    }
    RegistryBrowserWidget #registry-table {
        height: 1fr;
    }
    RegistryBrowserWidget #registry-status {
        height: 1;
        dock: bottom;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }
    """

    entries: reactive[List[ServerEntry]] = reactive(list, always_update=True)
    search_query: reactive[str] = reactive("")

    def compose(self) -> ComposeResult:
        with Horizontal(id="registry-search-bar"):
            yield Label("Search: ", id="registry-search-label")
            yield Input(
                placeholder="Filter servers by name or description…",
                id="registry-search",
            )
        yield DataTable(id="registry-table")
        yield Static("Ready", id="registry-status")

    def on_mount(self) -> None:
        table = self.query_one("#registry-table", DataTable)
        table.cursor_type = "row"
        table.add_columns("Name", "Transport", "Tools", "Version", "Description")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "registry-search":
            self.search_query = event.value

    def watch_search_query(self, value: str) -> None:
        self._refresh_table()

    def watch_entries(self, value: List[ServerEntry]) -> None:
        self._refresh_table()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        filtered = self._filtered_entries()
        if event.cursor_row < len(filtered):
            self.post_message(ServerSelected(filtered[event.cursor_row]))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Pressing Enter on a row triggers install request."""
        filtered = self._filtered_entries()
        if event.cursor_row < len(filtered):
            self.post_message(InstallRequested(filtered[event.cursor_row]))

    def set_status(self, text: str) -> None:
        """Update the status bar text."""
        if w := safe_query(self, "#registry-status", Static):
            w.update(text)

    def _filtered_entries(self) -> List[ServerEntry]:
        q = self.search_query.lower().strip()
        if not q:
            return list(self.entries)
        return [e for e in self.entries if q in e.name.lower() or q in e.description.lower()]

    def _refresh_table(self) -> None:
        table = safe_query(self, "#registry-table", DataTable)
        if table is None:
            return
        table.clear()
        for entry in self._filtered_entries():
            table.add_row(
                entry.name,
                entry.transport,
                str(len(entry.tools)),
                entry.version or "—",
                (
                    (entry.description[:60] + "…")
                    if len(entry.description) > 60
                    else entry.description
                ),
            )
        self.set_status(f"{len(self._filtered_entries())} servers shown")
