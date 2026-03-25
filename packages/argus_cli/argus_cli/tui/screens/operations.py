"""Operations mode — workflows, optimizer, and telemetry.

Houses the heavier operational features (each with Input widgets
or complex layouts) in their own tabs, keeping Dashboard clean.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.css.query import NoMatches
from textual.widgets import TabbedContent, TabPane

from argus_cli.tui.screens.base import ArgusScreen
from argus_cli.tui.widgets.optimizer_panel import OptimizerPanel
from argus_cli.tui.widgets.otel_panel import OTelPanel
from argus_cli.tui.widgets.sync_status import SyncStatusWidget
from argus_cli.tui.widgets.tool_ops_panel import ToolOpsPanel
from argus_cli.tui.widgets.workflows_panel import WorkflowsPanel

if TYPE_CHECKING:
    from textual.app import ComposeResult


class OperationsScreen(ArgusScreen):
    """Operations mode — workflows, tool optimizer, and telemetry."""

    JUMP_TARGETS = {
        "ops-tabs": "t",
        "workflows-panel-widget": "w",
        "optimizer-panel-widget": "o",
    }

    def compose_content(self) -> ComposeResult:
        with TabbedContent(id="ops-tabs"):
            with TabPane("Workflows", id="tab-ops-workflows"):
                yield WorkflowsPanel(id="workflows-panel-widget")
            with TabPane("Optimizer", id="tab-ops-optimizer"):
                yield OptimizerPanel(id="optimizer-panel-widget")
            with TabPane("Telemetry", id="tab-ops-otel"):
                yield OTelPanel(id="otel-panel-widget")
            with TabPane("Sync", id="tab-ops-sync"):
                yield SyncStatusWidget(id="sync-status-widget")
            with TabPane("Tool Ops", id="tab-ops-toolops"):
                yield ToolOpsPanel(id="tool-ops-panel-widget")

    def on_show(self) -> None:
        """Populate panels from cached app state when screen is displayed."""
        self._populate_optimizer()
        self._populate_otel()
        self._populate_sync()

    def _populate_optimizer(self) -> None:
        """Feed optimizer status from feature flags and cached capabilities."""
        status = self.app.last_status
        caps = self.app.last_caps
        try:
            panel = self.query_one(OptimizerPanel)
        except NoMatches:
            return

        enabled = False
        total_tools = 0
        if status is not None:
            ff: dict[str, Any] = getattr(status, "feature_flags", {}) or {}
            enabled = ff.get("optimizer", False)
        if caps is not None:
            total_tools = len(caps.tools)

        panel.update_optimizer_status(
            enabled=enabled,
            total_tools=total_tools,
        )

    def _populate_otel(self) -> None:
        """Feed OTel status from cached backends and status."""
        try:
            panel = self.query_one(OTelPanel)
        except NoMatches:
            return

        status = self.app.last_status
        if status is not None:
            ff: dict[str, Any] = getattr(status, "feature_flags", {}) or {}
            # OTel is enabled if there's an otel exporter configured
            otel_enabled = ff.get("otel", False)
            panel.update_otel_status(enabled=otel_enabled)

        # Populate per-backend breakdown from backends data
        mgr = self.app.server_manager
        if mgr is not None:
            from argus_cli.tui.server_manager import ServerManager

            if isinstance(mgr, ServerManager):
                entry = mgr.active_entry
                if entry and entry.client and entry.client.is_connected:
                    self.app.run_worker(
                        self._fetch_otel_backends(panel, entry.client),
                        name="otel-backends",
                        exclusive=True,
                    )

    async def _fetch_otel_backends(self, panel: OTelPanel, client: Any) -> None:
        """Async fetch backend data for OTel breakdown."""
        try:
            backends_resp = await client.get_backends()
            breakdown = []
            for b in backends_resp.backends:
                d = b.model_dump() if hasattr(b, "model_dump") else b
                health = d.get("health", {}) or {}
                breakdown.append(
                    {
                        "name": d.get("name", "?"),
                        "calls": 0,  # Not tracked in management API
                        "avg_latency_ms": health.get("latency_ms", 0) or 0,
                        "error_percent": 0,
                        "health": health,
                    }
                )
            panel.update_backend_breakdown(breakdown)
        except (OSError, ConnectionError, Exception):
            pass

    def _populate_sync(self) -> None:
        """Feed sync status from cached status data."""
        status = self.app.last_status
        if status is None:
            return
        try:
            widget = self.query_one(SyncStatusWidget)
        except NoMatches:
            return

        ff: dict[str, Any] = getattr(status, "feature_flags", {}) or {}
        hot_reload = ff.get("hot_reload", False)
        config_file = getattr(status.config, "file_path", "") or ""
        loaded_at = getattr(status.config, "loaded_at", "") or ""

        widget.update_sync_status(
            config_file=config_file,
            config_hash="",
            last_sync=loaded_at[:19] if loaded_at else "—",
            is_live=hot_reload,
        )
