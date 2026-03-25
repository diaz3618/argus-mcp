"""Capability DataTable widgets for tools, resources, and prompts."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import DataTable, TabbedContent, TabPane

from argus_cli.tui._error_utils import safe_query

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


def _trunc(text: str | None, max_len: int = 80) -> str:
    """Truncate long descriptions for table display."""
    if not text:
        return "—"
    first_line = text.strip().split("\n")[0]
    if len(first_line) > max_len:
        return first_line[: max_len - 1] + "…"
    return first_line


def _attr_or_key(obj: Any, key: str, default: Any = None) -> Any:
    """Get a value from *obj* whether it is a dict or an object with attrs.

    This lets ``populate()`` work with both MCP SDK objects
    (in-process mode) and plain dicts returned by the management API.
    """
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class CapabilitySection(Widget):
    """Tabbed view of Tools / Resources / Prompts DataTables."""

    tools_count: reactive[int] = reactive(0)
    resources_count: reactive[int] = reactive(0)
    prompts_count: reactive[int] = reactive(0)
    _conflicts_count: int = 0

    def compose(self) -> ComposeResult:
        with TabbedContent(id="cap-tabs"):
            with TabPane("Tools (0)", id="tab-tools"):
                yield DataTable(id="dt-tools")
            with TabPane("Resources (0)", id="tab-resources"):
                yield DataTable(id="dt-resources")
            with TabPane("Prompts (0)", id="tab-prompts"):
                yield DataTable(id="dt-prompts")

    def on_mount(self) -> None:
        dt_tools = self.query_one("#dt-tools", DataTable)
        dt_tools.add_columns("Name", "Original", "Server", "Description")
        dt_tools.cursor_type = "row"
        dt_tools.zebra_stripes = True

        dt_res = self.query_one("#dt-resources", DataTable)
        dt_res.add_columns("Name / URI", "Server", "Description", "MIME Type")
        dt_res.cursor_type = "row"
        dt_res.zebra_stripes = True

        dt_prompts = self.query_one("#dt-prompts", DataTable)
        dt_prompts.add_columns("Name", "Server", "Description", "Arguments")
        dt_prompts.cursor_type = "row"
        dt_prompts.zebra_stripes = True

    def _update_tab_labels(self) -> None:
        """Re-label tabs with current counts.

        Uses ``TabbedContent.get_tab()`` to obtain the actual ``Tab``
        widget (the clickable button) rather than setting
        ``TabPane.label`` which does not propagate to the visible tab.
        """
        if tabs := safe_query(self, "#cap-tabs", TabbedContent):
            conflicts_note = f" ⚡{self._conflicts_count}" if self._conflicts_count else ""
            tabs.get_tab("tab-tools").label = f"Tools ({self.tools_count}){conflicts_note}"
            tabs.get_tab("tab-resources").label = f"Resources ({self.resources_count})"
            tabs.get_tab("tab-prompts").label = f"Prompts ({self.prompts_count})"

    def watch_tools_count(self) -> None:
        self._update_tab_labels()

    def watch_resources_count(self) -> None:
        self._update_tab_labels()

    def watch_prompts_count(self) -> None:
        self._update_tab_labels()

    def _populate_tools_table(self, tools: list[Any], rmap: dict[str, tuple[str, str]]) -> int:
        """Fill the Tools DataTable and return the conflict count.

        Tools are grouped by backend server with styled separator rows.
        """
        dt_tools = self.query_one("#dt-tools", DataTable)
        dt_tools.clear()
        conflicts = 0

        # Build (server, row_data) pairs for grouping
        rows_by_server: dict[str, list[tuple]] = {}
        for t in tools:
            name = _attr_or_key(t, "name", "—")
            original = _attr_or_key(t, "original_name", "")
            renamed = _attr_or_key(t, "renamed", False)
            filtered = _attr_or_key(t, "filtered", False)
            server = _attr_or_key(t, "backend", "") or rmap.get(name, ("—", ""))[0]
            desc = _attr_or_key(t, "description")

            if renamed and original and original != name:
                original_display = f"[yellow]⚡ {original}[/yellow]"
                conflicts += 1
            elif filtered:
                original_display = "[dim]filtered[/dim]"
            else:
                original_display = "—"

            rows_by_server.setdefault(server, []).append(
                (name, original_display, server, _trunc(desc))
            )

        # Emit rows grouped by server with header separators
        for server_name, rows in sorted(rows_by_server.items()):
            count = len(rows)
            header = f"[b]▸ {server_name}[/b] ({count} tool{'s' if count != 1 else ''})"
            dt_tools.add_row(header, "", "", "", key=f"__group__{server_name}")
            for name, orig, srv, desc in rows:
                dt_tools.add_row(f"  {name}", orig, srv, desc, key=name)

        return conflicts

    def _populate_resources_table(
        self, resources: list[Any], rmap: dict[str, tuple[str, str]]
    ) -> None:
        """Fill the Resources DataTable."""
        dt_res = self.query_one("#dt-resources", DataTable)
        dt_res.clear()
        for r in resources:
            name = _attr_or_key(r, "name", "—")
            server = rmap.get(name, ("—", ""))[0]
            uri = _attr_or_key(r, "uri", name)
            mime = _attr_or_key(r, "mimeType") or _attr_or_key(r, "mime_type") or "—"
            desc = _attr_or_key(r, "description")
            dt_res.add_row(str(uri), server, _trunc(desc) if desc else "—", mime, key=name)

    def _populate_prompts_table(self, prompts: list[Any], rmap: dict[str, tuple[str, str]]) -> None:
        """Fill the Prompts DataTable."""
        dt_prompts = self.query_one("#dt-prompts", DataTable)
        dt_prompts.clear()
        for p in prompts:
            name = _attr_or_key(p, "name", "—")
            server = rmap.get(name, ("—", ""))[0]
            desc = _attr_or_key(p, "description")
            args_raw = _attr_or_key(p, "arguments") or []
            if args_raw:
                arg_names = [_attr_or_key(a, "name", str(a)) for a in args_raw]
                args_str = ", ".join(arg_names)
            else:
                args_str = "—"
            dt_prompts.add_row(name, server, _trunc(desc) if desc else "—", args_str, key=name)

    def populate(
        self,
        tools: list[Any],
        resources: list[Any],
        prompts: list[Any],
        route_map: dict[str, tuple[str, str]] | None = None,
    ) -> None:
        """Fill all three tables from MCP type lists or API dicts."""
        rmap = route_map or {}

        self._conflicts_count = self._populate_tools_table(tools, rmap)
        self.tools_count = len(tools)

        self._populate_resources_table(resources, rmap)
        self.resources_count = len(resources)

        self._populate_prompts_table(prompts, rmap)
        self.prompts_count = len(prompts)
