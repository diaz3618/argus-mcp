"""TUI screen definitions for multi-mode navigation."""

from argus_cli.tui.screens.base import ArgusScreen
from argus_cli.tui.screens.catalog_browser import CatalogBrowserScreen
from argus_cli.tui.screens.dashboard import DashboardScreen
from argus_cli.tui.screens.export_import import ExportImportScreen
from argus_cli.tui.screens.registry import RegistryScreen
from argus_cli.tui.screens.server_logs import ServerLogsScreen
from argus_cli.tui.screens.settings import SettingsScreen
from argus_cli.tui.screens.skills import SkillsScreen
from argus_cli.tui.screens.theme_picker import ThemeScreen
from argus_cli.tui.screens.tools import ToolsScreen

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
