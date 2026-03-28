"""TUI widget definitions."""

from argus_cli.tui.widgets.backend_status import BackendStatusWidget
from argus_cli.tui.widgets.capability_tables import CapabilitySection
from argus_cli.tui.widgets.event_log import EventLogWidget
from argus_cli.tui.widgets.server_info import ServerInfoWidget
from argus_cli.tui.widgets.tool_ops_panel import ToolOpsPanel

__all__ = [
    "BackendStatusWidget",
    "CapabilitySection",
    "EventLogWidget",
    "ServerInfoWidget",
    "ToolOpsPanel",
]
