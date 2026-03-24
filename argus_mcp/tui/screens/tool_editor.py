"""Tool editor screen — visual tool customization interface.

Sub-screen within Settings mode for customizing tools:
- Rename with live preview
- Include/exclude toggle
- Parameter defaults
- Save to config / undo
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import yaml  # type: ignore[import-untyped]
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, DataTable, Input, Label, Static

from argus_mcp._error_utils import safe_query
from argus_mcp.tui._config_ops import resolve_config_path, trigger_reload
from argus_mcp.tui.screens.base import ArgusScreen
from argus_mcp.tui.widgets.param_editor import ParamEditorWidget
from argus_mcp.tui.widgets.tool_preview import ToolPreviewWidget

logger = logging.getLogger(__name__)


class ToolEditorScreen(ArgusScreen):
    """Interactive tool customization screen.

    Layout:
    - Left: tool list (DataTable)
    - Center: editing controls (rename, filter, defaults)
    - Right: live preview of tool as client sees it
    """

    CSS = """
    ToolEditorScreen {
        layout: horizontal;
    }

    #tool-list-panel {
        width: 1fr;
        border: solid $primary;
        padding: 1;
    }

    #editor-panel {
        width: 2fr;
        border: solid $accent;
        padding: 1;
    }

    #preview-panel {
        width: 1fr;
        border: solid $success;
        padding: 1;
    }

    #rename-input {
        margin: 1 0;
    }

    .editor-section {
        margin-bottom: 1;
    }
    """

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("ctrl+s", "save_changes", "Save"),
        ("ctrl+z", "reset_tool", "Reset"),
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._tools: List[Dict[str, Any]] = []
        self._selected_tool: Optional[str] = None
        self._modifications: Dict[str, Dict[str, Any]] = {}

    def compose_content(self) -> ComposeResult:
        with Horizontal():
            # Left: Tool list
            with Vertical(id="tool-list-panel"):
                yield Label("[b]Tools[/b]")
                yield DataTable(id="tool-table")

            # Center: Editor
            with Vertical(id="editor-panel"):
                yield Label("[b]Tool Editor[/b]")
                yield Label("[dim]Select a tool to edit[/]", id="editor-hint")

                with Vertical(classes="editor-section", id="rename-section"):
                    yield Label("Rename:")
                    yield Input(placeholder="New tool name", id="rename-input")

                with Vertical(classes="editor-section", id="include-section"):
                    yield Label("Included:")
                    yield Button("Toggle Include/Exclude", id="toggle-include")

                with Vertical(classes="editor-section", id="defaults-section"):
                    yield Label("Parameter Defaults:")
                    yield ParamEditorWidget(id="param-editor")

                with Vertical(id="actions-section"):
                    yield Button("Save All Changes", variant="primary", id="save-btn")
                    yield Button("Reset Selected", variant="warning", id="reset-btn")

            # Right: Preview
            with Vertical(id="preview-panel"):
                yield ToolPreviewWidget(id="tool-preview")
                yield Static(
                    "[dim]Pending changes will appear here[/]",
                    id="diff-panel",
                )

    def on_mount(self) -> None:
        table = self.query_one("#tool-table", DataTable)
        table.add_columns("Name", "Backend", "Status")
        table.cursor_type = "row"

    def on_show(self) -> None:
        """Populate the tool list from app-level cached capabilities."""
        app = self.app
        caps = app.last_caps
        if caps is not None:
            tools = []
            for t in caps.tools:
                d = t.model_dump()
                # Map route_map to add backend info
                route = caps.route_map.get(d.get("name", ""), ("", ""))
                d["backend"] = route[0] if route else ""
                tools.append(d)
            self.load_tools(tools)

    def load_tools(self, tools: List[Dict[str, Any]]) -> None:
        """Load tools into the editor."""
        self._tools = tools
        table = self.query_one("#tool-table", DataTable)
        table.clear()
        for tool in tools:
            name = tool.get("name", "unknown")
            backend = tool.get("backend", "")
            # Check modifications for include status
            mods = self._modifications.get(name, {})
            included = mods.get("included", tool.get("included", True))
            status = "✓" if included else "✗"
            table.add_row(name, backend, status, key=name)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.row_key and event.row_key.value:
            self._select_tool(event.row_key.value)

    def _select_tool(self, tool_name: str) -> None:
        """Update editor and preview for the selected tool."""
        self._selected_tool = tool_name

        # Find tool info
        tool_info = next(
            (t for t in self._tools if t.get("name") == tool_name),
            None,
        )
        if not tool_info:
            return

        mods = self._modifications.get(tool_name, {})
        display_name = mods.get("rename", tool_name)

        rename = self.query_one("#rename-input", Input)
        rename.value = display_name

        # Update parameter editor with tool's input schema
        if param_editor := safe_query(self, "#param-editor", ParamEditorWidget):
            schema = tool_info.get("inputSchema", {})
            defaults = mods.get("defaults", {})
            param_editor.load_schema(schema, defaults)

        # Update preview
        preview = self.query_one("#tool-preview", ToolPreviewWidget)
        preview.update_preview(
            {
                "name": display_name,
                "description": tool_info.get("description", ""),
                "inputSchema": tool_info.get("inputSchema", {}),
            }
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "rename-input" and self._selected_tool:
            if self._selected_tool not in self._modifications:
                self._modifications[self._selected_tool] = {}
            self._modifications[self._selected_tool]["rename"] = event.value

            # Update preview
            tool_info = next(
                (t for t in self._tools if t.get("name") == self._selected_tool),
                None,
            )
            if tool_info:
                preview = self.query_one("#tool-preview", ToolPreviewWidget)
                preview.update_preview(
                    {
                        "name": event.value,
                        "description": tool_info.get("description", ""),
                        "inputSchema": tool_info.get("inputSchema", {}),
                    }
                )
            self._update_diff_panel()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "toggle-include":
            self._toggle_include()
        elif event.button.id == "save-btn":
            self.action_save_changes()
        elif event.button.id == "reset-btn":
            self.action_reset_tool()

    def _toggle_include(self) -> None:
        if not self._selected_tool:
            return
        if self._selected_tool not in self._modifications:
            self._modifications[self._selected_tool] = {}
        # Get current state: check modifications first, then original tool data
        tool_info = next((t for t in self._tools if t.get("name") == self._selected_tool), None)
        original = tool_info.get("included", True) if tool_info else True
        current = self._modifications[self._selected_tool].get("included", original)
        self._modifications[self._selected_tool]["included"] = not current
        self.load_tools(self._tools)
        self._update_diff_panel()

    def action_save_changes(self) -> None:
        """Save tool customizations to the YAML config file.

        Writes tool_overrides entries for renames, include/exclude, and
        parameter defaults, then triggers a server config reload.
        """
        if not self._modifications:
            self.notify("No changes to save")
            return

        config_path = self._resolve_config_path()
        if config_path is None:
            self.notify(
                "Cannot locate config file — save manually",
                severity="warning",
            )
            return

        try:
            with open(config_path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}

            overrides: Dict[str, Any] = data.setdefault("tool_overrides", {})

            for tool_name, mods in self._modifications.items():
                entry = overrides.setdefault(tool_name, {})
                if "rename" in mods and mods["rename"] != tool_name:
                    entry["display_name"] = mods["rename"]
                if "included" in mods:
                    entry["enabled"] = mods["included"]
                if "defaults" in mods and mods["defaults"]:
                    entry["defaults"] = mods["defaults"]

            with open(config_path, "w", encoding="utf-8") as fh:
                yaml.dump(data, fh, default_flow_style=False, sort_keys=False)

            count = len(self._modifications)
            self._modifications.clear()
            logger.info("Saved %d tool override(s) to %s", count, config_path)
            self.notify(
                f"Saved {count} tool customization(s) to {os.path.basename(config_path)}",
                title="Saved",
            )

            # Trigger hot-reload
            self._trigger_reload()

        except (OSError, yaml.YAMLError) as exc:
            logger.error("Failed to save tool overrides: %s", exc)
            self.notify(f"Save failed: {exc}", severity="error")

    def _resolve_config_path(self) -> Optional[str]:
        return resolve_config_path(self.app)

    def _trigger_reload(self) -> None:
        trigger_reload(
            self.app,
            notify=self.notify,
            worker_name="editor-reload",
        )

    def action_reset_tool(self) -> None:
        """Reset modifications for the selected tool."""
        if self._selected_tool and self._selected_tool in self._modifications:
            del self._modifications[self._selected_tool]
            self._select_tool(self._selected_tool)
            self.notify(f"Reset '{self._selected_tool}'")

    def _update_diff_panel(self) -> None:
        """Render a summary of all pending modifications."""
        diff = safe_query(self, "#diff-panel", Static)
        if diff is None:
            return
        if not self._modifications:
            diff.update("[dim]No pending changes[/]")
            return
        lines = ["[b]Pending Changes:[/b]"]
        for tool_name, mods in self._modifications.items():
            parts: list[str] = []
            if "rename" in mods and mods["rename"] != tool_name:
                parts.append(f"rename → {mods['rename']}")
            if "included" in mods:
                parts.append("exclude" if not mods["included"] else "include")
            if "defaults" in mods and mods["defaults"]:
                parts.append(f"{len(mods['defaults'])} defaults")
            if parts:
                lines.append(f"  [cyan]{tool_name}[/cyan]: {', '.join(parts)}")
        diff.update("\n".join(lines))

    def action_go_back(self) -> None:
        """Return to settings."""
        self.app.pop_screen()

    def get_modifications(self) -> Dict[str, Dict[str, Any]]:
        """Return all pending modifications."""
        return dict(self._modifications)
