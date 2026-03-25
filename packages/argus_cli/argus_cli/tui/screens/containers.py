"""Containers mode — manage Argus Docker containers.

Provides a tabbed layout with:
- **Overview**: container list with status, resource usage, uptime
- **Logs**: multi-container log viewer with severity coloring
- **Stats**: reactive CPU/memory bars driven by argusd push stream
- **Exec**: placeholder for interactive terminal (future)

All data flows through :class:`~argus_cli.daemon_client.DaemonClient`
over the argusd Unix Domain Socket.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, DataTable, Static, TabbedContent, TabPane

from argus_cli.tui.screens.base import ArgusScreen
from argus_cli.tui.widgets.container_logs import ContainerLogViewer
from argus_cli.tui.widgets.container_stats import ContainerStatsPanel
from argus_cli.tui.widgets.container_table import ContainerStatusBar, ContainerTable

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class ContainersScreen(ArgusScreen):
    """Container management screen with tabbed layout."""

    INITIAL_FOCUS = "#container-dt"

    JUMP_TARGETS = {
        "containers-tabs": "t",
        "container-dt": "c",
        "container-log": "l",
        "stats-cpu-bar": "s",
    }

    BINDINGS = [
        ("r", "refresh_containers", "Refresh"),
        ("ctrl+s", "action_start", "Start"),
        ("ctrl+x", "action_stop", "Stop"),
        ("ctrl+r", "action_restart", "Restart"),
        ("delete", "action_remove", "Remove"),
    ]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._daemon_client: Any | None = None
        self._stream_tasks: list[asyncio.Task[None]] = []
        self._selected_container_id: str | None = None

    def compose_content(self) -> ComposeResult:
        with Vertical(id="containers-layout"):
            yield ContainerStatusBar(id="container-status-bar")
            with TabbedContent(id="containers-tabs"):
                with TabPane("Overview", id="tab-containers-overview"):
                    yield ContainerTable(id="container-table-widget")
                    with Horizontal(id="container-actions-bar"):
                        yield Button("Start", id="btn-container-start", variant="success")
                        yield Button("Stop", id="btn-container-stop", variant="warning")
                        yield Button("Restart", id="btn-container-restart", variant="default")
                        yield Button("Remove", id="btn-container-remove", variant="error")
                        yield Button("Refresh", id="btn-container-refresh", variant="primary")
                with TabPane("Logs", id="tab-containers-logs"):
                    yield ContainerLogViewer(id="container-log-viewer")
                with TabPane("Stats", id="tab-containers-stats"):
                    yield ContainerStatsPanel(id="container-stats-panel")
                with TabPane("Exec", id="tab-containers-exec"):
                    yield Static(
                        "[dim]Interactive exec — select a container and press Enter[/dim]",
                        id="exec-placeholder",
                    )

    async def on_show(self) -> None:
        """Load containers when the screen is shown."""
        await self._connect_daemon()
        await self._load_containers()

    async def on_screen_suspend(self) -> None:
        """Cancel streaming tasks when leaving the screen."""
        self._cancel_streams()

    async def _connect_daemon(self) -> None:
        """Lazily connect the daemon client."""
        if self._daemon_client is not None:
            return
        try:
            from argus_cli.daemon_client import DaemonClient

            client = DaemonClient()
            if not client.socket_exists:
                logger.warning("argusd socket not found at %s", client.socket_path)
                self._update_status_error("argusd not running")
                return
            await client.connect()
            self._daemon_client = client
        except Exception:
            logger.exception("Failed to connect to argusd")
            self._update_status_error("Failed to connect to argusd")

    async def _load_containers(self) -> None:
        """Fetch container list from argusd and populate the table."""
        if self._daemon_client is None:
            return
        try:
            containers = await self._daemon_client.list_containers()
            table = self.query_one("#container-table-widget", ContainerTable)
            table.refresh_containers(containers)

            running = sum(
                1 for c in containers if str(c.get("status", "")).lower() in ("running", "up")
            )
            stopped = len(containers) - running
            status_bar = self.query_one("#container-status-bar", ContainerStatusBar)
            status_bar.update_counts(total=len(containers), running=running, stopped=stopped)
        except Exception:
            logger.exception("Failed to load containers")
            self._update_status_error("Error loading containers")

    def _update_status_error(self, message: str) -> None:
        with contextlib.suppress(NoMatches):
            bar = self.query_one("#container-status-bar", ContainerStatusBar)
            bar.update(f"[red]{message}[/red]")

    # ── Container actions ──────────────────────────────────────────

    def _get_selected_id(self) -> str | None:
        """Return the row key of the currently selected container."""
        try:
            table = self.query_one("#container-dt", DataTable)
            if table.cursor_row is not None:
                keys = list(table.rows.keys())
                if 0 <= table.cursor_row < len(keys):
                    return str(keys[table.cursor_row])
        except Exception:
            pass
        return self._selected_container_id

    async def _container_action(self, action: str) -> None:
        """Execute a lifecycle action on the selected container."""
        cid = self._get_selected_id()
        if not cid or self._daemon_client is None:
            return
        try:
            method = getattr(self._daemon_client, f"{action}_container")
            await method(cid)
            await self._load_containers()
        except Exception:
            logger.exception("Container %s failed for %s", action, cid)

    async def action_refresh_containers(self) -> None:
        await self._load_containers()

    async def action_start(self) -> None:
        await self._container_action("start")

    async def action_stop(self) -> None:
        await self._container_action("stop")

    async def action_restart(self) -> None:
        await self._container_action("restart")

    async def action_remove(self) -> None:
        await self._container_action("remove")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_map = {
            "btn-container-start": "action_start",
            "btn-container-stop": "action_stop",
            "btn-container-restart": "action_restart",
            "btn-container-remove": "action_remove",
            "btn-container-refresh": "action_refresh_containers",
        }
        action = button_map.get(event.button.id or "")
        if action:
            self.run_worker(getattr(self, action)())

    # ── SSE streaming ──────────────────────────────────────────────

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Start streaming logs + stats for the selected container."""
        row_key = str(event.row_key.value) if event.row_key else None
        if not row_key or row_key == self._selected_container_id:
            return
        self._selected_container_id = row_key
        self._cancel_streams()
        if self._daemon_client is not None:
            self._stream_tasks.append(asyncio.create_task(self._stream_logs(row_key)))
            self._stream_tasks.append(asyncio.create_task(self._stream_stats(row_key)))

    async def _stream_logs(self, container_id: str) -> None:
        """Background task: stream logs for a container."""
        if self._daemon_client is None:
            return
        viewer = self.query_one("#container-log-viewer", ContainerLogViewer)
        viewer.clear_logs()
        try:
            async for event in self._daemon_client.stream_logs(container_id, tail="200"):
                data = event.get("data", {})
                line = data.get("line", str(data)) if isinstance(data, dict) else str(data)
                stream = data.get("stream", "") if isinstance(data, dict) else ""
                viewer.append_log(line, stream=stream)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("Log stream ended for %s", container_id)

    async def _stream_stats(self, container_id: str) -> None:
        """Background task: stream stats for a container."""
        if self._daemon_client is None:
            return
        panel = self.query_one("#container-stats-panel", ContainerStatsPanel)
        try:
            async for event in self._daemon_client.stream_stats(container_id):
                data = event.get("data", {})
                if isinstance(data, dict):
                    panel.update_stats(data)
                    # Also update the overview table's CPU/mem columns
                    with contextlib.suppress(NoMatches):
                        table = self.query_one("#container-table-widget", ContainerTable)
                        table.update_stats(container_id, data)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("Stats stream ended for %s", container_id)

    def _cancel_streams(self) -> None:
        """Cancel all running SSE stream tasks."""
        for task in self._stream_tasks:
            task.cancel()
        self._stream_tasks.clear()
