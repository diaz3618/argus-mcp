"""TUI widget definitions."""

from argus_mcp.tui.widgets.backend_status import BackendStatusWidget
from argus_mcp.tui.widgets.capability_tables import CapabilitySection
from argus_mcp.tui.widgets.event_log import EventLogWidget
from argus_mcp.tui.widgets.server_info import ServerInfoWidget
from argus_mcp.tui.widgets.tool_ops_panel import ToolOpsPanel

__all__ = [
    "BackendStatusWidget",
    "CapabilitySection",
    "EventLogWidget",
    "ServerInfoWidget",
    "ToolOpsPanel",
]
