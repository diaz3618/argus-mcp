"""Kubernetes mode — manage Argus-managed Kubernetes pods.

Provides a tabbed layout with:
- **Pods**: pod list with status, node, IP, restarts, age
- **Logs**: per-pod log viewer with severity coloring
- **Events**: Kubernetes events for the selected pod
- **Details**: describe output for the selected pod

All data flows through :class:`~argus_cli.daemon_client.DaemonClient`
over the argusd Unix Domain Socket.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any

from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.widgets import Button, DataTable, Static, TabbedContent, TabPane

from argus_cli.tui.screens.base import ArgusScreen
from argus_cli.tui.widgets.container_logs import ContainerLogViewer
from argus_cli.tui.widgets.pod_table import PodStatusBar, PodTable

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class KubernetesScreen(ArgusScreen):
    """Kubernetes pod management screen with tabbed layout."""

    INITIAL_FOCUS = "#pod-dt"

    JUMP_TARGETS = {
        "kubernetes-tabs": "t",
        "pod-dt": "k",
        "pod-log": "l",
    }

    BINDINGS = [
        ("r", "refresh_pods", "Refresh"),
        ("delete", "action_delete_pod", "Delete Pod"),
    ]

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._daemon_client: Any | None = None
        self._stream_tasks: list[asyncio.Task[None]] = []
        self._selected_pod_key: str | None = None  # "namespace/name"

    def compose_content(self) -> ComposeResult:
        with Vertical(id="kubernetes-layout"):
            yield PodStatusBar(id="pod-status-bar")
            with TabbedContent(id="kubernetes-tabs"):
                with TabPane("Pods", id="tab-pods-overview"):
                    yield PodTable(id="pod-table-widget")
                    yield Button("Refresh", id="btn-pod-refresh", variant="primary")
                with TabPane("Logs", id="tab-pods-logs"):
                    yield ContainerLogViewer(id="pod-log-viewer")
                with TabPane("Events", id="tab-pods-events"):
                    yield Static(
                        "[dim]Select a pod to view its events.[/dim]",
                        id="pod-events-content",
                    )
                with TabPane("Details", id="tab-pods-details"):
                    yield Static(
                        "[dim]Select a pod to view details.[/dim]",
                        id="pod-details-content",
                    )

    async def on_show(self) -> None:
        """Load pods when the screen is shown."""
        await self._connect_daemon()
        await self._load_pods()

    async def on_screen_suspend(self) -> None:
        """Cancel streaming tasks when leaving the screen."""
        self._cancel_streams()

    async def _connect_daemon(self) -> None:
        """Lazily connect the daemon client."""
        if self._daemon_client is not None:
            return
        try:
            from argus_cli.config import get_config
            from argus_cli.daemon_client import DaemonClient

            cfg = get_config()
            client = DaemonClient(socket_path=cfg.argusd_socket)
            if not client.socket_exists:
                if cfg.argusd_auto_start:
                    started = client.auto_start(binary_hint=cfg.argusd_binary)
                    if not started:
                        self._update_status_error("argusd not running (auto-start failed)")
                        return
                else:
                    logger.warning("argusd socket not found at %s", client.socket_path)
                    self._update_status_error("argusd not running")
                    return
            await client.connect()
            self._daemon_client = client
        except Exception:
            logger.exception("Failed to connect to argusd")
            self._update_status_error("Failed to connect to argusd")

    async def _load_pods(self) -> None:
        """Fetch pod list from argusd and populate the table."""
        if self._daemon_client is None:
            return
        try:
            data = await self._daemon_client.list_pods()
            pods = data if isinstance(data, list) else data.get("pods", [])
            table = self.query_one("#pod-table-widget", PodTable)
            table.refresh_pods(pods)

            running = sum(1 for p in pods if str(p.get("status", "")).lower() == "running")
            pending = sum(1 for p in pods if str(p.get("status", "")).lower() == "pending")
            failed = sum(
                1
                for p in pods
                if str(p.get("status", "")).lower() in ("failed", "error", "crashloopbackoff")
            )
            status_bar = self.query_one("#pod-status-bar", PodStatusBar)
            status_bar.update_counts(
                total=len(pods), running=running, pending=pending, failed=failed
            )
        except Exception:
            logger.exception("Failed to load pods")
            self._update_status_error("Error loading pods")

    def _update_status_error(self, message: str) -> None:
        with contextlib.suppress(NoMatches):
            bar = self.query_one("#pod-status-bar", PodStatusBar)
            bar.update(f"[red]{message}[/red]")

    # ── Pod selection ──────────────────────────────────────────────

    def _get_selected_key(self) -> str | None:
        """Return the row key ('namespace/name') of the currently selected pod."""
        try:
            table = self.query_one("#pod-dt", DataTable)
            if table.cursor_row is not None:
                keys = list(table.rows.keys())
                if 0 <= table.cursor_row < len(keys):
                    return str(keys[table.cursor_row])
        except Exception:
            pass
        return self._selected_pod_key

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Start streaming logs + load events/details for the selected pod."""
        row_key = str(event.row_key.value) if event.row_key else None
        if not row_key or row_key == self._selected_pod_key:
            return
        self._selected_pod_key = row_key
        self._cancel_streams()
        if self._daemon_client is not None:
            self._stream_tasks.append(asyncio.create_task(self._stream_pod_logs(row_key)))
            self._stream_tasks.append(asyncio.create_task(self._load_pod_events(row_key)))
            self._stream_tasks.append(asyncio.create_task(self._load_pod_details(row_key)))

    def _parse_key(self, key: str) -> tuple[str, str]:
        """Split 'namespace/name' row key."""
        ns, _, name = key.partition("/")
        return ns, name

    # ── Streaming / detail loading ─────────────────────────────────

    async def _stream_pod_logs(self, key: str) -> None:
        """Background task: stream logs for a pod."""
        if self._daemon_client is None:
            return
        ns, name = self._parse_key(key)
        viewer = self.query_one("#pod-log-viewer", ContainerLogViewer)
        viewer.clear_logs()
        try:
            async for event in self._daemon_client.stream_pod_logs(ns, name, tail="200"):
                data = event.get("data", {})
                line = data.get("line", str(data)) if isinstance(data, dict) else str(data)
                stream = data.get("stream", "") if isinstance(data, dict) else ""
                viewer.append_log(line, stream=stream)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.debug("Pod log stream ended for %s", key)

    async def _load_pod_events(self, key: str) -> None:
        """Load Kubernetes events for a pod."""
        if self._daemon_client is None:
            return
        ns, name = self._parse_key(key)
        try:
            data = await self._daemon_client.pod_events(ns, name)
            events = data if isinstance(data, list) else data.get("events", [])
            lines = []
            for ev in events:
                etype = ev.get("type", "Normal")
                reason = ev.get("reason", "")
                msg = ev.get("message", "")
                age = ev.get("age", "")
                color = "yellow" if etype == "Warning" else "dim"
                lines.append(f"[{color}]{age:>8s}  {etype:<8s}  {reason:<20s}  {msg}[/]")
            content = "\n".join(lines) if lines else "[dim]No events.[/dim]"
            widget = self.query_one("#pod-events-content", Static)
            widget.update(content)
        except Exception:
            logger.debug("Failed to load events for %s", key)

    async def _load_pod_details(self, key: str) -> None:
        """Load describe output for a pod."""
        if self._daemon_client is None:
            return
        ns, name = self._parse_key(key)
        try:
            data = await self._daemon_client.describe_pod(ns, name)
            if isinstance(data, dict):
                lines = [f"[bold]{k}:[/] {v}" for k, v in data.items()]
                content = "\n".join(lines)
            else:
                content = str(data)
            widget = self.query_one("#pod-details-content", Static)
            widget.update(content)
        except Exception:
            logger.debug("Failed to load details for %s", key)

    def _cancel_streams(self) -> None:
        """Cancel all running stream tasks."""
        for task in self._stream_tasks:
            task.cancel()
        self._stream_tasks.clear()

    # ── Actions ────────────────────────────────────────────────────

    async def action_refresh_pods(self) -> None:
        await self._load_pods()

    async def action_delete_pod(self) -> None:
        """Delete the currently selected pod."""
        key = self._get_selected_key()
        if not key or self._daemon_client is None:
            return
        ns, name = self._parse_key(key)
        try:
            await self._daemon_client.delete_pod(ns, name)
            await self._load_pods()
        except Exception:
            logger.exception("Failed to delete pod %s", key)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_map = {
            "btn-pod-refresh": "action_refresh_pods",
        }
        action = button_map.get(event.button.id or "")
        if action:
            self.run_worker(getattr(self, action)())
