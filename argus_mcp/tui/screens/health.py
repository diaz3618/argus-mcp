"""Health mode — backend health, sessions, and version drift.

Aggregates monitoring widgets into a tabbed layout so the
Dashboard stays clean.  The Status tab also provides lifecycle
controls for individual backends and the whole server.
"""

from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.css.query import NoMatches
from textual.widgets import TabbedContent, TabPane

from argus_mcp.tui.screens.base import ArgusScreen
from argus_mcp.tui.widgets.health_panel import HealthPanel
from argus_mcp.tui.widgets.server_groups import ServerGroupsWidget
from argus_mcp.tui.widgets.sessions_panel import SessionsPanel
from argus_mcp.tui.widgets.version_drift import VersionDriftPanel

logger = logging.getLogger(__name__)


class HealthScreen(ArgusScreen):
    """Health monitoring mode — per-backend status, sessions, versions."""

    def compose_content(self) -> ComposeResult:
        with TabbedContent(id="health-tabs"):
            with TabPane("Status", id="tab-health-status"):
                yield HealthPanel(id="health-panel-widget")
            with TabPane("Sessions", id="tab-health-sessions"):
                yield SessionsPanel(id="sessions-panel-widget")
            with TabPane("Versions", id="tab-health-versions"):
                yield VersionDriftPanel(id="version-drift-widget")
            with TabPane("Server Groups", id="tab-health-groups"):
                yield ServerGroupsWidget(id="server-groups-widget")

    def on_show(self) -> None:
        """Refresh health data from cached app state."""
        self._refresh_from_app()

    def _refresh_from_app(self) -> None:
        """Pull latest backend data from the app cache into widgets."""
        app = self.app
        last_status = getattr(app, "_last_status", None)
        if last_status is None:
            return

        # Feed backends into health panel + server groups
        mgr = getattr(app, "_server_manager", None)
        if mgr is None:
            return
        client = getattr(mgr, "active_client", None)
        if client is None:
            return

        async def _fetch() -> None:
            try:
                backends_resp = await client.get_backends()
                details = [b.model_dump() for b in backends_resp.backends]
                try:
                    self.query_one(HealthPanel).update_from_backends(details)
                except NoMatches:
                    pass
                try:
                    self.query_one(ServerGroupsWidget).update_groups(details)
                except NoMatches:
                    pass
            except (OSError, ConnectionError):
                pass

        app.run_worker(_fetch(), exclusive=False, name="health-refresh")

    # ── Helper: get active API client ────────────────────────────

    def _get_api_client(self):
        """Return the active :class:`ApiClient` or *None*."""
        mgr = getattr(self.app, "_server_manager", None)
        if mgr is None:
            return None
        return getattr(mgr, "active_client", None)

    # ── Lifecycle action handlers ────────────────────────────────

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
            except (OSError, ConnectionError) as exc:
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
            except (OSError, ConnectionError) as exc:
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
            except (OSError, ConnectionError) as exc:
                # Connection errors are expected after shutdown
                panel.set_action_status("[yellow]⏻[/yellow] Shutdown sent (connection closed)")
                logger.debug("Expected error after shutdown: %s", exc)

        self.app.run_worker(_shutdown(), name="shutdown-server", exclusive=False)
