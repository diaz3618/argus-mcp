"""TUI screen definitions for multi-mode navigation."""

from argus_mcp.tui.screens.base import ArgusScreen
from argus_mcp.tui.screens.catalog_browser import CatalogBrowserScreen
from argus_mcp.tui.screens.dashboard import DashboardScreen
from argus_mcp.tui.screens.export_import import ExportImportScreen
from argus_mcp.tui.screens.registry import RegistryScreen
from argus_mcp.tui.screens.server_logs import ServerLogsScreen
from argus_mcp.tui.screens.settings import SettingsScreen
from argus_mcp.tui.screens.skills import SkillsScreen
from argus_mcp.tui.screens.theme_picker import ThemeScreen
from argus_mcp.tui.screens.tools import ToolsScreen

__all__ = [
    "ArgusScreen",
    "CatalogBrowserScreen",
    "DashboardScreen",
    "ExportImportScreen",
    "RegistryScreen",
    "ServerLogsScreen",
    "SettingsScreen",
    "SkillsScreen",
    "ThemeScreen",
    "ToolsScreen",
]
