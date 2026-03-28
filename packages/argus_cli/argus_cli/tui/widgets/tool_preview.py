"""Tool preview widget — shows how a tool appears to MCP clients.

Renders a live preview of the tool after customization (rename,
filter, parameter defaults), so users can see exactly what clients
will see.
"""

from __future__ import annotations

import json
from typing import Any

from textual.widgets import Static


class ToolPreviewWidget(Static):
    """Displays a formatted preview of a tool's client-facing shape.

    Attributes
    ----------
    tool_info:
        Tool info dict with keys: name, description, inputSchema.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._tool_info: dict[str, Any] | None = None

    def update_preview(self, tool_info: dict[str, Any]) -> None:
        """Update the preview with new tool info."""
        self._tool_info = tool_info
        self.refresh()

    def clear_preview(self) -> None:
        """Clear the preview."""
        self._tool_info = None
        self.refresh()

    def render(self) -> str:
        if not self._tool_info:
            return "[dim]Select a tool to preview[/]"

        name = self._tool_info.get("name", "")
        desc = self._tool_info.get("description", "")
        schema = self._tool_info.get("inputSchema", {})

        lines = [
            "[b]Client Preview[/b]",
            "",
            f"[b]Name:[/b]  {name}",
            f"[b]Desc:[/b]  {desc}",
            "",
            "[b]Input Schema:[/b]",
        ]

        if schema:
            try:
                schema_str = json.dumps(schema, indent=2)
                lines.append(schema_str)
            except (TypeError, ValueError):
                lines.append(str(schema))
        else:
            lines.append("  [dim](no parameters)[/]")

        return "\n".join(lines)
