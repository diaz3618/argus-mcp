"""Server groups widget — collapsible group tree for sidebar navigation.

Groups backends into named categories with batch operations
per group (restart all, stop all, health check).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Label, Tree

from argus_cli.tui._constants import phase_icon
from argus_cli.tui._error_utils import safe_query

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class ServerGroupsWidget(Widget):
    """Collapsible server groups tree for sidebar."""

    DEFAULT_CSS = """
    ServerGroupsWidget {
        height: auto;
        max-height: 20;
        border: round $accent;
        padding: 0 1;
    }
    #sg-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 0;
    }
    #sg-tree {
        height: auto;
        max-height: 16;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._groups: dict[str, list[dict[str, Any]]] = {}

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Server Groups[/b]", id="sg-title")
            yield Tree("Servers", id="sg-tree")

    def on_mount(self) -> None:
        if tree := safe_query(self, "#sg-tree", Tree):
            tree.root.expand()

    def update_groups(
        self,
        backends: list[dict[str, Any]],
        groups: dict[str, list[str]] | None = None,
    ) -> None:
        """Rebuild the server groups tree.

        Args:
            backends: List of backend dicts from the management API.
            groups: Optional mapping of group name → list of backend names.
                    If None, backends are grouped by their 'group' field.
        """
        tree = safe_query(self, "#sg-tree", Tree)
        if tree is None:
            return
        tree.clear()

        if groups is None:
            groups = {}
            for b in backends:
                group_name = b.get("group", "ungrouped") or "ungrouped"
                groups.setdefault(group_name, []).append(b.get("name", "?"))

        self._groups = {}
        backend_map = {b.get("name"): b for b in backends}

        for group_name, members in sorted(groups.items()):
            # Defensive: members might be a dict {servers: [...], count: N}
            if isinstance(members, dict):
                members = members.get("servers", [])
            elif not isinstance(members, list):
                continue
            total = len(members)

            group_label = f"{group_name} ({total})"
            group_node = tree.root.add(group_label, expand=(group_name != "ungrouped"))

            group_backends = []
            for member_name in members:
                b = backend_map.get(member_name, {})
                phase = b.get("phase", "unknown").lower()
                tools = b.get("capabilities", {}).get("tools", 0) if b.get("capabilities") else "?"
                transport = b.get("type", "?")

                icon = phase_icon(phase)

                group_node.add_leaf(f"{icon} {member_name}  {transport}  {tools} tools")
                group_backends.append(b)

            self._groups[group_name] = group_backends
