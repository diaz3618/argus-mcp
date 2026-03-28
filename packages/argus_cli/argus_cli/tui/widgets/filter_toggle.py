"""Filter toggle widget — visual include/exclude toggle for tools.

Shows a list of tools with toggleable switches for including or
excluding them from the exposed tool set.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Label, Static, Switch

from argus_cli.tui._error_utils import safe_query

if TYPE_CHECKING:
    from textual.app import ComposeResult


class FilterToggleWidget(Static):
    """Displays toggleable filters for tools.

    Posts :class:`FilterChanged` when a tool's include/exclude state changes.
    """

    class FilterChanged(Message):
        """Posted when a tool's filter state changes."""

        def __init__(self, tool_name: str, included: bool) -> None:
            super().__init__()
            self.tool_name = tool_name
            self.included = included

    def __init__(self, tools: list[dict[str, Any]], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._tools = tools

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Tool Filters[/b]")
            for tool in self._tools:
                name = tool.get("name", "unknown")
                included = tool.get("included", True)
                yield Label(f"  {name}")
                yield Switch(
                    value=included,
                    id=f"filter-{name}",
                )

    def on_switch_changed(self, event: Switch.Changed) -> None:
        widget_id = event.switch.id or ""
        if widget_id.startswith("filter-"):
            tool_name = widget_id[len("filter-") :]
            self.post_message(self.FilterChanged(tool_name, event.value))

    def get_filter_state(self) -> dict[str, bool]:
        """Return current filter state for all tools."""
        state: dict[str, bool] = {}
        for tool in self._tools:
            name = tool.get("name", "unknown")
            sw = safe_query(self, f"#filter-{name}", Switch)
            state[name] = sw.value if sw is not None else True
        return state
