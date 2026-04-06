"""Install panel widget — server detail view and install action.

Shows details for a selected :class:`ServerEntry` and provides
an install button to add it to the Argus configuration.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Button, Label, Static

from argus_mcp.registry.models import ServerEntry
from argus_mcp.tui._error_utils import safe_query

logger = logging.getLogger(__name__)


class InstallConfirmed(Message):
    """Posted when the user confirms adding a server to the config."""

    def __init__(self, entry: ServerEntry, config: dict) -> None:
        super().__init__()
        self.entry = entry
        self.config = config


class InstallPanelWidget(Widget):
    """Side-panel showing details for a selected registry entry.

    Attributes
    ----------
    selected_entry : ServerEntry | None
        The currently displayed entry.
    """

    DEFAULT_CSS = """
    InstallPanelWidget {
        width: 40;
        height: 1fr;
        border-left: solid $accent;
        padding: 1 2;
        layout: vertical;
    }
    InstallPanelWidget #install-title {
        text-style: bold;
        margin-bottom: 1;
    }
    InstallPanelWidget #install-details {
        height: 1fr;
    }
    InstallPanelWidget #install-btn {
        dock: bottom;
        margin-top: 1;
    }
    """

    selected_entry: reactive[Optional[ServerEntry]] = reactive(None)

    def compose(self) -> ComposeResult:
        yield Label("Server Details", id="install-title")
        with VerticalScroll(id="install-details"):
            yield Static("Select a server to view details.", id="install-info")
        yield Button("Add to Config", id="install-btn", variant="primary", disabled=True)

    def watch_selected_entry(self, entry: Optional[ServerEntry]) -> None:
        self._update_detail(entry)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "install-btn" and self.selected_entry is not None:
            config = self.selected_entry.to_backend_config()
            self.post_message(InstallConfirmed(self.selected_entry, config))

    def _update_detail(self, entry: Optional[ServerEntry]) -> None:
        info = safe_query(self, "#install-info", Static)
        btn = safe_query(self, "#install-btn", Button)
        if info is None or btn is None:
            return

        if entry is None:
            info.update("Select a server to view details.")
            btn.disabled = True
            return

        lines = [
            f"[b]{entry.name}[/b]",
            "",
            f"[dim]Transport:[/dim]  {entry.transport}",
        ]
        if entry.url:
            lines.append(f"[dim]URL:[/dim]        {entry.url}")
        if entry.command:
            cmd = entry.command
            if entry.args:
                cmd += " " + " ".join(entry.args)
            lines.append(f"[dim]Command:[/dim]    {cmd}")
        if entry.version:
            lines.append(f"[dim]Version:[/dim]    {entry.version}")
        if entry.categories:
            lines.append(f"[dim]Categories:[/dim] {', '.join(entry.categories)}")

        if entry.tools:
            lines.append("")
            lines.append(f"[b]Tools ({len(entry.tools)}):[/b]")
            for tool in entry.tools[:20]:  # cap display
                desc = f"  — {tool.description}" if tool.description else ""
                lines.append(f"  • {tool.name}{desc}")
            if len(entry.tools) > 20:
                lines.append(f"  … and {len(entry.tools) - 20} more")

        lines.append("")
        lines.append("[dim]Config preview:[/dim]")
        lines.append(json.dumps(entry.to_backend_config(), indent=2))

        info.update("\n".join(lines))
        btn.disabled = False
