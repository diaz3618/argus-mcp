"""Tools mode — enhanced capability tables with filtering and search.

Provides a focused view of tools, resources, and prompts from all
connected backend servers.  Includes a search bar for live filtering
and a detail panel for inspecting individual tool schemas.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any

from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Input, Static, Switch

from argus_cli.tui.screens.base import ArgusScreen
from argus_cli.tui.widgets.capability_tables import CapabilitySection
from argus_cli.tui.widgets.module_container import ModuleContainer
from argus_cli.tui.widgets.tplot import FrequencyChart

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class ToolsScreen(ArgusScreen):
    """Tools mode — capability tables with search, filtering, and detail view."""

    JUMP_TARGETS = {
        "tools-search": "s",
        "dt-tools": "t",
        "tools-detail-panel": "d",
        "tools-freq-chart": "q",
    }

    INITIAL_FOCUS = "#dt-tools"

    BINDINGS = [
        ("slash", "focus_search", "Search"),
        ("escape", "clear_search", "Clear"),
        ("c", "toggle_conflicts", "Conflicts Only"),
        ("f", "toggle_filtered", "Show Filtered"),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._cached_tools: list[dict[str, Any]] = []
        self._cached_resources: list[dict[str, Any]] = []
        self._cached_prompts: list[dict[str, Any]] = []
        self._cached_route_map: dict | None = None
        self._conflicts_only: bool = False
        self._show_filtered: bool = False
        self._filter_enabled: bool = True

    def compose_content(self) -> ComposeResult:
        with Vertical(id="tools-layout"):
            with Horizontal(id="tools-header-bar"):
                yield Static(
                    "[b]Tools Explorer[/b]  •  Browse, search, and inspect capabilities",
                    id="tools-header",
                )
                yield Input(
                    placeholder="Search tools, resources, prompts… (press /)",
                    id="tools-search",
                )
                yield Switch(value=True, id="tools-filter-switch")
            yield Static("", id="tools-status-bar")
            with ModuleContainer(title="Capabilities", subtitle="[t]ools", id="tools-cap-section"):
                yield CapabilitySection(id="tools-cap-tables")
            with ModuleContainer(title="Detail", subtitle="[d]etail", id="tools-detail-panel"):
                yield Static("", id="tools-detail-text")
            with ModuleContainer(
                title="Invocation Frequency",
                subtitle="chart",
                id="tools-freq-section",
            ):
                yield FrequencyChart(id="tools-freq-chart")

    def on_show(self) -> None:
        """Re-populate capability tables from app-level cached data."""
        app = self.app
        caps = app.last_caps
        if caps is not None:
            tools = [t.model_dump() for t in caps.tools]
            resources = [r.model_dump() for r in caps.resources]
            prompts = [p.model_dump() for p in caps.prompts]
            route_map = caps.route_map
            self._cached_tools = tools
            self._cached_resources = resources
            self._cached_prompts = prompts
            self._cached_route_map = route_map
            self._populate_tables()

    def _populate_tables(self, filtered_tools: list[dict[str, Any]] | None = None) -> None:
        """Populate capability tables and update conflict status bar."""
        tools = filtered_tools if filtered_tools is not None else self._cached_tools
        try:
            cap = self.query_one("#tools-cap-tables", CapabilitySection)
            cap.populate(
                tools,
                self._cached_resources,
                self._cached_prompts,
                self._cached_route_map,
            )
        except NoMatches:
            logger.debug("Cannot populate tools cap section", exc_info=True)
        self._update_status_bar(tools)
        self._update_frequency_chart(tools)

    def _update_status_bar(self, tools: list[dict[str, Any]] | None = None) -> None:
        """Update the conflict/filter status bar."""
        all_tools = self._cached_tools
        displayed = tools or all_tools
        total = len(displayed)
        total_all = len(all_tools)
        conflicts = sum(1 for t in all_tools if t.get("renamed"))
        filtered_count = sum(1 for t in all_tools if t.get("filtered"))
        parts = [f"{total} tools"]
        if total != total_all:
            parts[0] += f" (of {total_all})"
        if conflicts:
            parts.append(f"[yellow]⚡ {conflicts} renamed[/yellow]")
        if filtered_count:
            if self._show_filtered:
                parts.append(f"[dim]{filtered_count} hidden shown[/dim]  [F] Hide")
            else:
                parts.append(f"[dim]{filtered_count} hidden[/dim]  [F] Show")
        if self._conflicts_only:
            parts.append("[bold yellow]conflicts only[/bold yellow]  [C] All")
        else:
            parts.append("[C] Conflicts only")
        with contextlib.suppress(NoMatches):
            self.query_one("#tools-status-bar", Static).update("  │  ".join(parts))

    @staticmethod
    def _item_matches(item: dict[str, Any], query: str, fields: tuple) -> bool:
        """Return True if *query* appears in any of the named *fields*."""
        return any(query in (item.get(f, "") or "").lower() for f in fields)

    def on_switch_changed(self, event: Switch.Changed) -> None:
        """Toggle filter active state without clearing the input."""
        if event.switch.id != "tools-filter-switch":
            return
        self._filter_enabled = event.value
        self._apply_search_filter()

    def _apply_search_filter(self) -> None:
        """Re-apply the current search filter."""
        try:
            search = self.query_one("#tools-search", Input)
        except NoMatches:
            return
        query = search.value.strip().lower()
        if not query or not self._filter_enabled:
            base = self._get_base_tools()
            self._populate_tables(base)
            return
        self._filter_with_query(query)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Live-filter capability tables based on search text."""
        if event.input.id != "tools-search":
            return
        if not self._filter_enabled:
            return
        query = event.value.strip().lower()
        if not query:
            base = self._get_base_tools()
            self._populate_tables(base)
            return
        self._filter_with_query(query)

    def _filter_with_query(self, query: str) -> None:
        """Apply text filter across tools, resources, and prompts."""
        base_tools = self._get_base_tools()
        filtered_tools = [
            t
            for t in base_tools
            if self._item_matches(t, query, ("name", "description", "original_name"))
        ]
        filtered_resources = [
            r
            for r in self._cached_resources
            if self._item_matches(r, query, ("name", "uri", "description"))
        ]
        filtered_prompts = [
            p for p in self._cached_prompts if self._item_matches(p, query, ("name", "description"))
        ]
        try:
            cap = self.query_one("#tools-cap-tables", CapabilitySection)
            cap.populate(
                filtered_tools, filtered_resources, filtered_prompts, self._cached_route_map
            )
        except NoMatches:
            pass
        self._update_status_bar(filtered_tools)

    def _get_base_tools(self) -> list[dict[str, Any]]:
        """Return cached tools respecting conflict/filter toggles."""
        tools = self._cached_tools
        if not self._show_filtered:
            tools = [t for t in tools if not t.get("filtered")]
        if self._conflicts_only:
            tools = [t for t in tools if t.get("renamed")]
        return tools

    def action_focus_search(self) -> None:
        """Focus the search input."""
        with contextlib.suppress(NoMatches):
            self.query_one("#tools-search", Input).focus()

    def action_clear_search(self) -> None:
        """Clear the search and reset filter."""
        try:
            search = self.query_one("#tools-search", Input)
            if search.value:
                search.value = ""
            else:
                # If already empty, let escape propagate
                pass
        except NoMatches:
            pass

    def action_toggle_conflicts(self) -> None:
        """Toggle showing only renamed/conflicting tools."""
        self._conflicts_only = not self._conflicts_only
        base = self._get_base_tools()
        self._populate_tables(base)

    def action_toggle_filtered(self) -> None:
        """Toggle visibility of filtered/hidden tools."""
        self._show_filtered = not self._show_filtered
        base = self._get_base_tools()
        self._populate_tables(base)

    def _update_frequency_chart(self, tools: list[dict[str, Any]]) -> None:
        """Update the frequency bar chart from tool metadata."""
        try:
            chart = self.query_one("#tools-freq-chart", FrequencyChart)
        except NoMatches:
            return
        # Use backend occurrence count as a proxy for invocation frequency
        names = [t.get("name", "?") for t in tools]
        counts = [1] * len(names)
        if names:
            chart.set_data(names[:20], counts[:20])
