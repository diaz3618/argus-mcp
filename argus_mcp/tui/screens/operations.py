"""Operations mode — workflows, optimizer, and telemetry.

Houses the heavier operational features (each with Input widgets
or complex layouts) in their own tabs, keeping Dashboard clean.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import TabbedContent, TabPane

from argus_mcp.tui.screens.base import ArgusScreen
from argus_mcp.tui.widgets.optimizer_panel import OptimizerPanel
from argus_mcp.tui.widgets.otel_panel import OTelPanel
from argus_mcp.tui.widgets.sync_status import SyncStatusWidget
from argus_mcp.tui.widgets.tool_ops_panel import ToolOpsPanel
from argus_mcp.tui.widgets.workflows_panel import WorkflowsPanel


class OperationsScreen(ArgusScreen):
    """Operations mode — workflows, tool optimizer, and telemetry."""

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
