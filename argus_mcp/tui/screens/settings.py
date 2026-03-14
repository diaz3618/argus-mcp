"""Settings mode — comprehensive configuration, server management, and preferences.

Provides:
- General: Log level, polling interval, feature flags
- Servers: Add/edit/remove server connections
- Theme: Current theme + picker + cycle
- Config: Read-only JSON view of active server config
- About: Version, links, server info
"""

from __future__ import annotations

import json as _json
import logging
from typing import Any, Dict

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import (
    Button,
    Input,
    Label,
    Select,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)

from argus_mcp.constants import SERVER_NAME, SERVER_VERSION
from argus_mcp.tui.screens.base import ArgusScreen

# Lazy-import heavy widget panels only when needed (avoids circular imports)
_PANEL_IMPORTS_DONE = False


def _ensure_panel_imports() -> None:
    """Import widget panels on first use to avoid heavy startup cost."""
    global _PANEL_IMPORTS_DONE
    if _PANEL_IMPORTS_DONE:
        return
    _PANEL_IMPORTS_DONE = True
    # Imports are done at call-site in compose_content for tab panes.


logger = logging.getLogger(__name__)


class SettingsScreen(ArgusScreen):
    """Settings mode — application configuration, servers, themes, and info.

    Uses tabbed layout with sections for General settings, Server
    management, Theme preferences, Config viewer, and About info.
    """

    def compose_content(self) -> ComposeResult:
        with TabbedContent(id="settings-tabs"):
            with TabPane("General", id="tab-general"):
                with Vertical(id="general-section"):
                    yield Static("[b]General Settings[/b]", id="general-title")

                    with Horizontal(classes="setting-row"):
                        yield Label("Log Level:", classes="setting-label")
                        yield Select(
                            [
                                ("DEBUG", "DEBUG"),
                                ("INFO", "INFO"),
                                ("WARNING", "WARNING"),
                                ("ERROR", "ERROR"),
                            ],
                            value="INFO",
                            id="log-level-select",
                            allow_blank=False,
                        )

                    with Horizontal(classes="setting-row"):
                        yield Label("Poll Interval (s):", classes="setting-label")
                        yield Input(
                            placeholder="2.0",
                            id="poll-interval-input",
                            type="number",
                        )

                    yield Static("[b]Feature Flags[/b]", id="flags-title")
                    yield Static("No feature flags reported.", id="flags-display")

                    yield Static("[b]Conflict Resolution[/b]", id="conflict-title")
                    with Horizontal(classes="setting-row"):
                        yield Label("Strategy:", classes="setting-label")
                        yield Select(
                            [
                                ("first-wins", "first-wins"),
                                ("prefix", "prefix"),
                                ("priority", "priority"),
                                ("error", "error"),
                            ],
                            value="first-wins",
                            id="conflict-strategy-select",
                            allow_blank=False,
                        )
                    with Horizontal(classes="setting-row"):
                        yield Label("Separator:", classes="setting-label")
                        yield Input(
                            value="_",
                            id="conflict-separator-input",
                            placeholder="Separator for prefix strategy",
                        )
                    yield Static(
                        "[dim]Priority order is configured in the YAML config file.[/dim]",
                        id="conflict-priority-hint",
                    )

                    with Horizontal(classes="setting-row"):
                        yield Button(
                            "Reload Config",
                            id="btn-reload-config",
                            variant="primary",
                        )
                        yield Button(
                            "Reconnect All",
                            id="btn-reconnect-all",
                            variant="default",
                        )

            with TabPane("Servers", id="tab-servers"):
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

            with TabPane("Theme", id="tab-theme"):
                with Vertical(id="theme-section-content"):
                    yield Static("[b]Appearance[/b]", id="theme-title")

                    with Horizontal(classes="setting-row"):
                        yield Label("Current Theme:", classes="setting-label")
                        yield Static("", id="current-theme-display")

                    with Horizontal(classes="setting-row"):
                        yield Button(
                            "Open Theme Picker",
                            id="btn-theme-picker",
                            variant="primary",
                        )
                        yield Button(
                            "Next Theme",
                            id="btn-next-theme",
                            variant="default",
                        )

            with TabPane("Config", id="tab-config"):
                with Vertical(id="config-section"):
                    yield Static("[b]Active Configuration[/b]", id="config-title")
                    with Horizontal(classes="setting-row"):
                        yield Label("Config File:", classes="setting-label")
                        yield Static("—", id="config-path-display")
                    with Horizontal(classes="setting-row"):
                        yield Button(
                            "Edit",
                            id="btn-config-edit-toggle",
                            variant="primary",
                        )
                        yield Button(
                            "Validate",
                            id="btn-config-validate",
                            variant="default",
                        )
                        yield Button(
                            "Save",
                            id="btn-config-save",
                            variant="success",
                            disabled=True,
                        )
                    yield TextArea(
                        "",
                        id="config-viewer",
                        read_only=True,
                        language="json",
                    )
                    yield Static("", id="config-validation-result")

            with TabPane("Middleware", id="tab-middleware"):
                from argus_mcp.tui.widgets.middleware_panel import MiddlewarePipelineWidget

                yield MiddlewarePipelineWidget(id="mw-pipeline-widget")

            with TabPane("Registries", id="tab-registries"):
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

            with TabPane("About", id="tab-about"):
                with Vertical(id="about-section"):
                    yield Static(
                        f"[b]{SERVER_NAME}[/b] v{SERVER_VERSION}",
                        id="about-title",
                    )
                    yield Static("", id="about-details")

    def on_show(self) -> None:
        """Refresh all settings panels from current app state."""
        self._refresh_general()
        self._refresh_servers()
        self._refresh_theme()
        self._refresh_config()
        self._refresh_registries()
        self._refresh_about()

    def on_screen_resume(self) -> None:
        """Refresh theme display when returning from modal (e.g. theme picker)."""
        self._refresh_theme()

    def _refresh_general(self) -> None:
        """Populate the General tab from current state."""
        app = self.app
        status = getattr(app, "_last_status", None)
        if status is not None:
            # Feature flags
            flags = getattr(status, "feature_flags", {}) or {}
            if flags:
                lines = [f"  {k}: {'✓' if v else '✗'}" for k, v in flags.items()]
                self._set_text("#flags-display", "\n".join(lines))
            else:
                self._set_text("#flags-display", "No feature flags reported.")

            # Conflict resolution — read from server config if available
            config = getattr(status, "config", None)
            if config is not None:
                cr = getattr(config, "conflict_resolution", None)
                if cr is not None:
                    try:
                        strategy_val = getattr(cr, "strategy", "first-wins")
                        sep_val = getattr(cr, "separator", "_")
                        self.query_one("#conflict-strategy-select", Select).value = strategy_val
                        self.query_one("#conflict-separator-input", Input).value = sep_val
                    except NoMatches:
                        logger.debug("Could not refresh conflict settings", exc_info=True)

    def _refresh_servers(self) -> None:
        """Populate the Servers tab with current connections."""
        mgr = getattr(self.app, "_server_manager", None)
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

    def _refresh_theme(self) -> None:
        """Show the current theme name."""
        theme = getattr(self.app, "theme", "textual-dark") or "textual-dark"
        self._set_text("#current-theme-display", f"[b]{theme}[/b]")

    def _refresh_config(self) -> None:
        """Load config preview from server status or manager."""
        app = self.app
        status = getattr(app, "_last_status", None)

        # Config file path
        if status is not None:
            config_path = getattr(status.config, "file_path", None)
            if config_path:
                self._set_text("#config-path-display", config_path)

        # Build config JSON
        try:
            viewer = self.query_one("#config-viewer", TextArea)

            mgr = getattr(app, "_server_manager", None)
            if mgr is not None:
                entries = mgr.entries
                data: Dict[str, Any] = {"servers": {}}
                for name, entry in entries.items():
                    data["servers"][name] = {
                        "url": entry.url,
                        "connected": entry.connected,
                    }
                if status is not None:
                    data["service"] = {
                        "name": status.service.name,
                        "version": status.service.version,
                        "state": status.service.state,
                        "uptime_seconds": status.service.uptime_seconds,
                    }
                    data["transport"] = {
                        "sse_url": status.transport.sse_url,
                        "streamable_http_url": status.transport.streamable_http_url,
                        "host": status.transport.host,
                        "port": status.transport.port,
                    }
                    data["config"] = {
                        "file_path": status.config.file_path,
                        "loaded_at": status.config.loaded_at,
                        "backend_count": status.config.backend_count,
                    }
                    if status.feature_flags:
                        data["feature_flags"] = status.feature_flags
                viewer.load_text(_json.dumps(data, indent=2))
                return

            from argus_mcp.constants import DEFAULT_HOST, DEFAULT_PORT

            fallback = {
                "note": "Config viewer populated when connected to a server.",
                "default_host": DEFAULT_HOST,
                "default_port": DEFAULT_PORT,
            }
            viewer.load_text(_json.dumps(fallback, indent=2))
        except NoMatches:
            logger.debug("Could not load config preview", exc_info=True)

    def _refresh_about(self) -> None:
        """Populate the About section."""
        app = self.app
        status = getattr(app, "_last_status", None)
        mgr = getattr(app, "_server_manager", None)

        lines = [
            f"  Textual v{app.app_version if hasattr(app, 'app_version') else '—'}",
        ]
        if status is not None:
            lines.append(f"  Service state: {status.service.state}")
            if status.service.uptime_seconds:
                mins = int(status.service.uptime_seconds // 60)
                secs = int(status.service.uptime_seconds % 60)
                lines.append(f"  Uptime: {mins}m {secs}s")
            if status.config.backend_count:
                lines.append(f"  Backends: {status.config.backend_count}")
        if mgr is not None:
            lines.append(f"  Servers configured: {mgr.count}")
            if mgr.active_name:
                lines.append(f"  Active server: {mgr.active_name}")

        caps = getattr(app, "_last_caps", None)
        if caps is not None:
            lines.append(
                f"  Capabilities: {len(caps.tools)} tools, "
                f"{len(caps.resources)} resources, "
                f"{len(caps.prompts)} prompts"
            )

        self._set_text("#about-details", "\n".join(lines))

    def _set_text(self, selector: str, text: str) -> None:
        """Safely update a Static widget's content."""
        try:
            self.query_one(selector, Static).update(text)
        except NoMatches:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle all settings button clicks."""
        btn_id = event.button.id

        if btn_id == "btn-theme-picker":
            self.app.action_open_theme_picker()

        elif btn_id == "btn-next-theme":
            self.app.action_next_theme()
            self._refresh_theme()

        elif btn_id == "btn-reload-config":
            self._do_reload_config()

        elif btn_id == "btn-reconnect-all":
            self._do_reconnect_all()

        elif btn_id == "btn-add-server":
            self._do_add_server()

        elif btn_id == "btn-remove-server":
            self._do_remove_server()

        elif btn_id == "btn-config-edit-toggle":
            self._do_toggle_config_edit()

        elif btn_id == "btn-config-validate":
            self._do_validate_config()

        elif btn_id == "btn-config-save":
            self._do_save_config()

        elif btn_id == "btn-add-registry":
            self._do_add_registry()

        elif btn_id == "btn-remove-registry":
            self._do_remove_registry()

    def _do_reload_config(self) -> None:
        """Trigger a config reload on the active server."""
        mgr = getattr(self.app, "_server_manager", None)
        if mgr is None:
            self.notify("No server manager", severity="warning")
            return
        client = mgr.active_client
        if client is None:
            self.notify("Not connected to any server", severity="warning")
            return

        async def _reload() -> None:
            try:
                result = await client.post_reload()
                if result.reloaded:
                    added = ", ".join(result.backends_added) or "none"
                    removed = ", ".join(result.backends_removed) or "none"
                    self.notify(
                        f"Config reloaded  •  added: {added}  •  removed: {removed}",
                        title="Reload Complete",
                    )
                else:
                    errors = "; ".join(result.errors) if result.errors else "unknown"
                    self.notify(f"Reload failed: {errors}", severity="error")
            except (OSError, ConnectionError) as exc:
                self.notify(f"Reload failed: {exc}", severity="error")

        self.app.run_worker(_reload(), exclusive=True, name="config-reload")

    def _do_reconnect_all(self) -> None:
        """Reconnect all servers."""
        mgr = getattr(self.app, "_server_manager", None)
        if mgr is None:
            self.notify("No server manager", severity="warning")
            return

        async def _reconnect() -> None:
            try:
                results = await mgr.connect_all()
                ok = sum(1 for e in results.values() if e is None)
                fail = sum(1 for e in results.values() if e is not None)
                self.notify(
                    f"Reconnect: {ok} OK, {fail} failed",
                    title="Reconnect Complete",
                )
                self._refresh_servers()
            except (OSError, ConnectionError) as exc:
                self.notify(f"Reconnect failed: {exc}", severity="error")

        self.app.run_worker(_reconnect(), exclusive=True, name="reconnect-all")

    def _do_add_server(self) -> None:
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

        mgr = getattr(self.app, "_server_manager", None)
        if mgr is None:
            self.notify("No server manager available", severity="error")
            return

        mgr.add(name, url, token)
        mgr.save()
        self.notify(f"Added server '{name}' ({url})", title="Server Added")
        self._refresh_servers()

        # Clear inputs
        try:
            self.query_one("#server-name-input", Input).value = ""
            self.query_one("#server-url-input", Input).value = ""
            self.query_one("#server-token-input", Input).value = ""
        except NoMatches:
            pass

    def _do_remove_server(self) -> None:
        """Remove the server whose name is in the name input."""
        try:
            name = self.query_one("#server-name-input", Input).value.strip()
        except NoMatches:
            return

        if not name:
            self.notify("Enter the server name to remove", severity="warning")
            return

        mgr = getattr(self.app, "_server_manager", None)
        if mgr is None:
            self.notify("No server manager available", severity="error")
            return

        try:
            mgr.remove(name)
            mgr.save()
            self.notify(f"Removed server '{name}'", title="Server Removed")
            self._refresh_servers()
        except KeyError:
            self.notify(f"No server named '{name}'", severity="warning")

    def _do_toggle_config_edit(self) -> None:
        """Toggle config viewer between read-only and edit mode."""
        try:
            viewer = self.query_one("#config-viewer", TextArea)
            viewer.read_only = not viewer.read_only
            btn = self.query_one("#btn-config-edit-toggle", Button)
            save_btn = self.query_one("#btn-config-save", Button)
            if viewer.read_only:
                btn.label = "Edit"
                save_btn.disabled = True
            else:
                btn.label = "Lock"
                save_btn.disabled = False
            self._set_text(
                "#config-validation-result",
                "[dim]Editing enabled[/dim]" if not viewer.read_only else "",
            )
        except NoMatches:
            logger.debug("Could not toggle config edit", exc_info=True)

    def _do_validate_config(self) -> None:
        """Validate the current contents of the config editor."""
        try:
            viewer = self.query_one("#config-viewer", TextArea)
            text = viewer.text
            import json

            json.loads(text)
            self._set_text("#config-validation-result", "[green]✓ Valid JSON[/green]")
        except _json.JSONDecodeError as exc:
            self._set_text(
                "#config-validation-result",
                f"[red]✗ Invalid JSON: {exc}[/red]",
            )
        except NoMatches:
            self._set_text("#config-validation-result", "[yellow]Could not validate[/yellow]")

    def _do_save_config(self) -> None:
        """Save edited config back to disk (placeholder)."""
        self.notify(
            "Config save not yet connected to the server API.",
            severity="information",
            title="Config",
            timeout=4,
        )

    def _refresh_registries(self) -> None:
        """Populate the Registries tab."""
        try:
            viewer = self.query_one("#registries-viewer", TextArea)
            # Read from settings
            from argus_mcp.tui.settings import load_settings

            settings = load_settings()
            registries = settings.get("registries", [])
            if registries:
                viewer.load_text(_json.dumps(registries, indent=2))
            else:
                viewer.load_text(
                    _json.dumps(
                        [],
                        indent=2,
                    )
                )
        except NoMatches:
            logger.debug("Could not refresh registries", exc_info=True)

    def _do_add_registry(self) -> None:
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
        self._refresh_registries()

        # Clear inputs
        try:
            self.query_one("#reg-name-input", Input).value = ""
            self.query_one("#reg-url-input", Input).value = ""
            self.query_one("#reg-priority-input", Input).value = "100"
        except NoMatches:
            pass

    def _do_remove_registry(self) -> None:
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
        self._refresh_registries()
