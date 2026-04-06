"""Registry browser widget — server catalog with search, sort, filter and column controls.

Displays a ``DataTable`` of servers from the registry with a search input,
transport filter, sortable column headers, and column visibility toggles.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from textual.containers import Horizontal
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Checkbox, DataTable, Input, Label, Select, Static, Switch

from argus_cli.tui._error_utils import safe_query

if TYPE_CHECKING:
    from argus_mcp.registry.models import ServerEntry
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)

# Column configuration: (key, header_label, default_visible)
_COLUMNS = [
    ("name", "Name", True),
    ("transport", "Transport", True),
    ("tools", "Tools", True),
    ("version", "Version", True),
    ("categories", "Categories", False),
    ("description", "Description", True),
]

_ALL_TRANSPORTS = ""


class RegistryServerHighlighted(Message):
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
    """Interactive registry browser with search, sort, filter and column controls."""

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
    RegistryBrowserWidget #registry-transport-filter {
        width: 24;
    }
    RegistryBrowserWidget #registry-filter-switch {
        width: auto;
        margin-left: 1;
    }
    RegistryBrowserWidget #registry-column-bar {
        height: auto;
        max-height: 3;
        padding: 0 1;
    }
    RegistryBrowserWidget .col-toggle {
        width: auto;
        margin: 0 1 0 0;
        height: auto;
        padding: 0;
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

    entries: reactive[list[ServerEntry]] = reactive(list, always_update=True)
    search_query: reactive[str] = reactive("")

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._sort_column: str = ""
        self._sort_reverse: bool = False
        self._transport_filter: str = _ALL_TRANSPORTS
        self._visible_columns: set[str] = {k for k, _, vis in _COLUMNS if vis}
        self._filter_enabled: bool = True
        self._search_debounce: object | None = None

    def compose(self) -> ComposeResult:
        with Horizontal(id="registry-search-bar"):
            yield Label("Search: ", id="registry-search-label")
            yield Input(
                placeholder="Filter servers by name or description…",
                id="registry-search",
            )
            yield Select(
                [("All Transports", _ALL_TRANSPORTS)],
                value=_ALL_TRANSPORTS,
                allow_blank=False,
                id="registry-transport-filter",
            )
            yield Switch(value=True, id="registry-filter-switch")
        with Horizontal(id="registry-column-bar"):
            for key, label, default_vis in _COLUMNS:
                yield Checkbox(
                    label,
                    value=default_vis,
                    id=f"col-{key}",
                    classes="col-toggle",
                )
        yield DataTable(id="registry-table")
        yield Static("Ready", id="registry-status")

    def on_mount(self) -> None:
        self._rebuild_columns()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "registry-search":
            if self._search_debounce is not None:
                self._search_debounce.stop()  # type: ignore[union-attr]
            if not self._filter_enabled:
                self.search_query = ""
                return
            value = event.value
            self._search_debounce = self.set_timer(
                0.15, lambda: setattr(self, "search_query", value)
            )

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id == "registry-filter-switch":
            self._filter_enabled = event.value
            if event.value:
                inp = safe_query(self, "#registry-search", Input)
                self.search_query = inp.value if inp else ""
            else:
                self.search_query = ""

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "registry-transport-filter":
            val = event.value
            self._transport_filter = str(val) if val != Select.BLANK else _ALL_TRANSPORTS
            self._refresh_table()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        cid = event.checkbox.id or ""
        if cid.startswith("col-"):
            col_key = cid[4:]
            if event.value:
                self._visible_columns.add(col_key)
            else:
                self._visible_columns.discard(col_key)
            self._rebuild_columns()

    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        col_key = str(event.column_key)
        if self._sort_column == col_key:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = col_key
            self._sort_reverse = False
        self._rebuild_columns()

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        filtered = self._sorted_filtered()
        if event.cursor_row < len(filtered):
            self.post_message(RegistryServerHighlighted(filtered[event.cursor_row]))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Pressing Enter on a row triggers install request."""
        filtered = self._sorted_filtered()
        if event.cursor_row < len(filtered):
            self.post_message(InstallRequested(filtered[event.cursor_row]))

    def watch_search_query(self, _value: str) -> None:
        self._refresh_table()

    def watch_entries(self, _value: list[ServerEntry]) -> None:
        self._update_transport_options()
        self._refresh_table()

    def set_status(self, text: str) -> None:
        """Update the status bar text."""
        if w := safe_query(self, "#registry-status", Static):
            w.update(text)

    def _update_transport_options(self) -> None:
        """Rebuild the transport filter dropdown from current entries."""
        select = safe_query(self, "#registry-transport-filter", Select)
        if select is None:
            return
        transports = sorted({e.transport for e in self.entries if e.transport})
        options: list[tuple[str, str]] = [("All Transports", _ALL_TRANSPORTS)]
        for t in transports:
            options.append((t, t))
        saved = self._transport_filter
        select.set_options(options)
        if saved and saved in transports:
            select.value = saved
        else:
            self._transport_filter = _ALL_TRANSPORTS
            select.value = _ALL_TRANSPORTS

    def _rebuild_columns(self) -> None:
        """Rebuild table columns (needed when sort or visibility changes)."""
        table = safe_query(self, "#registry-table", DataTable)
        if table is None:
            return
        table.clear(columns=True)
        table.cursor_type = "row"
        for key, label, _ in _COLUMNS:
            if key in self._visible_columns:
                indicator = ""
                if self._sort_column == key:
                    indicator = " \u25b2" if not self._sort_reverse else " \u25bc"
                table.add_column(label + indicator, key=key)
        self._refresh_table()

    @staticmethod
    def _cell_value(entry: ServerEntry, key: str) -> str:
        if key == "name":
            return entry.name
        if key == "transport":
            return entry.transport
        if key == "tools":
            return str(len(entry.tools))
        if key == "version":
            return entry.version or "\u2014"
        if key == "categories":
            return ", ".join(entry.categories) or "\u2014"
        if key == "description":
            desc = entry.description
            return (desc[:60] + "\u2026") if len(desc) > 60 else desc
        return ""

    def _filtered_entries(self) -> list[ServerEntry]:
        q = self.search_query.lower().strip()
        result = list(self.entries)
        if q:
            result = [e for e in result if q in e.name.lower() or q in e.description.lower()]
        if self._transport_filter:
            result = [e for e in result if e.transport == self._transport_filter]
        return result

    def _sorted_filtered(self) -> list[ServerEntry]:
        entries = self._filtered_entries()
        if not self._sort_column:
            return entries
        key_map = {
            "name": lambda e: e.name.lower(),
            "transport": lambda e: e.transport.lower(),
            "tools": lambda e: len(e.tools),
            "version": lambda e: (e.version or "").lower(),
            "categories": lambda e: ", ".join(e.categories).lower(),
            "description": lambda e: e.description.lower(),
        }
        key_fn = key_map.get(self._sort_column)
        if key_fn:
            entries = sorted(entries, key=key_fn, reverse=self._sort_reverse)
        return entries

    def _refresh_table(self) -> None:
        table = safe_query(self, "#registry-table", DataTable)
        if table is None:
            return
        table.clear()
        visible_keys = [k for k, _, _ in _COLUMNS if k in self._visible_columns]
        sorted_entries = self._sorted_filtered()
        for entry in sorted_entries:
            row = tuple(self._cell_value(entry, k) for k in visible_keys)
            table.add_row(*row)
        count = len(sorted_entries)
        total = len(self.entries)
        if count == total:
            self.set_status(f"{count} servers")
        else:
            self.set_status(f"{count} / {total} servers shown")
