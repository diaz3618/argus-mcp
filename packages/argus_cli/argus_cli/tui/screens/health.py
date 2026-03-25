"""Health mode — backend health, sessions, and version drift.

Aggregates monitoring widgets into a tabbed layout so the
Dashboard stays clean.  The Status tab also provides lifecycle
controls for individual backends and the whole server.
"""

from __future__ import annotations

import contextlib
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.widgets import TabbedContent, TabPane

from argus_cli.tui.api_client import ApiClientError
from argus_cli.tui.screens.base import ArgusScreen
from argus_cli.tui.widgets.filter_bar import FilterBar
from argus_cli.tui.widgets.health_panel import HealthPanel
from argus_cli.tui.widgets.server_groups import ServerGroupsWidget
from argus_cli.tui.widgets.sessions_panel import SessionsPanel
from argus_cli.tui.widgets.tplot import HealthTrendChart, LatencyChart
from argus_cli.tui.widgets.version_drift import VersionDriftPanel

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class HealthScreen(ArgusScreen):
    """Health monitoring mode — per-backend status, sessions, versions."""

    JUMP_TARGETS = {
        "health-tabs": "t",
        "health-panel-widget": "h",
        "sessions-panel-widget": "s",
        "version-drift-widget": "v",
        "server-groups-widget": "g",
        "health-latency-chart": "l",
        "health-trend-chart": "r",
    }

    BINDINGS = [
        ("slash", "focus_filter", "Filter"),
    ]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._health_filter_query: str = ""
        self._health_filter_enabled: bool = True
        self._cached_backends: list[dict] = []

    def compose_content(self) -> ComposeResult:
        with Vertical(id="health-layout"):
            yield FilterBar(
                placeholder="Filter backends: name or latency (e.g. >=100)…",
                label="Filter:",
                input_id="health-filter-input",
                id="health-filter-bar",
            )
            with TabbedContent(id="health-tabs"):
                with TabPane("Status", id="tab-health-status"):
                    yield HealthPanel(id="health-panel-widget")
                with TabPane("Sessions", id="tab-health-sessions"):
                    yield SessionsPanel(id="sessions-panel-widget")
                with TabPane("Versions", id="tab-health-versions"):
                    yield VersionDriftPanel(id="version-drift-widget")
                with TabPane("Server Groups", id="tab-health-groups"):
                    yield ServerGroupsWidget(id="server-groups-widget")
                with TabPane("Latency Chart", id="tab-health-latency"):
                    yield LatencyChart(id="health-latency-chart")
                with TabPane("Health Trends", id="tab-health-trends"):
                    yield HealthTrendChart(id="health-trend-chart")

    def on_filter_bar_filter_changed(self, event: FilterBar.FilterChanged) -> None:
        """Re-filter health table when the filter bar changes."""
        self._health_filter_query = event.query
        self._health_filter_enabled = event.enabled
        self._apply_health_filter()

    def _apply_health_filter(self) -> None:
        """Filter the health panel's DataTable rows."""
        if not self._cached_backends:
            return
        if not self._health_filter_enabled or not self._health_filter_query:
            with contextlib.suppress(NoMatches):
                self.query_one(HealthPanel).update_from_backends(self._cached_backends)
            return
        q = self._health_filter_query
        filtered = []
        for b in self._cached_backends:
            name = b.get("name", "")
            if FilterBar.matches_text(name, q):
                filtered.append(b)
                continue
            lat = (b.get("health") or {}).get("latency_ms")
            if lat is not None and FilterBar.matches_numeric(lat, q):
                filtered.append(b)
        with contextlib.suppress(NoMatches):
            self.query_one(HealthPanel).update_from_backends(filtered)

    def action_focus_filter(self) -> None:
        with contextlib.suppress(NoMatches):
            self.query_one("#health-filter-bar", FilterBar).focus_input()

    def on_show(self) -> None:
        """Refresh health data from cached app state."""
        self._refresh_from_app()

    def _refresh_from_app(self) -> None:
        """Pull latest backend data from the app cache into widgets."""
        app = self.app
        last_status = app.last_status
        if last_status is None:
            return

        # Feed backends into health panel + server groups
        mgr = app.server_manager
        if mgr is None:
            return
        client = getattr(mgr, "active_client", None)
        if client is None:
            return

        async def _fetch() -> None:
            try:
                backends_resp = await client.get_backends()
                details = [b.model_dump() for b in backends_resp.backends]
                self._cached_backends = details
                self._apply_health_filter()
                with contextlib.suppress(NoMatches):
                    self.query_one(ServerGroupsWidget).update_groups(details)

                # Feed version info into VersionDriftPanel
                version_servers = []
                for d in details:
                    version_servers.append(
                        {
                            "name": d.get("name", "?"),
                            "current_version": d.get("labels", {}).get("version", "—"),
                            "registry_version": "—",
                        }
                    )
                with contextlib.suppress(NoMatches):
                    self.query_one(VersionDriftPanel).update_versions(version_servers)

                # Feed latency chart with per-backend latency snapshot
                now_str = datetime.now(tz=timezone.utc).strftime("%H:%M:%S")
                backend_latencies: dict[str, float] = {}
                for d in details:
                    lat = (d.get("health") or {}).get("latency_ms")
                    if lat is not None:
                        name = d.get("name", "?")
                        backend_latencies[name] = float(lat)
                        # Also feed the single latency chart with average
                if backend_latencies:
                    avg_lat = sum(backend_latencies.values()) / len(backend_latencies)
                    with contextlib.suppress(NoMatches):
                        self.query_one(LatencyChart).add_point(now_str, avg_lat)
                    with contextlib.suppress(NoMatches):
                        self.query_one(HealthTrendChart).add_snapshot(now_str, backend_latencies)
            except (OSError, ConnectionError, ApiClientError):
                pass

            # Feed sessions into SessionsPanel
            sessions_resp = app.last_sessions
            if sessions_resp is not None:
                sessions_list = []
                for s in getattr(sessions_resp, "sessions", []):
                    d = s.model_dump() if hasattr(s, "model_dump") else s
                    sessions_list.append(
                        {
                            "session_id": d.get("id", "?"),
                            "user": d.get("transport_type", "—"),
                            "tool_count": d.get("tool_count", 0),
                            "created": f"{d.get('age_seconds', 0):.0f}s ago",
                            "ttl_remaining": d.get("ttl", 0) - d.get("age_seconds", 0),
                            "active": not d.get("expired", False),
                        }
                    )
                with contextlib.suppress(NoMatches):
                    self.query_one(SessionsPanel).update_sessions(sessions_list)

            # Feed groups into ServerGroupsWidget from cached groups data
            groups_resp = app.last_groups
            if groups_resp is not None:
                try:
                    inner = groups_resp.get("groups", {}) if isinstance(groups_resp, dict) else {}
                    # Normalize: API returns {name: {servers: [...], count: N}}
                    # but widget expects {name: [server_name, ...]}
                    normalized: dict[str, list[str]] = {}
                    for gname, gval in inner.items():
                        if isinstance(gval, dict):
                            normalized[gname] = gval.get("servers", [])
                        elif isinstance(gval, list):
                            normalized[gname] = gval
                    self.query_one(ServerGroupsWidget).update_groups([], groups=normalized)
                except NoMatches:
                    pass

        app.run_worker(_fetch(), exclusive=False, name="health-refresh")

    def _get_api_client(self):
        """Return the active :class:`ApiClient` or *None*."""
        mgr = self.app.server_manager
        if mgr is None:
            return None
        return getattr(mgr, "active_client", None)

    def on_health_panel_backend_reconnect(self, event: HealthPanel.BackendReconnect) -> None:
        """Reconnect a single backend via the management API."""
        client = self._get_api_client()
        if client is None:
            self.app.notify("Not connected to a server.", severity="error")
            return

        name = event.backend_name
        panel = self.query_one(HealthPanel)
        panel.set_action_status(f"Reconnecting [b]{name}[/b]…")
        self.app.notify(f"Reconnecting backend '{name}'…")

        async def _reconnect() -> None:
            try:
                resp = await client.post_reconnect(name)
                if resp.reconnected:
                    panel.set_action_status(
                        f"[green]✓[/green] Backend '{name}' reconnected successfully"
                    )
                    self.app.notify(f"Backend '{name}' reconnected.", severity="information")
                else:
                    err = resp.error or "unknown error"
                    panel.set_action_status(f"[red]✕[/red] Reconnect failed: {err}")
                    self.app.notify(f"Reconnect failed: {err}", severity="error")
            except (OSError, ConnectionError, ApiClientError) as exc:
                panel.set_action_status(f"[red]✕[/red] Reconnect error: {exc}")
                self.app.notify(f"Reconnect error: {exc}", severity="error")
            # Refresh the health table
            self._refresh_from_app()

        self.app.run_worker(_reconnect(), name=f"reconnect-{name}", exclusive=False)

    def on_health_panel_reload_requested(self, event: HealthPanel.ReloadRequested) -> None:
        """Hot-reload configuration via the management API."""
        client = self._get_api_client()
        if client is None:
            self.app.notify("Not connected to a server.", severity="error")
            return

        panel = self.query_one(HealthPanel)
        panel.set_action_status("Reloading configuration…")
        self.app.notify("Reloading server configuration…")

        async def _reload() -> None:
            try:
                resp = await client.post_reload()
                if resp.reloaded:
                    parts = []
                    if resp.backends_added:
                        parts.append(f"+{len(resp.backends_added)} added")
                    if resp.backends_removed:
                        parts.append(f"-{len(resp.backends_removed)} removed")
                    if resp.backends_changed:
                        parts.append(f"~{len(resp.backends_changed)} changed")
                    detail = ", ".join(parts) if parts else "no changes"
                    panel.set_action_status(f"[green]✓[/green] Config reloaded ({detail})")
                    self.app.notify(f"Config reloaded: {detail}", severity="information")
                else:
                    errs = "; ".join(resp.errors) if resp.errors else "unknown"
                    panel.set_action_status(f"[red]✕[/red] Reload failed: {errs}")
                    self.app.notify(f"Reload failed: {errs}", severity="error")
            except (OSError, ConnectionError, ApiClientError) as exc:
                panel.set_action_status(f"[red]✕[/red] Reload error: {exc}")
                self.app.notify(f"Reload error: {exc}", severity="error")
            self._refresh_from_app()

        self.app.run_worker(_reload(), name="reload-config", exclusive=False)

    def on_health_panel_shutdown_requested(self, event: HealthPanel.ShutdownRequested) -> None:
        """Gracefully shut down the Argus server."""
        client = self._get_api_client()
        if client is None:
            self.app.notify("Not connected to a server.", severity="error")
            return

        panel = self.query_one(HealthPanel)
        panel.set_action_status("Shutting down server…")
        self.app.notify("Sending shutdown request…", severity="warning")

        async def _shutdown() -> None:
            try:
                resp = await client.post_shutdown(timeout_seconds=10.0)
                if resp.shutting_down:
                    panel.set_action_status("[yellow]⏻[/yellow] Server is shutting down")
                    self.app.notify(
                        "Server is shutting down. Connection will be lost.",
                        severity="warning",
                    )
                else:
                    panel.set_action_status("[red]✕[/red] Shutdown request rejected")
            except (OSError, ConnectionError, ApiClientError) as exc:
                # Connection errors are expected after shutdown
                panel.set_action_status("[yellow]⏻[/yellow] Shutdown sent (connection closed)")
                logger.debug("Expected error after shutdown: %s", exc)

        self.app.run_worker(_shutdown(), name="shutdown-server", exclusive=False)

    def on_health_panel_add_backend_requested(
        self,
        event: HealthPanel.AddBackendRequested,
    ) -> None:
        """Open the backend config modal to add a new backend."""
        from argus_cli.tui.screens.backend_config import BackendConfigModal

        def _on_result(result: tuple | None) -> None:
            if result is None:
                return
            name, config = result
            self._add_backend_to_config(name, config)

        self.app.push_screen(BackendConfigModal(entry=None), _on_result)

    def _add_backend_to_config(self, name: str, config: dict) -> None:
        """Write a new backend to config.yaml and trigger hot-reload."""
        import json
        import os

        import yaml  # type: ignore[import-untyped]
        from argus_mcp.config.loader import find_config_file

        panel = self.query_one(HealthPanel)
        config_path = find_config_file()
        if config_path is None:
            self.app.notify("Cannot find config.yaml", severity="error")
            return

        try:
            with open(config_path) as fh:
                data = yaml.safe_load(fh) or {}
        except Exception as exc:
            logger.debug("Config read failed", exc_info=True)
            self.app.notify(f"Config read error: {exc}", severity="error")
            return

        backends = data.setdefault("backends", {})
        if name in backends:
            self.app.notify(f"Backend '{name}' already exists", severity="warning")
            return

        backends[name] = config
        try:
            with open(config_path, "w") as fh:
                yaml.safe_dump(data, fh, default_flow_style=False, sort_keys=False)
        except Exception as exc:
            logger.debug("Config write failed", exc_info=True)
            self.app.notify(f"Config write error: {exc}", severity="error")
            return

        logger.info("Added backend '%s' to %s: %s", name, config_path, json.dumps(config))
        panel.set_action_status(f"Added [b]{name}[/b] — reloading…")
        self.app.notify(
            f"Added [b]{name}[/b] to {os.path.basename(config_path)}",
            title="Backend Added",
        )

        # Trigger hot-reload
        client = self._get_api_client()
        if client is None:
            return

        async def _reload() -> None:
            try:
                resp = await client.post_reload()
                if resp.reloaded:
                    panel.set_action_status(
                        f"[green]✓[/green] Backend '{name}' added and config reloaded"
                    )
                else:
                    errs = "; ".join(resp.errors) if resp.errors else "unknown"
                    panel.set_action_status(f"[red]✕[/red] Reload failed: {errs}")
            except (OSError, ConnectionError, ApiClientError) as exc:
                panel.set_action_status(f"[red]✕[/red] Reload error: {exc}")
            self._refresh_from_app()

        self.app.run_worker(_reload(), name="add-backend-reload", exclusive=False)

    def on_health_panel_restart_requested(
        self,
        event: HealthPanel.RestartRequested,
    ) -> None:
        """Restart the Argus server — shutdown then poll for reconnection."""
        client = self._get_api_client()
        if client is None:
            self.app.notify("Not connected to a server.", severity="error")
            return

        panel = self.query_one(HealthPanel)
        panel.set_action_status("[yellow]⏻[/yellow] Restarting server…")
        self.app.notify("Restarting server — sending shutdown…", severity="warning")

        async def _restart() -> None:
            import asyncio

            try:
                await client.post_shutdown(timeout_seconds=5.0)
            except (OSError, ConnectionError, ApiClientError):
                pass  # expected — connection drops after shutdown

            panel.set_action_status("[yellow]…[/yellow] Server down — waiting for restart…")

            # Poll until the server comes back (container auto-restart / systemd)
            for _attempt in range(30):
                await asyncio.sleep(2)
                try:
                    health = await client.get_health()
                    if health:
                        panel.set_action_status("[green]✓[/green] Server restarted successfully")
                        self.app.notify("Server restarted!", severity="information")
                        self._refresh_from_app()
                        return
                except (OSError, ConnectionError, ApiClientError):
                    continue

            panel.set_action_status("[red]✕[/red] Server did not come back within 60 seconds")
            self.app.notify(
                "Server did not restart within timeout. Check container/systemd.",
                severity="error",
            )

        self.app.run_worker(_restart(), name="restart-server", exclusive=False)
