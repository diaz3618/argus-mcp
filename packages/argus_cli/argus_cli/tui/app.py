"""Argus MCP Textual TUI application.

Polls the management API of one or more running Argus servers over
HTTP via :class:`ServerManager`.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from typing import TYPE_CHECKING, Any

from argus_mcp.constants import (
    SERVER_NAME,
    SERVER_VERSION,
)
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Footer, Header

from argus_cli.tui._error_utils import safe_query
from argus_cli.tui.api_client import ApiClientError
from argus_cli.tui.commands import NavigationProvider, ThemeProvider
from argus_cli.tui.events import (
    CapabilitiesReady,
    ConfigSyncUpdate,
    ConnectionLost,
    ConnectionRestored,
    ReAuthRequired,
)
from argus_cli.tui.screens.audit_log import AuditLogScreen
from argus_cli.tui.screens.catalog_browser import CatalogBrowserScreen
from argus_cli.tui.screens.containers import ContainersScreen
from argus_cli.tui.screens.dashboard import DashboardScreen
from argus_cli.tui.screens.export_import import ExportImportScreen
from argus_cli.tui.screens.health import HealthScreen
from argus_cli.tui.screens.kubernetes import KubernetesScreen
from argus_cli.tui.screens.operations import OperationsScreen
from argus_cli.tui.screens.registry import RegistryScreen
from argus_cli.tui.screens.security import SecurityScreen
from argus_cli.tui.screens.server_logs import ServerLogsScreen
from argus_cli.tui.screens.settings import SettingsScreen
from argus_cli.tui.screens.setup_wizard import SetupWizardScreen
from argus_cli.tui.screens.skills import SkillsScreen
from argus_cli.tui.screens.tool_editor import ToolEditorScreen
from argus_cli.tui.screens.tools import ToolsScreen
from argus_cli.tui.widgets.backend_status import BackendStatusWidget
from argus_cli.tui.widgets.capability_tables import CapabilitySection
from argus_cli.tui.widgets.event_log import EventLogWidget
from argus_cli.tui.widgets.jump_overlay import Jumper, JumpOverlay
from argus_cli.tui.widgets.server_info import ServerInfoWidget
from argus_cli.tui.widgets.server_selector import ServerSelected, ServerSelectorWidget
from argus_cli.tui.widgets.tplot import UptimeChart

if TYPE_CHECKING:
    from collections.abc import Iterable

    from textual.screen import Screen

    from argus_cli.tui.server_manager import ServerManager

logger = logging.getLogger(__name__)

# Polling interval for status updates (seconds).
_POLL_BASE = 2.0
_POLL_MAX = 8.0

# Maximum number of event IDs to remember (LRU eviction).
_SEEN_EVENTS_MAX = 10_000

# Transport path suffixes that users might accidentally include in the
# ``--server`` URL.  We strip these so the management API client always
# targets the server root.
_TRANSPORT_SUFFIXES = ("/mcp", "/sse", "/messages/", "/messages")


def _normalise_server_url(url: str | None) -> str | None:
    """Strip transport-path suffixes from a server URL.

    Users may pass ``http://host:port/mcp`` as the ``--server`` URL, but
    the management API is mounted at ``/manage/v1`` on the server root.
    """
    if url is None:
        return None
    url = url.rstrip("/")
    for suffix in _TRANSPORT_SUFFIXES:
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            break
    return url or None


class ArgusApp(App):
    """Textual TUI for the Argus MCP server."""

    TITLE = f"{SERVER_NAME} v{SERVER_VERSION}"
    SUB_TITLE = ""
    CSS_PATH = "argus.tcss"

    COMMANDS = App.COMMANDS | {ThemeProvider, NavigationProvider}

    BINDINGS = [
        Binding("q", "quit", "Quit", priority=True),
        Binding("1", "switch_mode('dashboard')", "Dash", key_display="1"),
        Binding("d", "switch_mode('dashboard')", "Dash", show=False),
        Binding("2", "switch_mode('tools')", "Tools", key_display="2"),
        Binding("3", "switch_mode('registry')", "Reg", key_display="3"),
        Binding("4", "switch_mode('settings')", "Set", key_display="4"),
        Binding("s", "switch_mode('settings')", "Set", show=False),
        Binding("5", "switch_mode('skills')", "Skills", key_display="5"),
        Binding("6", "switch_mode('editor')", "Edit", key_display="6"),
        Binding("7", "switch_mode('audit')", "Audit", key_display="7"),
        Binding("8", "switch_mode('health')", "Health", key_display="8"),
        Binding("h", "switch_mode('health')", "Health", show=False),
        Binding("9", "switch_mode('security')", "Sec", key_display="9"),
        Binding("0", "switch_mode('operations')", "Ops", key_display="0"),
        Binding("o", "switch_mode('operations')", "Ops", show=False),
        Binding("c", "switch_mode('containers')", "Containers", show=False),
        Binding("k", "switch_mode('kubernetes')", "Kubernetes", show=False),
        Binding("w", "switch_mode('wizard')", "Wizard", show=False),
        Binding("x", "export_client_config", "Export Config", show=False),
        Binding("t", "show_tools", "Tools Tab", show=False),
        Binding("r", "show_resources", "Resources Tab", show=False),
        Binding("p", "show_prompts", "Prompts Tab", show=False),
        Binding("n", "next_theme", "Next Theme", show=False),
        Binding("T", "open_theme_picker", "Themes", key_display="shift+t", show=False),
        Binding("semicolon", "jump_mode", "Jump", show=False),
    ]

    MODES = {
        "dashboard": DashboardScreen,
        "tools": ToolsScreen,
        "registry": RegistryScreen,
        "settings": SettingsScreen,
        "skills": SkillsScreen,
        "editor": ToolEditorScreen,
        "audit": AuditLogScreen,
        "health": HealthScreen,
        "security": SecurityScreen,
        "operations": OperationsScreen,
        "wizard": SetupWizardScreen,
        "server_logs": ServerLogsScreen,
        "export_import": ExportImportScreen,
        "catalog": CatalogBrowserScreen,
        "containers": ContainersScreen,
        "kubernetes": KubernetesScreen,
    }

    DEFAULT_MODE = "dashboard"

    def __init__(
        self,
        server_url: str | None = None,
        token: str | None = None,
        *,
        server_manager: object | None = None,
    ) -> None:
        super().__init__()

        # Remote mode parameters — normalise the URL so that the
        # management API client uses the server root, not an MCP
        # sub-path like /mcp or /sse.
        self._server_url = _normalise_server_url(server_url)
        self._token = token

        # Server manager — always used for connection management
        self._server_manager: object | None = server_manager  # ServerManager

        # Polling state
        self._connected = False
        self._caps_loaded = False
        self._seen_event_ids: OrderedDict[str, None] = OrderedDict()
        self._poll_timer: object | None = None
        self._sse_worker: object | None = None
        self._poll_interval: float = _POLL_BASE
        self._last_status_hash: int = 0

        # Cached data for cross-screen access
        self._last_status: Any | None = None
        self._last_caps: Any | None = None
        self._last_sessions: Any | None = None
        self._last_groups: Any | None = None

    @property
    def server_manager(self) -> object | None:
        return self._server_manager

    @property
    def last_status(self) -> Any | None:
        return self._last_status

    @property
    def last_caps(self) -> Any | None:
        return self._last_caps

    @property
    def last_sessions(self) -> Any | None:
        return self._last_sessions

    @property
    def last_groups(self) -> Any | None:
        return self._last_groups

    @property
    def last_events(self) -> list | None:
        return getattr(self, "_last_events", None)

    def _record_event_id(self, event_id: str) -> None:
        """Remember an event ID with bounded LRU eviction."""
        self._seen_event_ids[event_id] = None
        while len(self._seen_event_ids) > _SEEN_EVENTS_MAX:
            self._seen_event_ids.popitem(last=False)

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Footer()

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        """Extend the command palette with Argus MCP commands."""
        yield from super().get_system_commands(screen)

        yield SystemCommand(
            title="Dashboard Mode",
            help="Server info, backends, events, and capabilities (1/d)",
            callback=lambda: self.switch_mode("dashboard"),
        )
        yield SystemCommand(
            title="Tools Mode",
            help="Full-screen capability explorer with filtering (2)",
            callback=lambda: self.switch_mode("tools"),
        )
        yield SystemCommand(
            title="Registry Mode",
            help="Server browser and discovery (3)",
            callback=lambda: self.switch_mode("registry"),
        )
        yield SystemCommand(
            title="Settings Mode",
            help="Theme, config viewer, and preferences (4/s)",
            callback=lambda: self.switch_mode("settings"),
        )
        yield SystemCommand(
            title="Skills Mode",
            help="Manage installed skill presets (5)",
            callback=lambda: self.switch_mode("skills"),
        )
        yield SystemCommand(
            title="Tool Editor Mode",
            help="Rename, filter, and customize tools (6)",
            callback=lambda: self.switch_mode("editor"),
        )
        yield SystemCommand(
            title="Audit Log Mode",
            help="Structured event log with filters and export (7)",
            callback=lambda: self.switch_mode("audit"),
        )
        yield SystemCommand(
            title="Health Mode",
            help="Backend health, sessions, and version drift (8/h)",
            callback=lambda: self.switch_mode("health"),
        )
        yield SystemCommand(
            title="Security Mode",
            help="Auth, authorization, secrets, and network (9)",
            callback=lambda: self.switch_mode("security"),
        )
        yield SystemCommand(
            title="Operations Mode",
            help="Workflows, optimizer, and telemetry (0/o)",
            callback=lambda: self.switch_mode("operations"),
        )
        yield SystemCommand(
            title="Setup Wizard",
            help="Config editor with import/export, backend templates (w)",
            callback=lambda: self.switch_mode("wizard"),
        )
        yield SystemCommand(
            title="Server Logs",
            help="Per-server operational logs with filtering",
            callback=lambda: self.switch_mode("server_logs"),
        )
        yield SystemCommand(
            title="Export / Import",
            help="Export and import config with dry-run preview",
            callback=lambda: self.switch_mode("export_import"),
        )
        yield SystemCommand(
            title="Catalog Browser",
            help="Onboard backends from YAML catalog definitions",
            callback=lambda: self.switch_mode("catalog"),
        )
        yield SystemCommand(
            title="Export Client Config",
            help="Generate config for VS Code, Cursor, Claude, etc.",
            callback=self.action_export_client_config,
        )

        yield SystemCommand(
            title="Show Server Details",
            help="Configuration file, log file, and log level",
            callback=self._show_server_details,
        )
        yield SystemCommand(
            title="Show Connection Info",
            help="SSE endpoint URL and backend status",
            callback=self._show_connection_info,
        )

        yield SystemCommand(
            title="Show Tools Tab",
            help="Switch capability tables to the Tools tab",
            callback=self.action_show_tools,
        )
        yield SystemCommand(
            title="Show Resources Tab",
            help="Switch capability tables to the Resources tab",
            callback=self.action_show_resources,
        )
        yield SystemCommand(
            title="Show Prompts Tab",
            help="Switch capability tables to the Prompts tab",
            callback=self.action_show_prompts,
        )

        yield SystemCommand(
            title="Open Theme Picker",
            help="Browse and preview all available themes",
            callback=self.action_open_theme_picker,
        )
        yield SystemCommand(
            title="Cycle Theme",
            help="Switch to the next enabled theme",
            callback=self.action_next_theme,
        )

        yield SystemCommand(
            title="Jump Mode",
            help="Spatial navigation overlay for quick widget focus (;)",
            callback=self.action_jump_mode,
        )

        yield SystemCommand(
            title="Reconnect All Backends",
            help="Re-establish connections to all configured backends",
            callback=self._reconnect_all_backends,
        )

    def _show_server_details(self) -> None:
        """Show server config details via notification."""
        try:
            srv = self.screen.query_one(ServerInfoWidget)
            lines = [
                f"[b]Config file:[/b]  {srv.config_file}",
                f"[b]Log file:[/b]    {srv.log_file}",
                f"[b]Log level:[/b]   {srv.log_level}",
            ]
            self.notify("\n".join(lines), title="Server Details", timeout=8)
        except NoMatches:
            self.notify("Switch to Dashboard to view server details.", timeout=4)

    def action__tb_server_details(self) -> None:
        """Toolbar action: show server details notification."""
        self._show_server_details()

    def _show_connection_info(self) -> None:
        """Show connection info via notification."""
        try:
            srv = self.screen.query_one(ServerInfoWidget)
            bk = self.screen.query_one(BackendStatusWidget)
            lines = [
                f"[b]SSE URL:[/b]    {srv.sse_url}",
                f"[b]Backends:[/b]   {bk.connected}/{bk.total} connected",
                f"[b]Status:[/b]     {srv.status_text}",
            ]
            self.notify("\n".join(lines), title="Connection Info", timeout=8)
        except NoMatches:
            self.notify("Switch to Dashboard to view connection info.", timeout=4)

    def on_mount(self) -> None:
        """Called after the TUI is fully mounted."""
        from argus_cli.tui.settings import load_settings

        settings = load_settings()
        saved_theme = settings.get("theme", "textual-dark")
        if saved_theme in self.available_themes:
            self.theme = saved_theme

        from argus_cli.theme import sync_with_textual_theme

        sync_with_textual_theme(self.theme or "textual-dark")

        self._ensure_server_manager()

        # DEFAULT_MODE already switches to dashboard; initialize
        # widgets after the mode screen is composed.
        self.set_timer(0.1, self._init_after_mode_switch)

    def _init_after_mode_switch(self) -> None:
        """Initialize dashboard widgets after mode switch completes.

        Safe to call multiple times — becomes a no-op after the first
        successful run.
        """
        if getattr(self, "_dashboard_init_done", False):
            return
        try:
            scr = self.screen
            info = scr.query_one(ServerInfoWidget)
            info.server_name = SERVER_NAME
            info.server_version = SERVER_VERSION

            event_log = scr.query_one(EventLogWidget)
            event_log.start_capture()

            self._start_remote_mode(info, event_log)
            self._dashboard_init_done = True
        except (NoMatches, AttributeError) as exc:
            logger.warning("Dashboard initialization deferred: %s", exc)

    def _ensure_server_manager(self) -> None:
        """Lazily create a :class:`ServerManager` if one wasn't injected."""
        if self._server_manager is not None:
            return

        from argus_cli.tui.server_manager import ServerManager

        if self._server_url:
            # Single-server mode via --server URL
            self._server_manager = ServerManager.from_single(
                url=self._server_url, token=self._token
            )
        else:
            # Load from servers.json
            self._server_manager = ServerManager.from_config()

    def _start_remote_mode(self, info: ServerInfoWidget, event_log: EventLogWidget) -> None:
        """Initialize remote-mode: connect to server(s) via HTTP."""

        mgr: ServerManager = self._server_manager  # type: ignore[assignment]

        if mgr.count == 0:
            # No servers configured — add a default
            from argus_mcp.constants import DEFAULT_HOST, DEFAULT_PORT

            default_url = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
            mgr.add("local", default_url, set_active=True)
            mgr.save()

        active = mgr.active_entry
        if active:
            info.sse_url = active.url
            info.status_text = "Connecting…"
            event_log.add_event(
                "Initialization",
                f"Connecting to server '{active.name}' at {active.url}…",
            )
        else:
            info.status_text = "No servers configured"

        self._refresh_server_selector()

        # Kick off the initial connection + polling
        self._start_polling()

    def on_unmount(self) -> None:
        """Clean up on app exit."""
        # Stop polling timer
        if self._poll_timer is not None:
            self._poll_timer.stop()

        # Stop SSE stream
        self._stop_sse_stream()

        # Close API clients via server manager.
        # During Textual shutdown the async event loop is being torn down,
        # so we use the synchronous fallback to close httpx transports.
        if self._server_manager is not None:
            from argus_cli.tui.server_manager import ServerManager

            if isinstance(self._server_manager, ServerManager):
                self._server_manager.close_all_sync()

        # Stop capturing print() — guard against empty screen stack
        # during Textual shutdown.
        try:
            screen = self.screen
        except Exception:
            return
        ew = safe_query(screen, "EventLogWidget", EventLogWidget)
        if ew is not None:
            ew.stop_capture()

    def _start_polling(self) -> None:
        """Begin the initial connection and periodic polling."""
        self._do_initial_connect()

    def _do_initial_connect(self) -> None:
        """Worker: establish the first connection to server(s)."""
        self.run_worker(self._initial_connect(), exclusive=True, name="initial-connect")

    async def _initial_connect(self) -> None:
        """Connect all servers via the manager and fetch initial state."""

        mgr: ServerManager = self._server_manager  # type: ignore[assignment]

        results = await mgr.connect_all()
        for name, err in results.items():
            if err is None:
                logger.info("Connected to server '%s'", name)
            else:
                logger.warning("Failed to connect to '%s': %s", name, err)

        # Update selector after connect attempts
        self._refresh_server_selector()

        # Fetch state from the active server
        client = mgr.active_client
        if client is not None:
            try:
                health = await client.get_health()
                logger.info("Initial health check: %s", health.status)
                self._connected = True
                self.post_message(ConnectionRestored())

                status = await client.get_status()
                self._apply_status_response(status)

                caps = await client.get_capabilities()
                self._apply_capabilities_response(caps)
                self._caps_loaded = True

                events = await client.get_events(limit=100)
                self._apply_events_response(events)
            except (OSError, ConnectionError, ApiClientError) as exc:
                logger.warning("Initial data fetch failed: %s", exc)
                self.post_message(ConnectionLost(reason=f"Cannot reach server: {exc}"))
        else:
            active = mgr.active_entry
            reason = "No servers configured"
            if active:
                err = results.get(active.name)
                reason = f"Cannot reach server '{active.name}': {err}"
            self.post_message(ConnectionLost(reason=reason))

        # Start periodic polling regardless — it will retry on failure
        self._poll_timer = self.set_interval(
            self._poll_interval, self._poll_tick, name="status-poll"
        )

        # Start SSE event stream if connected
        if self._connected:
            self._start_sse_stream()

    def _start_sse_stream(self) -> None:
        """Launch a background worker for the SSE event stream."""
        if self._sse_worker is not None:
            return  # Already running
        self._sse_worker = self.run_worker(
            self._sse_event_loop(), exclusive=False, name="sse-events"
        )

    def _stop_sse_stream(self) -> None:
        """Cancel the SSE background worker."""
        if self._sse_worker is not None:
            self._sse_worker.cancel()
            self._sse_worker = None

    async def _sse_event_loop(self) -> None:
        """Background worker: consume SSE events and feed EventLogWidget."""
        mgr: ServerManager = self._server_manager  # type: ignore[assignment]
        client = mgr.active_client
        if client is None:
            return

        try:
            async for event_data in client.stream_events():
                event_id = event_data.get("id", "")
                if event_id and event_id in self._seen_event_ids:
                    continue
                if event_id:
                    self._record_event_id(event_id)

                stage = event_data.get("stage", "event")
                message = event_data.get("message", "")
                details = event_data.get("details")
                timestamp = event_data.get("timestamp")

                extra: list[str] = []
                if details and isinstance(details, dict):
                    for k, v in details.items():
                        extra.append(f"{k}: {v}")

                try:
                    event_log = self.screen.query_one(EventLogWidget)
                    event_log.add_event(
                        stage,
                        message,
                        timestamp=timestamp,
                        extra_lines=extra if extra else None,
                    )
                except NoMatches:
                    pass

                # Bridge config_sync events
                if stage == "config_sync" and details:
                    d = details if isinstance(details, dict) else {}
                    self.post_message(
                        ConfigSyncUpdate(
                            config_file=d.get("config_file", ""),
                            config_hash=d.get("config_hash", ""),
                            sync_type=d.get("type", "changed"),
                            details=message,
                            timestamp=timestamp or "",
                        )
                    )
        except (OSError, ConnectionError, ApiClientError, asyncio.CancelledError):
            logger.debug("SSE event stream ended")
        finally:
            self._sse_worker = None

    def _poll_tick(self) -> None:
        """Timer callback: dispatch async poll worker."""
        self.run_worker(self._poll_once(), exclusive=True, name="poll")

    async def _poll_once(self) -> None:
        """Single poll cycle: fetch status + events from active server."""

        mgr: ServerManager = self._server_manager  # type: ignore[assignment]
        entry = mgr.active_entry
        if entry is None:
            return

        name = entry.name
        client = entry.client

        # Try to connect if not yet connected
        if client is None or not client.is_connected:
            try:
                await mgr.connect(name)
                client = mgr.active_client
            except (OSError, ConnectionError, ApiClientError):
                return

        if client is None:
            return

        try:
            batch = await client.get_batch(events_limit=20)

            self._apply_status_response(batch.status)

            # Compute a lightweight status hash for adaptive polling
            _status_hash = hash(
                (
                    batch.status.service.state,
                    batch.status.config.backend_count,
                    getattr(batch.status.service, "uptime", None),
                )
            )

            if not self._connected:
                self._connected = True
                self._caps_loaded = False
                mgr.mark_connected(name)
                self.post_message(ConnectionRestored())

            if not self._caps_loaded:
                self._apply_capabilities_response(batch.capabilities)
                self._caps_loaded = True

            self._apply_events_response(batch.events)
            self._apply_backends_response(batch.backends)

            # Sessions and groups are not in the batch — fetch in parallel
            sessions_result, groups_result = await asyncio.gather(
                client.get_sessions(),
                client.get_groups(),
                return_exceptions=True,
            )

            if not isinstance(sessions_result, BaseException):
                self._last_sessions = sessions_result

            if not isinstance(groups_result, BaseException):
                self._last_groups = groups_result

        except (OSError, ConnectionError, ApiClientError) as exc:
            was_connected = self._connected
            self._connected = False
            self._caps_loaded = False
            mgr.mark_disconnected(name)
            # Always notify on failure — not just when previously connected.
            self.post_message(ConnectionLost(reason=str(exc)))
            if not was_connected:
                logger.debug("Poll failed (still disconnected): %s", exc)
            # Reset to fast polling on errors so recovery is quick
            _status_hash = 0

        # Adaptive polling interval: back off when nothing changes
        changed = _status_hash != self._last_status_hash
        self._last_status_hash = _status_hash
        if changed:
            new_interval = _POLL_BASE
        else:
            new_interval = min(self._poll_interval * 2, _POLL_MAX)

        if new_interval != self._poll_interval:
            self._poll_interval = new_interval
            if self._poll_timer is not None:
                self._poll_timer.stop()  # type: ignore[union-attr]
            self._poll_timer = self.set_interval(
                self._poll_interval, self._poll_tick, name="status-poll"
            )

        # Refresh selector to reflect connection status changes
        self._refresh_server_selector()

    def _apply_status_response(self, status: Any) -> None:
        """Convert a StatusResponse into widget updates."""
        self._last_status = status
        try:
            srv_widget = self.screen.query_one(ServerInfoWidget)
            srv_widget.server_version = status.service.version or SERVER_VERSION
            srv_widget.sse_url = status.transport.sse_url or self._server_url or ""
            srv_widget.streamable_http_url = status.transport.streamable_http_url or ""
            if status.transport.streamable_http_url:
                srv_widget.transport_type = "streamable-http"
            srv_widget.status_text = status.service.state
            srv_widget.config_file = status.config.file_path or ""
        except NoMatches:
            pass  # Widget not in active screen

        try:
            backend = self.screen.query_one(BackendStatusWidget)
            backend.total = status.config.backend_count
            if status.service.state == "running":
                backend.connected = status.config.backend_count
            elif status.service.state == "error":
                backend.connected = 0
        except NoMatches:
            pass  # Widget not in active screen

    def _apply_backends_response(self, backends_resp: Any) -> None:
        """Feed phase-aware backend data into BackendStatusWidget."""
        try:
            backend_widget = self.screen.query_one(BackendStatusWidget)
            backend_widget.update_from_backends(backends_resp.backends)
        except NoMatches:
            pass  # Widget not in active screen

        # Feed uptime chart on dashboard
        try:
            uptime_chart = self.screen.query_one(UptimeChart)
            names = []
            uptimes = []
            for b in backends_resp.backends:
                names.append(getattr(b, "name", "?"))
                health = getattr(b, "health", None)
                if health is not None:
                    status = getattr(health, "status", "unknown")
                else:
                    status = "unknown"
                uptimes.append(
                    100.0 if status == "healthy" else 50.0 if status == "degraded" else 0.0
                )
            if names:
                uptime_chart.set_data(names, uptimes)
        except NoMatches:
            pass  # Widget not in active screen

    def _apply_capabilities_response(self, caps: Any) -> None:
        """Convert a CapabilitiesResponse into widget updates."""
        self._last_caps = caps

        route_map = caps.route_map

        try:
            cap_section = self.screen.query_one(CapabilitySection)
            cap_section.populate(caps.tools, caps.resources, caps.prompts, route_map)
        except NoMatches:
            pass  # Widget not in active screen

        try:
            event_log = self.screen.query_one(EventLogWidget)
            event_log.add_event(
                "✅ Service Ready",
                f"{len(caps.tools)} tools, {len(caps.resources)} resources, "
                f"{len(caps.prompts)} prompts loaded",
            )
        except NoMatches:
            pass  # Widget not in active screen

    def _apply_events_response(self, events_resp: Any) -> None:
        """Show new events in the EventLogWidget.

        Also detects ``config_sync`` stage events and posts a
        :class:`ConfigSyncUpdate` Textual message for :class:`SyncStatusWidget`.
        """
        self._last_events = events_resp  # Cache for audit log screen
        for ev in events_resp.events:
            if ev.id in self._seen_event_ids:
                continue
            self._record_event_id(ev.id)
            extra: list[str] = []
            if ev.details:
                for k, v in ev.details.items():
                    extra.append(f"{k}: {v}")
            try:
                event_log = self.screen.query_one(EventLogWidget)
                event_log.add_event(
                    ev.stage,
                    ev.message,
                    timestamp=ev.timestamp,
                    extra_lines=extra if extra else None,
                )
            except NoMatches:
                pass  # Widget not in active screen

            # Bridge config_sync events to SyncStatusWidget
            if ev.stage == "config_sync" and ev.details:
                details = ev.details if isinstance(ev.details, dict) else {}
                self.post_message(
                    ConfigSyncUpdate(
                        config_file=details.get("config_file", ""),
                        config_hash=details.get("config_hash", ""),
                        sync_type=details.get("type", "changed"),
                        details=ev.message,
                        timestamp=ev.timestamp,
                    )
                )

    def on_config_sync_update(self, event: ConfigSyncUpdate) -> None:
        """Handle a config sync event by updating the SyncStatusWidget."""
        from argus_cli.tui.widgets.sync_status import SyncStatusWidget

        try:
            widget = self.screen.query_one(SyncStatusWidget)
            widget.update_sync_status(
                config_file=event.config_file,
                config_hash=event.config_hash,
                last_sync=event.timestamp,
                is_live=event.sync_type != "error",
            )
            widget.add_sync_event(
                {
                    "time": event.timestamp,
                    "type": event.sync_type,
                    "details": event.details,
                }
            )
        except NoMatches:
            pass  # Widget not in active screen

    def _refresh_server_selector(self) -> None:
        """Update the ServerSelectorWidget with current server entries."""

        mgr: ServerManager | None = self._server_manager  # type: ignore[assignment]
        if mgr is None:
            return

        try:
            selector = self.screen.query_one("#srv-selector", ServerSelectorWidget)
        except NoMatches:
            return  # widget not mounted yet

        servers = [
            {
                "name": e.name,
                "url": e.url,
                "connected": e.connected,
            }
            for e in mgr.entries.values()
        ]
        selector.refresh_servers(servers, active_name=mgr.active_name)

    def on_server_selected(self, event: ServerSelected) -> None:
        """Handle the user switching to a different server."""

        mgr: ServerManager | None = self._server_manager  # type: ignore[assignment]
        if mgr is None:
            return

        name = event.server_name
        logger.info("Switching active server to '%s'", name)

        mgr.set_active(name)
        mgr.save()

        self._connected = False
        self._caps_loaded = False
        self._seen_event_ids.clear()
        self._stop_sse_stream()
        self._poll_interval = _POLL_BASE
        self._last_status_hash = 0

        entry = mgr.active_entry
        if entry:
            try:
                srv_widget = self.screen.query_one(ServerInfoWidget)
                srv_widget.sse_url = entry.url
                srv_widget.status_text = "Connecting\u2026" if not entry.connected else "Connected"
            except NoMatches:
                pass

            try:
                event_log = self.screen.query_one(EventLogWidget)
                event_log.add_event(
                    "Server Switch",
                    f"Switched to '{name}' ({entry.url})",
                )
            except NoMatches:
                pass

        # Force an immediate poll
        self.run_worker(self._poll_once(), exclusive=True, name="poll-switch")

        self._refresh_server_selector()

    def on_capabilities_ready(self, event: CapabilitiesReady) -> None:
        """Explicit capability population (alternative path)."""
        try:
            cap = self.screen.query_one(CapabilitySection)
        except NoMatches:
            return
        cap.populate(
            event.tools,
            event.resources,
            event.prompts,
            event.route_map,
        )

    def on_connection_lost(self, event: ConnectionLost) -> None:
        """Handle loss of HTTP connection to the remote server."""
        self._stop_sse_stream()
        try:
            srv_widget = self.screen.query_one(ServerInfoWidget)
            srv_widget.status_text = "Disconnected"
        except NoMatches:
            pass  # Widget not in active screen

        try:
            event_log = self.screen.query_one(EventLogWidget)
            event_log.add_event(
                "⚠️  Connection Lost",
                event.reason,
            )
        except NoMatches:
            pass  # Widget not in active screen
        self.notify(
            f"Connection lost: {event.reason}",
            title="Disconnected",
            severity="warning",
            timeout=5,
        )

    def on_connection_restored(self, event: ConnectionRestored) -> None:
        """Handle reconnection to the remote server."""
        try:
            srv_widget = self.screen.query_one(ServerInfoWidget)
            srv_widget.status_text = "Connected"
        except NoMatches:
            pass  # Widget not in active screen

        try:
            event_log = self.screen.query_one(EventLogWidget)
            event_log.add_event(
                "✅ Reconnected",
                "Connection to server restored.",
            )
        except NoMatches:
            pass  # Widget not in active screen

        # Restart SSE event stream on reconnection
        self._start_sse_stream()

    def on_backend_status_widget_backend_selected(
        self, event: BackendStatusWidget.BackendSelected
    ) -> None:
        """Open the backend detail modal when a backend row is selected."""

        def _handle_result(result: str | None) -> None:
            if result is None:
                return
            backend_name = event.backend.get("name", "")
            if result == "restart":
                self.run_worker(
                    self._reconnect_backend(backend_name),
                    name="backend-restart",
                    exclusive=True,
                )
            elif result == "disconnect":
                self.notify(
                    f"Disconnect '{backend_name}' — use Reconnect to cycle the connection",
                    title="Disconnect",
                    severity="information",
                    timeout=4,
                )

        from argus_cli.tui.screens.backend_detail import BackendDetailModal

        self.push_screen(BackendDetailModal(event.backend), callback=_handle_result)

    async def _reconnect_backend(self, name: str) -> None:
        """Ask the management API to reconnect a specific backend."""
        mgr = self._server_manager
        if mgr is None:
            return
        client = getattr(mgr, "active_client", None)
        if client is None:
            return
        try:
            await client.post_reconnect(name)
            self.notify(f"Reconnect '{name}' requested", title="Backend", severity="information")
            try:
                event_log = self.screen.query_one(EventLogWidget)
                event_log.add_event("🔄 Reconnect", f"Requested reconnect for '{name}'")
            except NoMatches:
                pass
        except (OSError, ConnectionError, ApiClientError) as exc:
            self.notify(f"Reconnect failed: {exc}", title="Error", severity="error")

    def _reconnect_all_backends(self) -> None:
        """Reconnect all configured backends via the management API."""
        self.run_worker(self._do_reconnect_all(), name="reconnect-all", exclusive=True)

    async def _do_reconnect_all(self) -> None:
        """Worker: reconnect every backend."""
        mgr = self._server_manager
        if mgr is None:
            return
        client = getattr(mgr, "active_client", None)
        if client is None:
            self.notify("No active server connection", severity="warning")
            return
        entries = getattr(mgr, "entries", {})
        for name in entries:
            try:
                await client.post_reconnect(name)
            except (OSError, ConnectionError, ApiClientError):
                pass
        self.notify(
            f"Reconnect requested for {len(entries)} backend(s)",
            title="Reconnect All",
            timeout=4,
        )

    def on_re_auth_required(self, event: ReAuthRequired) -> None:
        """Handle a backend requiring interactive re-authentication."""
        try:
            event_log = self.screen.query_one(EventLogWidget)
            event_log.add_event(
                "🔑 Re-auth Required",
                f"Backend '{event.backend_name}' needs re-authentication.",
            )
        except NoMatches:
            pass
        self.notify(
            f"Backend '{event.backend_name}' requires re-authentication. "
            "Use the management API /reauth endpoint to trigger it.",
            title="Re-auth Required",
            severity="warning",
            timeout=8,
        )

    async def _trigger_reauth(self, name: str) -> None:
        """Ask the management API to trigger re-auth for a specific backend."""
        mgr = self._server_manager
        if mgr is None:
            return
        client = getattr(mgr, "active_client", None)
        if client is None:
            return
        try:
            await client.post_reauth(name)
            self.notify(
                f"Re-auth for '{name}' initiated",
                title="Re-auth",
                severity="information",
            )
        except (OSError, ConnectionError, ApiClientError) as exc:
            self.notify(f"Re-auth failed: {exc}", title="Error", severity="error")

    def action_show_tools(self) -> None:
        """Switch capability table to Tools tab."""
        try:
            from textual.widgets import TabbedContent

            tabs = self.screen.query_one("#cap-tabs", TabbedContent)
            tabs.active = "tab-tools"
        except NoMatches:
            logger.debug("Could not switch to tools tab", exc_info=True)

    def action_show_resources(self) -> None:
        """Switch capability table to Resources tab."""
        try:
            from textual.widgets import TabbedContent

            tabs = self.screen.query_one("#cap-tabs", TabbedContent)
            tabs.active = "tab-resources"
        except NoMatches:
            logger.debug("Could not switch to resources tab", exc_info=True)

    def action_show_prompts(self) -> None:
        """Switch capability table to Prompts tab."""
        try:
            from textual.widgets import TabbedContent

            tabs = self.screen.query_one("#cap-tabs", TabbedContent)
            tabs.active = "tab-prompts"
        except NoMatches:
            logger.debug("Could not switch to prompts tab", exc_info=True)

    def action_quit(self) -> None:
        """Gracefully exit the TUI via the exit modal."""
        # Count running backends for the pre-flight message
        backends_running = 0
        try:
            mgr = self._server_manager
            if mgr is not None:
                backends_running = sum(1 for e in mgr.entries.values() if e.connected)
        except (AttributeError, TypeError):
            pass

        def _on_exit_choice(result: str | None) -> None:
            if result is None:
                return  # Cancelled
            try:
                event_log = self.screen.query_one(EventLogWidget)
                event_log.add_event("🛑 Shutting Down", f"Exit mode: {result}")
            except NoMatches:
                pass

            if result == "stop-and-exit":
                # Request server shutdown before exiting
                self.run_worker(self._shutdown_then_exit(), name="shutdown-exit")
            else:
                # save-and-exit: just save settings and exit
                from argus_cli.tui.settings import load_settings, save_settings

                settings = load_settings()
                settings["theme"] = self.theme or "textual-dark"
                save_settings(settings)
                self.exit()

        from argus_cli.tui.screens.exit_modal import ExitModal

        self.push_screen(
            ExitModal(running_count=backends_running),
            callback=_on_exit_choice,
        )

    async def _shutdown_then_exit(self) -> None:
        """Request server shutdown and then exit the TUI."""
        mgr = self._server_manager
        if mgr is not None:
            client = getattr(mgr, "active_client", None)
            if client is not None:
                try:
                    await client.post_shutdown()
                except (OSError, ConnectionError, ApiClientError) as exc:
                    logger.warning("Shutdown request failed: %s", exc)
        from argus_cli.tui.settings import load_settings, save_settings

        settings = load_settings()
        settings["theme"] = self.theme or "textual-dark"
        save_settings(settings)
        self.exit()

    def action_next_theme(self) -> None:
        """Cycle to the next enabled theme and persist the choice."""
        from argus_cli.tui.settings import load_settings, save_settings

        settings = load_settings()
        enabled = settings.get("enabled_themes", ["textual-dark"])
        # Filter to themes actually registered
        enabled = [t for t in enabled if t in self.available_themes]
        if not enabled:
            enabled = ["textual-dark"]

        current = self.theme or "textual-dark"
        try:
            idx = enabled.index(current)
            next_theme = enabled[(idx + 1) % len(enabled)]
        except ValueError:
            next_theme = enabled[0]

        self.theme = next_theme
        settings["theme"] = next_theme
        save_settings(settings)

        from argus_cli.theme import sync_with_textual_theme

        sync_with_textual_theme(next_theme)

        self.notify(f"Theme: {next_theme}", timeout=2)

    def action_open_theme_picker(self) -> None:
        """Open the modal theme picker screen."""

        def _on_theme_selected(theme_name: str | None) -> None:
            if theme_name is not None:
                from argus_cli.tui.settings import load_settings, save_settings

                settings = load_settings()
                settings["theme"] = theme_name
                save_settings(settings)

                from argus_cli.theme import sync_with_textual_theme

                sync_with_textual_theme(theme_name)

                self.notify(f"Theme: {theme_name}", timeout=2)

        from argus_cli.tui.screens.theme_picker import ThemeScreen

        self.push_screen(ThemeScreen(), _on_theme_selected)

    def action_export_client_config(self) -> None:
        """Open the client configuration export modal."""
        # Determine the server URL for the snippet
        sse_url = self._server_url or ""
        status = self.last_status
        if status is not None:
            url = getattr(status.transport, "sse_url", None)
            if url:
                sse_url = url
        if not sse_url:
            from argus_mcp.constants import DEFAULT_HOST, DEFAULT_PORT

            sse_url = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
        from argus_cli.tui.screens.client_config import ClientConfigModal

        self.push_screen(ClientConfigModal(server_url=sse_url))

    def action_jump_mode(self) -> None:
        """Open the jump-mode overlay for the active screen."""
        screen = self.screen
        targets = getattr(screen, "JUMP_TARGETS", None)
        if not targets:
            return
        jumper = Jumper(targets, screen)

        def _on_jump_result(result: str | Widget | None) -> None:
            if result is None:
                return
            if isinstance(result, Widget):
                result.focus()
            elif isinstance(result, str):
                try:
                    widget = screen.query_one(f"#{result}")
                    widget.focus()
                except NoMatches:
                    logger.debug("Jump target #%s not found", result)

        self.push_screen(JumpOverlay(jumper), _on_jump_result)
