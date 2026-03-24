"""Tool Ops widget — batch tool validation and diagnostic panel.

Lives inside the Operations screen as a TabPane.  Uses cached
capabilities from ``app._last_caps`` to display tool metadata,
run validation checks, and show diagnostic summaries.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any

from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.widgets import Button, DataTable, Input, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class ToolOpsPanel(Static):
    """Batch tool validation, metadata normalization checks, and diagnostics."""

    DEFAULT_CSS = """
    ToolOpsPanel { height: 1fr; padding: 0 1; }
    """

    def compose(self) -> ComposeResult:
        yield Static(
            "[b]Tool Operations[/b]  — Validate & diagnose registered tools",
            classes="panel-heading",
        )
        with Horizontal(id="toolops-control-bar"):
            yield Input(placeholder="Filter tools…", id="toolops-filter")
            yield Button("Refresh", id="btn-toolops-refresh", variant="primary")
            yield Button("Validate All", id="btn-toolops-validate", variant="warning")

        yield DataTable(id="toolops-table")
        with Horizontal(id="toolops-status-bar"):
            yield Static("", id="toolops-stats")

    def on_mount(self) -> None:
        try:
            table = self.query_one("#toolops-table", DataTable)
            table.add_columns("Tool", "Backend", "Schema", "Params", "Issues")
            table.cursor_type = "row"
        except NoMatches:
            pass
        self._refresh_data()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-toolops-refresh":
            self._refresh_data()
        elif event.button.id == "btn-toolops-validate":
            self._run_validation()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "toolops-filter":
            self._refresh_data()

    def _get_tools(self) -> list[dict[str, Any]]:
        """Extract tool dicts from cached capabilities."""
        caps = self.app.last_caps
        if caps is None:
            return []
        try:
            return [t.model_dump() for t in caps.tools]
        except (AttributeError, TypeError):
            return []

    def _get_route_map(self) -> dict[str, str]:
        """Extract route_map from cached capabilities."""
        caps = self.app.last_caps
        if caps is None:
            return {}
        return getattr(caps, "route_map", {}) or {}

    def _get_filter(self) -> str:
        try:
            return self.query_one("#toolops-filter", Input).value.lower()
        except NoMatches:
            return ""

    def _refresh_data(self) -> None:
        """Populate the tools table from cached capabilities."""
        tools = self._get_tools()
        route_map = self._get_route_map()
        filt = self._get_filter()

        try:
            table = self.query_one("#toolops-table", DataTable)
            table.clear()
        except NoMatches:
            return

        displayed = 0
        for tool in tools:
            name = tool.get("name", "?")
            if filt and filt not in name.lower():
                continue
            backend = route_map.get(name, "—")
            schema = tool.get("inputSchema") or tool.get("input_schema") or {}
            param_count = len(schema.get("properties", {})) if isinstance(schema, dict) else 0
            schema_type = schema.get("type", "—") if isinstance(schema, dict) else "—"
            table.add_row(name, backend, schema_type, str(param_count), "—")
            displayed += 1

        with contextlib.suppress(NoMatches):
            self.query_one("#toolops-stats", Static).update(
                f" {displayed} tools shown  |  {len(tools)} total"
            )

    def _run_validation(self) -> None:
        """Run metadata quality checks on all tools."""
        tools = self._get_tools()
        route_map = self._get_route_map()
        filt = self._get_filter()

        try:
            table = self.query_one("#toolops-table", DataTable)
            table.clear()
        except NoMatches:
            return

        issue_count = 0
        for tool in tools:
            name = tool.get("name", "?")
            if filt and filt not in name.lower():
                continue
            backend = route_map.get(name, "—")
            schema = tool.get("inputSchema") or tool.get("input_schema") or {}
            param_count = len(schema.get("properties", {})) if isinstance(schema, dict) else 0
            schema_type = schema.get("type", "—") if isinstance(schema, dict) else "—"

            issues = self._check_tool_issues(tool, schema, backend)

            if issues:
                issue_count += 1
                issue_text = "[yellow]" + ", ".join(issues) + "[/yellow]"
            else:
                issue_text = "[green]✓ ok[/green]"

            table.add_row(name, backend, schema_type, str(param_count), issue_text)

        with contextlib.suppress(NoMatches):
            self.query_one("#toolops-stats", Static).update(
                f" {len(tools)} tools  |  {issue_count} with issues"
            )

        self.app.notify(f"Validation: {issue_count} issue(s) in {len(tools)} tools", timeout=3)

    @staticmethod
    def _check_tool_issues(tool: dict, schema: Any, backend: str) -> list[str]:
        """Check a single tool's metadata for quality issues."""
        issues: list[str] = []
        if not tool.get("description", ""):
            issues.append("no description")
        if not isinstance(schema, dict) or "properties" not in schema:
            issues.append("no input schema")
        elif schema.get("type", "—") != "object":
            issues.append(f"schema type={schema.get('type', '—')}")
        if backend == "—":
            issues.append("unrouted")
        return issues
