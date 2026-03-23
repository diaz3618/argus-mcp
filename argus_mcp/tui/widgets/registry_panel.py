"""Registry manager panel — add/remove/view MCP server registries."""

from __future__ import annotations

import json as _json
import logging

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, Input, Label, Select, Static, TextArea

logger = logging.getLogger(__name__)


class RegistryManagerPanel(Static):
    """Self-contained widget for managing registry sources."""

    def compose(self) -> ComposeResult:
        with Vertical(id="registries-section"):
            yield Static("[b]Registry Sources[/b]", id="registries-title")
            yield Static(
                "[dim]Configure multiple MCP server registries with priority ordering.[/dim]",
                id="registries-hint",
            )
            yield TextArea(
                "",
                id="registries-viewer",
                read_only=True,
                language="json",
            )
            yield Static("[b]Add Registry[/b]", id="registries-add-title")
            with Horizontal(classes="setting-row"):
                yield Label("Name:", classes="setting-label")
                yield Input(placeholder="community", id="reg-name-input")
            with Horizontal(classes="setting-row"):
                yield Label("URL:", classes="setting-label")
                yield Input(
                    placeholder="https://registry.example.com",
                    id="reg-url-input",
                )
            with Horizontal(classes="setting-row"):
                yield Label("Priority:", classes="setting-label")
                yield Input(placeholder="100", id="reg-priority-input", type="number")
            with Horizontal(classes="setting-row"):
                yield Label("Auth:", classes="setting-label")
                yield Select(
                    [("none", "none"), ("api-key", "api-key"), ("bearer", "bearer")],
                    value="none",
                    id="reg-auth-select",
                    allow_blank=False,
                )
            with Horizontal(classes="setting-row"):
                yield Button("Add Registry", id="btn-add-registry", variant="primary")
                yield Button("Remove Selected", id="btn-remove-registry", variant="error")

    def on_mount(self) -> None:
        self.refresh_registries()

    def refresh_registries(self) -> None:
        """Populate the viewer with current registry data."""
        try:
            viewer = self.query_one("#registries-viewer", TextArea)
            from argus_mcp.tui.settings import load_settings

            settings = load_settings()
            registries = settings.get("registries", [])
            viewer.load_text(_json.dumps(registries, indent=2))
        except NoMatches:
            logger.debug("Could not refresh registries", exc_info=True)

    @on(Button.Pressed, "#btn-add-registry")
    def _do_add_registry(self, event: Button.Pressed) -> None:
        """Add a registry from the input fields."""
        try:
            name = self.query_one("#reg-name-input", Input).value.strip()
            url = self.query_one("#reg-url-input", Input).value.strip()
            priority = self.query_one("#reg-priority-input", Input).value.strip()
            auth = self.query_one("#reg-auth-select", Select).value
        except NoMatches:
            return

        if not name or not url:
            self.notify("Name and URL are required", severity="warning")
            return

        from argus_mcp.tui.settings import load_settings, save_settings

        settings = load_settings()
        registries = settings.get("registries", [])
        registries.append(
            {
                "name": name,
                "url": url,
                "priority": int(priority) if priority else 100,
                "auth": auth or "none",
            }
        )
        settings["registries"] = registries
        save_settings(settings)
        self.notify(f"Added registry '{name}'", title="Registry Added")
        self.refresh_registries()

        # Clear inputs
        try:
            self.query_one("#reg-name-input", Input).value = ""
            self.query_one("#reg-url-input", Input).value = ""
            self.query_one("#reg-priority-input", Input).value = "100"
        except NoMatches:
            pass

    @on(Button.Pressed, "#btn-remove-registry")
    def _do_remove_registry(self, event: Button.Pressed) -> None:
        """Remove registry by name from the name input field."""
        try:
            name = self.query_one("#reg-name-input", Input).value.strip()
        except NoMatches:
            return
        if not name:
            self.notify("Enter the registry name to remove", severity="warning")
            return
        from argus_mcp.tui.settings import load_settings, save_settings

        settings = load_settings()
        registries = settings.get("registries", [])
        original_len = len(registries)
        registries = [r for r in registries if r.get("name") != name]
        if len(registries) == original_len:
            self.notify(f"No registry named '{name}'", severity="warning")
            return
        settings["registries"] = registries
        save_settings(settings)
        self.notify(f"Removed registry '{name}'", title="Registry Removed")
        self.refresh_registries()
