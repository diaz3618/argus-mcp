"""Settings mode — configuration, server management, and preferences.

Provides:
- General: Log level, polling interval, feature flags
- Servers: Add/edit/remove server connections
- Theme: Current theme + picker + cycle
- Config: Read-only JSON view of active server config
- About: Version, links, server info
"""

from __future__ import annotations

import contextlib
import json as _json
import logging
from typing import TYPE_CHECKING, Any

from argus_mcp.constants import SERVER_NAME, SERVER_VERSION
from textual import on
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

from argus_cli.tui.screens.base import ArgusScreen
from argus_cli.tui.widgets.registry_panel import RegistryManagerPanel
from argus_cli.tui.widgets.server_connections_panel import ServerConnectionsPanel

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class SettingsScreen(ArgusScreen):
    """Settings mode — application configuration, servers, themes, and info.

    Uses tabbed layout with sections for General settings, Server
    management, Theme preferences, Config viewer, and About info.
    """

    JUMP_TARGETS = {
        "settings-tabs": "t",
    }

    def compose_content(self) -> ComposeResult:
        with TabbedContent(id="settings-tabs"):
            with TabPane("General", id="tab-general"), Vertical(id="general-section"):
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
                yield ServerConnectionsPanel(id="server-connections-widget")

            with TabPane("Theme", id="tab-theme"), Vertical(id="theme-section-content"):
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

            with TabPane("Config", id="tab-config"), Vertical(id="config-section"):
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
                from argus_cli.tui.widgets.middleware_panel import MiddlewarePipelineWidget

                yield MiddlewarePipelineWidget(id="mw-pipeline-widget")

            with TabPane("Registries", id="tab-registries"):
                yield RegistryManagerPanel(id="registry-manager-widget")

            with TabPane("About", id="tab-about"), Vertical(id="about-section"):
                yield Static(
                    f"[b]{SERVER_NAME}[/b] v{SERVER_VERSION}",
                    id="about-title",
                )
                yield Static("", id="about-details")

    def on_show(self) -> None:
        """Refresh all settings panels from current app state."""
        self._refresh_general()
        self._refresh_theme()
        self._refresh_config()
        self._refresh_about()
        self._refresh_middleware()

    def on_screen_resume(self) -> None:
        """Refresh theme display when returning from modal (e.g. theme picker)."""
        self._refresh_theme()

    def _refresh_general(self) -> None:
        """Populate the General tab from current state."""
        app = self.app
        status = app.last_status
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

    def _refresh_theme(self) -> None:
        """Show the current theme name."""
        theme = getattr(self.app, "theme", "textual-dark") or "textual-dark"
        self._set_text("#current-theme-display", f"[b]{theme}[/b]")

    def _refresh_config(self) -> None:
        """Load config preview from server status or manager."""
        app = self.app
        status = app.last_status

        # Config file path
        if status is not None:
            config_path = getattr(status.config, "file_path", None)
            if config_path:
                self._set_text("#config-path-display", config_path)

        # Build config JSON
        try:
            viewer = self.query_one("#config-viewer", TextArea)

            mgr = app.server_manager
            if mgr is not None:
                entries = mgr.entries
                data: dict[str, Any] = {"servers": {}}
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
        status = app.last_status
        mgr = app.server_manager

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

        caps = app.last_caps
        if caps is not None:
            lines.append(
                f"  Capabilities: {len(caps.tools)} tools, "
                f"{len(caps.resources)} resources, "
                f"{len(caps.prompts)} prompts"
            )

        self._set_text("#about-details", "\n".join(lines))

    def _refresh_middleware(self) -> None:
        """Update middleware pipeline based on feature flags."""
        from argus_cli.tui.widgets.middleware_panel import (
            _DEFAULT_LAYERS,
            MiddlewarePipelineWidget,
        )

        try:
            mw_widget = self.query_one(MiddlewarePipelineWidget)
        except NoMatches:
            return

        status = self.app.last_status
        if status is None:
            return

        ff = getattr(status, "feature_flags", {}) or {}

        # Build layers reflecting actual feature-flag state
        flag_map = {
            "Authentication": ff.get("outgoing_auth", True),
            "Telemetry": ff.get("otel", False),
            "Tool Call Filter": ff.get("optimizer", False),
        }

        layers = []
        for layer in _DEFAULT_LAYERS:
            entry = dict(layer)
            name = entry["name"]
            if name in flag_map:
                entry["status"] = "enabled" if flag_map[name] else "disabled"
            layers.append(entry)

        mw_widget.update_pipeline(layers)

    def _set_text(self, selector: str, text: str) -> None:
        """Safely update a Static widget's content."""
        with contextlib.suppress(NoMatches):
            self.query_one(selector, Static).update(text)

    @on(Button.Pressed, "#btn-theme-picker")
    def _handle_theme_picker(self, event: Button.Pressed) -> None:
        self.app.action_open_theme_picker()

    @on(Button.Pressed, "#btn-next-theme")
    def _handle_next_theme(self, event: Button.Pressed) -> None:
        self.app.action_next_theme()
        self._refresh_theme()

    @on(Button.Pressed, "#btn-reload-config")
    def _handle_reload_config(self, event: Button.Pressed) -> None:
        self._do_reload_config()

    @on(Button.Pressed, "#btn-reconnect-all")
    def _handle_reconnect_all(self, event: Button.Pressed) -> None:
        self._do_reconnect_all()

    @on(Button.Pressed, "#btn-config-edit-toggle")
    def _handle_config_edit_toggle(self, event: Button.Pressed) -> None:
        self._do_toggle_config_edit()

    @on(Button.Pressed, "#btn-config-validate")
    def _handle_config_validate(self, event: Button.Pressed) -> None:
        self._do_validate_config()

    @on(Button.Pressed, "#btn-config-save")
    def _handle_config_save(self, event: Button.Pressed) -> None:
        self._do_save_config()

    def _do_reload_config(self) -> None:
        """Trigger a config reload on the active server."""
        mgr = self.app.server_manager
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
        mgr = self.app.server_manager
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
                with contextlib.suppress(NoMatches):
                    self.query_one(ServerConnectionsPanel).refresh_servers()
            except (OSError, ConnectionError) as exc:
                self.notify(f"Reconnect failed: {exc}", severity="error")

        self.app.run_worker(_reconnect(), exclusive=True, name="reconnect-all")

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
        """Inform user that remote config writing is not supported.

        The management API provides read-only config access and a reload
        endpoint but does not accept config writes.  Config changes must
        be made on the server's filesystem and then reloaded via
        POST /manage/v1/reload.
        """
        self.notify(
            "Remote config save is not supported. "
            "Edit the config file on the server and use Reload.",
            severity="information",
            title="Config",
            timeout=5,
        )
