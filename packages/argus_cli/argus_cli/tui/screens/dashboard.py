"""Dashboard mode — server info, backends, events, and capabilities.

The main operational screen.  Kept intentionally clean: sidebar
(server selector, info, backends) + event log + capability tables.
All monitoring/operational panels live in dedicated mode screens
(Health, Security, Operations) accessible via keyboard shortcuts.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.containers import Horizontal, Vertical

from argus_cli.tui.screens.base import ArgusScreen
from argus_cli.tui.widgets.backend_status import BackendStatusWidget
from argus_cli.tui.widgets.capability_tables import CapabilitySection
from argus_cli.tui.widgets.event_log import EventLogWidget
from argus_cli.tui.widgets.module_container import ModuleContainer
from argus_cli.tui.widgets.quick_actions import QuickAction, QuickActionBar
from argus_cli.tui.widgets.server_info import ServerInfoWidget
from argus_cli.tui.widgets.server_selector import ServerSelectorWidget
from argus_cli.tui.widgets.tplot import UptimeChart

if TYPE_CHECKING:
    from textual.app import ComposeResult


class DashboardScreen(ArgusScreen):
    """Main dashboard screen."""

    JUMP_TARGETS = {
        "srv-selector": "s",
        "backends-module": "b",
        "main-area": "e",
        "cap-section": "c",
        "dashboard-uptime-chart": "u",
    }

    def on_show(self) -> None:
        """Trigger app-level initialization once the screen is shown."""
        if getattr(self, "_ds_init_done", False):
            return
        self._ds_init_done = True
        app = self.app
        if hasattr(app, "_init_after_mode_switch"):
            app._init_after_mode_switch()

    def compose_content(self) -> ComposeResult:
        with Horizontal(id="top-row"):
            with Vertical(id="sidebar"):
                yield ServerSelectorWidget(id="srv-selector")
                with ModuleContainer(title="Server", subtitle="[s]erver", id="server-info-module"):
                    yield ServerInfoWidget()
                with ModuleContainer(title="Backends", subtitle="[b]ackends", id="backends-module"):
                    yield BackendStatusWidget()
            with ModuleContainer(title="Events", subtitle="[e]vents", id="main-area"):
                yield EventLogWidget()
        with ModuleContainer(title="Capabilities", subtitle="[c]apabilities", id="cap-section"):
            yield CapabilitySection()
        with ModuleContainer(title="Connection Uptime", subtitle="[u]ptime", id="uptime-section"):
            yield UptimeChart(id="dashboard-uptime-chart")
        yield QuickActionBar(
            actions=[
                QuickAction("x", "Export Config", lambda: self.app.action_export_client_config()),
                QuickAction("T", "Themes", lambda: self.app.action_open_theme_picker()),
                QuickAction("n", "Next Theme", lambda: self.app.action_next_theme()),
                QuickAction(";", "Jump", lambda: self.app.action_jump_mode()),
            ],
            id="dashboard-quick-actions",
        )
