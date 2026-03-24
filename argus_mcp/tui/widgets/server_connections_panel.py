"""Server connections panel — add/remove/view MCP server connections."""

from __future__ import annotations

import json as _json
import logging
from typing import Any, Dict

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, Input, Label, Static, TextArea

logger = logging.getLogger(__name__)


class ServerConnectionsPanel(Static):
    """Self-contained widget for managing server connections."""

    def compose(self) -> ComposeResult:
        with Vertical(id="servers-section"):
            yield Static("[b]Server Connections[/b]", id="servers-title")
            yield TextArea("", id="servers-viewer", read_only=True, language="json")

            yield Static("[b]Add / Edit Server[/b]", id="add-server-title")
            with Horizontal(classes="setting-row"):
                yield Label("Name:", classes="setting-label")
                yield Input(placeholder="my-server", id="server-name-input")
            with Horizontal(classes="setting-row"):
                yield Label("URL:", classes="setting-label")
                yield Input(
                    placeholder="http://127.0.0.1:9000",
                    id="server-url-input",
                )
            with Horizontal(classes="setting-row"):
                yield Label("Token:", classes="setting-label")
                yield Input(
                    placeholder="(optional)",
                    id="server-token-input",
                    password=True,
                )
            with Horizontal(classes="setting-row"):
                yield Button("Add Server", id="btn-add-server", variant="primary")
                yield Button("Remove Selected", id="btn-remove-server", variant="error")

    def on_mount(self) -> None:
        self.refresh_servers()

    def refresh_servers(self) -> None:
        """Populate the viewer with current server connection data."""
        mgr = self.app.server_manager
        if mgr is None:
            return
        try:
            entries = mgr.entries
            data: Dict[str, Any] = {}
            for name, entry in entries.items():
                data[name] = {
                    "url": entry.url,
                    "connected": entry.connected,
                    "active": (name == mgr.active_name),
                }
            viewer = self.query_one("#servers-viewer", TextArea)
            viewer.load_text(_json.dumps(data, indent=2))
        except NoMatches:
            logger.debug("Could not refresh servers", exc_info=True)

    @on(Button.Pressed, "#btn-add-server")
    def _do_add_server(self, event: Button.Pressed) -> None:
        """Add a server from the input fields."""
        try:
            name = self.query_one("#server-name-input", Input).value.strip()
            url = self.query_one("#server-url-input", Input).value.strip()
            token = self.query_one("#server-token-input", Input).value.strip() or None
        except NoMatches:
            return

        if not name or not url:
            self.notify("Name and URL are required", severity="warning")
            return

        mgr = self.app.server_manager
        if mgr is None:
            self.notify("No server manager available", severity="error")
            return

        mgr.add(name, url, token)
        mgr.save()
        self.notify(f"Added server '{name}' ({url})", title="Server Added")
        self.refresh_servers()

        try:
            self.query_one("#server-name-input", Input).value = ""
            self.query_one("#server-url-input", Input).value = ""
            self.query_one("#server-token-input", Input).value = ""
        except NoMatches:
            pass

    @on(Button.Pressed, "#btn-remove-server")
    def _do_remove_server(self, event: Button.Pressed) -> None:
        """Remove the server whose name is in the name input."""
        try:
            name = self.query_one("#server-name-input", Input).value.strip()
        except NoMatches:
            return

        if not name:
            self.notify("Enter the server name to remove", severity="warning")
            return

        mgr = self.app.server_manager
        if mgr is None:
            self.notify("No server manager available", severity="error")
            return

        try:
            mgr.remove(name)
            mgr.save()
            self.notify(f"Removed server '{name}'", title="Server Removed")
            self.refresh_servers()
        except KeyError:
            self.notify(f"No server named '{name}'", severity="warning")
