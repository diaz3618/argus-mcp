"""Version drift detection modal and widget.

Compares running server versions against registry latest versions
and shows update availability badges. Provides changelog view and
one-click update action.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Label, Static, TextArea

from argus_mcp._error_utils import safe_query

logger = logging.getLogger(__name__)


class VersionDriftPanel(Widget):
    """Version drift indicators for backend servers."""

    DEFAULT_CSS = """
    VersionDriftPanel {
        height: auto;
        max-height: 14;
        border: round $accent;
        padding: 0 1;
    }
    #vd-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 0;
    }
    #vd-summary {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    #vd-table {
        height: auto;
        max-height: 8;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Version Status[/b]", id="vd-title")
            yield Static("Updates available: 0 of 0 servers", id="vd-summary")
            yield DataTable(id="vd-table")

    def on_mount(self) -> None:
        if table := safe_query(self, "#vd-table", DataTable):
            table.add_columns("Server", "Current", "Registry", "Status")
            table.cursor_type = "row"
            table.zebra_stripes = True

    def update_versions(self, servers: List[Dict[str, Any]]) -> None:
        """Refresh version comparison table.

        Each dict should have: name, current_version, registry_version.
        """
        table = safe_query(self, "#vd-table", DataTable)
        if table is None:
            return
        table.clear()

        updates_available = 0
        total = len(servers)

        for s in servers:
            name = s.get("name", "?")
            current = s.get("current_version", s.get("version", "—"))
            registry = s.get("registry_version", s.get("latest", "—"))

            if not registry or registry == "—":
                status = "[dim]— No registry[/dim]"
            elif current == registry:
                status = "[green]✓ Up to date[/green]"
            else:
                updates_available += 1
                # Check if major version change
                cur_major = _parse_major(current)
                reg_major = _parse_major(registry)
                if cur_major is not None and reg_major is not None and reg_major > cur_major:
                    status = "[red]⬆ Major update[/red]"
                elif current and registry and current < registry:
                    status = "[yellow]⬆ Update available[/yellow]"
                else:
                    status = "[yellow]⬆ Update available[/yellow]"

            table.add_row(name, str(current), str(registry), status)

        summary = f"Updates available: {updates_available} of {total} servers"
        if w := safe_query(self, "#vd-summary", Static):
            w.update(summary)


def _parse_major(version: str) -> Optional[int]:
    """Extract major version number from a version string like 'v2.1.0'."""
    try:
        v = version.lstrip("v")
        return int(v.split(".")[0])
    except (ValueError, IndexError, AttributeError):
        return None


class ChangelogModal(ModalScreen[Optional[str]]):
    """Modal showing version changelog and update option."""

    DEFAULT_CSS = """
    ChangelogModal {
        align: center middle;
    }
    #changelog-dialog {
        width: 68;
        max-height: 24;
        border: thick $warning;
        background: $surface;
        padding: 1 2;
    }
    #cl-header {
        text-style: bold;
        text-align: center;
        margin-bottom: 1;
    }
    #cl-warning {
        color: $warning;
        margin-bottom: 1;
    }
    #cl-content {
        height: 8;
        margin-bottom: 1;
    }
    #cl-actions {
        height: 3;
        align: center middle;
    }
    #cl-actions Button {
        margin: 0 1;
    }
    """

    BINDINGS = [("escape", "close", "Close")]

    def __init__(
        self,
        server_name: str,
        current_version: str,
        new_version: str,
        changelog: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._server_name = server_name
        self._current = current_version
        self._new = new_version
        self._changelog = changelog

    def compose(self) -> ComposeResult:
        with Vertical(id="changelog-dialog"):
            yield Label(
                f"[b]{self._server_name} — {self._current} → {self._new}[/b]",
                id="cl-header",
            )

            cur_major = _parse_major(self._current)
            new_major = _parse_major(self._new)
            if cur_major is not None and new_major is not None and new_major > cur_major:
                yield Static(
                    "⚠ MAJOR version change — may include breaking changes",
                    id="cl-warning",
                )
            else:
                yield Static("", id="cl-warning")

            yield Label("[b]Changelog:[/b]")
            yield TextArea(
                self._changelog or "(no changelog available)",
                id="cl-content",
                read_only=True,
            )

            with Horizontal(id="cl-actions"):
                yield Button("Update Now", variant="primary", id="btn-cl-update")
                yield Button("Skip Version", variant="default", id="btn-cl-skip")
                yield Button("Cancel", variant="default", id="btn-cl-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cl-update":
            self.dismiss("update")
        elif event.button.id == "btn-cl-skip":
            self.dismiss("skip")
        elif event.button.id == "btn-cl-cancel":
            self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
