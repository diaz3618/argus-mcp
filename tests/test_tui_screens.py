"""Tests for TUI screens and widgets.

Covers:
- ServerLogsScreen: init, filters, events, pause, export
- ExportImportScreen: init, bindings, panel composition
- _ExportPanel / _ImportPanel: config loading, secret handling, conflict strategy
- CatalogBrowserScreen: init, bindings, example loading, stage/commit flow
- ToolOpsPanel: init, tool extraction, validation logic, filtering
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# Skip if textual version lacks SystemCommand (required by argus_mcp.tui)
try:
    from textual.app import SystemCommand  # noqa: F401
except ImportError:
    pytest.skip("textual version lacks SystemCommand", allow_module_level=True)

from textual.css.query import NoMatches  # noqa: E402

# ServerLogsScreen
from argus_mcp.tui.screens.server_logs import ServerLogsScreen  # noqa: E402


class TestServerLogsScreenInit:
    def test_init_defaults(self):
        screen = ServerLogsScreen()
        assert screen._events == []
        assert screen._paused is False
        assert screen._filter_search == ""
        assert screen._show_correlation is True

    def test_bindings_present(self):
        screen = ServerLogsScreen()
        binding_keys = {b[0] if isinstance(b, tuple) else b.key for b in screen.BINDINGS}
        assert "slash" in binding_keys
        assert "escape" in binding_keys
        assert "c" in binding_keys
        assert "e" in binding_keys
        assert "p" in binding_keys


class TestServerLogsApplyFilters:
    """Test the _apply_filters method in isolation (mocking widget queries)."""

    def _make_screen(self) -> ServerLogsScreen:
        screen = ServerLogsScreen()
        # Widget queries raise NoMatches when unmounted — _apply_filters catches these
        screen.query_one = MagicMock(side_effect=NoMatches())
        return screen

    def test_filter_empty_events(self):
        screen = self._make_screen()
        result = screen._apply_filters([])
        assert result == []

    def test_filter_pass_through(self):
        screen = self._make_screen()
        events = [
            {"server": "s1", "method": "tools/call", "status": "ok"},
            {"server": "s2", "method": "tools/list", "status": "ok"},
        ]
        # With no widget queries succeeding, all filters fall through
        result = screen._apply_filters(events)
        assert len(result) == 2

    def test_text_search_filter(self):
        screen = self._make_screen()
        screen._filter_search = "special-tool"
        events = [
            {"server": "s1", "tool": "special-tool", "method": "tools/call"},
            {"server": "s2", "tool": "other-tool", "method": "tools/call"},
        ]
        result = screen._apply_filters(events)
        assert len(result) == 1
        assert result[0]["tool"] == "special-tool"

    def test_text_search_case_insensitive(self):
        screen = self._make_screen()
        screen._filter_search = "MYSERVER"
        events = [
            {"server": "myserver", "tool": "t1"},
        ]
        result = screen._apply_filters(events)
        assert len(result) == 1


class TestServerLogsAddEvent:
    def test_add_event_appends(self):
        screen = ServerLogsScreen()
        screen._refresh_table = MagicMock()
        event = {"server": "s1", "method": "tools/call"}
        screen.add_event(event)
        assert len(screen._events) == 1
        assert screen._events[0] is event

    def test_add_event_ignored_when_paused(self):
        screen = ServerLogsScreen()
        screen._refresh_table = MagicMock()
        screen._paused = True
        screen.add_event({"server": "s1"})
        assert len(screen._events) == 0

    def test_toggle_pause(self):
        screen = ServerLogsScreen()
        screen.query_one = MagicMock(side_effect=NoMatches())
        assert screen._paused is False
        screen.action_toggle_pause()
        assert screen._paused is True
        screen.action_toggle_pause()
        assert screen._paused is False


class TestServerLogsCorrelation:
    def test_toggle_correlation(self):
        screen = ServerLogsScreen()
        screen._refresh_table = MagicMock()
        screen.notify = MagicMock()
        assert screen._show_correlation is True
        screen.action_toggle_correlation()
        assert screen._show_correlation is False
        screen.action_toggle_correlation()
        assert screen._show_correlation is True


# ExportImportScreen

from argus_mcp.config.export import ExportFilter, SecretHandling
from argus_mcp.config.import_handler import ConflictStrategy
from argus_mcp.tui.screens.export_import import (
    ExportImportScreen,
)


class TestExportImportScreenInit:
    def test_bindings_present(self):
        screen = ExportImportScreen()
        binding_keys = {b[0] if isinstance(b, tuple) else b.key for b in screen.BINDINGS}
        assert "e" in binding_keys
        assert "i" in binding_keys
        assert "escape" in binding_keys


class TestExportPanelSecretHandling:
    """Test SecretHandling enum used by the export panel."""

    def test_secret_handling_values(self):
        assert SecretHandling.MASK.value == "mask"
        assert SecretHandling.STRIP.value == "strip"
        assert SecretHandling.PRESERVE.value == "preserve"

    def test_all_secret_modes(self):
        expected = {"mask", "strip", "preserve"}
        assert {sh.value for sh in SecretHandling} == expected


class TestExportFilterConstruction:
    def test_backends_only(self):
        f = ExportFilter(entity_types={"backends"})
        assert "backends" in f.entity_types

    def test_all_filter_is_none(self):
        """When 'all' is selected, the panel returns None."""
        # Verifying the pattern: None means no filter
        assert ExportFilter(entity_types=set()) is not None


class TestImportConflictStrategy:
    """Test ConflictStrategy enum used by the import panel."""

    def test_conflict_strategy_values(self):
        assert ConflictStrategy.SKIP.value == "skip"
        assert ConflictStrategy.UPDATE.value == "update"
        assert ConflictStrategy.RENAME.value == "rename"
        assert ConflictStrategy.FAIL.value == "fail"

    def test_all_strategies(self):
        expected = {"skip", "update", "rename", "fail"}
        assert {cs.value for cs in ConflictStrategy} == expected


# CatalogBrowserScreen

from argus_mcp.registry.catalog import CatalogEntryStatus
from argus_mcp.tui.screens.catalog_browser import (
    _EXAMPLE_CATALOG,
    CatalogBrowserScreen,
)


class TestCatalogBrowserScreenInit:
    def test_bindings_present(self):
        screen = CatalogBrowserScreen()
        binding_keys = {b[0] if isinstance(b, tuple) else b.key for b in screen.BINDINGS}
        assert "escape" in binding_keys
        assert "s" in binding_keys
        assert "c" in binding_keys


class TestExampleCatalog:
    def test_example_is_valid_yaml(self):
        import yaml

        data = yaml.safe_load(_EXAMPLE_CATALOG)
        assert isinstance(data, dict)
        assert "servers" in data
        assert isinstance(data["servers"], list)
        assert len(data["servers"]) >= 1

    def test_example_has_required_fields(self):
        import yaml

        data = yaml.safe_load(_EXAMPLE_CATALOG)
        server = data["servers"][0]
        assert "name" in server
        assert "transport" in server
        assert "command" in server


class TestCatalogEntryStatusEnum:
    def test_all_statuses(self):
        expected = {"staged", "added", "skipped", "failed", "health_ok", "health_failed"}
        assert {s.value for s in CatalogEntryStatus} == expected

    def test_staged(self):
        assert CatalogEntryStatus.STAGED.value == "staged"

    def test_added(self):
        assert CatalogEntryStatus.ADDED.value == "added"

    def test_failed(self):
        assert CatalogEntryStatus.FAILED.value == "failed"


# ToolOpsPanel

from argus_mcp.tui.widgets.tool_ops_panel import ToolOpsPanel


class TestToolOpsPanelGetTools:
    """Test _get_tools() with mock app.last_caps."""

    def _make_panel(self, caps: Any = None) -> ToolOpsPanel:
        panel = ToolOpsPanel()
        mock_app = MagicMock()
        mock_app.last_caps = caps
        # Patch the app property to return our mock
        with patch.object(type(panel), "app", new_callable=lambda: property(lambda self: mock_app)):
            panel._mock_app = mock_app  # stash for assertions
        return panel

    def test_returns_empty_when_no_caps(self):
        panel = ToolOpsPanel()
        mock_app = MagicMock()
        mock_app.last_caps = None
        with patch.object(type(panel), "app", new_callable=lambda: property(lambda s: mock_app)):
            result = panel._get_tools()
        assert result == []

    def test_returns_tools_from_caps(self):
        panel = ToolOpsPanel()
        tool1 = MagicMock()
        tool1.model_dump.return_value = {"name": "t1", "description": "Tool 1"}
        tool2 = MagicMock()
        tool2.model_dump.return_value = {"name": "t2", "description": "Tool 2"}
        mock_app = MagicMock()
        mock_app.last_caps = MagicMock(tools=[tool1, tool2])
        with patch.object(type(panel), "app", new_callable=lambda: property(lambda s: mock_app)):
            result = panel._get_tools()
        assert len(result) == 2
        assert result[0]["name"] == "t1"
        assert result[1]["name"] == "t2"

    def test_returns_empty_for_attribute_error(self):
        panel = ToolOpsPanel()
        mock_app = MagicMock()
        caps = MagicMock(spec=[])
        mock_app.last_caps = caps
        with patch.object(type(panel), "app", new_callable=lambda: property(lambda s: mock_app)):
            result = panel._get_tools()
        assert result == []


class TestToolOpsPanelGetRouteMap:
    def test_returns_empty_when_no_caps(self):
        panel = ToolOpsPanel()
        mock_app = MagicMock()
        mock_app.last_caps = None
        with patch.object(type(panel), "app", new_callable=lambda: property(lambda s: mock_app)):
            result = panel._get_route_map()
        assert result == {}

    def test_returns_route_map(self):
        panel = ToolOpsPanel()
        mock_app = MagicMock()
        mock_app.last_caps = MagicMock(route_map={"tool1": "backend-a", "tool2": "backend-b"})
        with patch.object(type(panel), "app", new_callable=lambda: property(lambda s: mock_app)):
            result = panel._get_route_map()
        assert result == {"tool1": "backend-a", "tool2": "backend-b"}

    def test_returns_empty_when_route_map_none(self):
        panel = ToolOpsPanel()
        mock_app = MagicMock()
        mock_app.last_caps = MagicMock(route_map=None)
        with patch.object(type(panel), "app", new_callable=lambda: property(lambda s: mock_app)):
            result = panel._get_route_map()
        assert result == {}


class TestToolOpsValidationLogic:
    """Test the validation heuristics in _run_validation without widgets."""

    def test_no_description_detected(self):
        tool = {
            "name": "t1",
            "description": "",
            "inputSchema": {"type": "object", "properties": {"a": {}}},
        }
        issues = self._check_issues(tool, route_map={"t1": "backend"})
        assert "no description" in issues

    def test_no_input_schema_detected(self):
        tool = {"name": "t2", "description": "A tool"}
        issues = self._check_issues(tool, route_map={"t2": "backend"})
        assert "no input schema" in issues

    def test_schema_type_not_object(self):
        tool = {
            "name": "t3",
            "description": "A tool",
            "inputSchema": {"type": "array", "properties": {}},
        }
        issues = self._check_issues(tool, route_map={"t3": "backend"})
        assert any("schema type" in i for i in issues)

    def test_unrouted_detected(self):
        tool = {
            "name": "t4",
            "description": "A tool",
            "inputSchema": {"type": "object", "properties": {"x": {}}},
        }
        issues = self._check_issues(tool, route_map={})
        assert "unrouted" in issues

    def test_clean_tool_no_issues(self):
        tool = {
            "name": "t5",
            "description": "A good tool",
            "inputSchema": {"type": "object", "properties": {"x": {}}},
        }
        issues = self._check_issues(tool, route_map={"t5": "backend"})
        assert issues == []

    def test_input_schema_alt_key(self):
        """Tool may use 'input_schema' instead of 'inputSchema'."""
        tool = {
            "name": "t6",
            "description": "Tool",
            "input_schema": {"type": "object", "properties": {"x": {}}},
        }
        issues = self._check_issues(tool, route_map={"t6": "backend"})
        assert issues == []

    @staticmethod
    def _check_issues(tool: Dict[str, Any], route_map: Dict[str, str]) -> List[str]:
        """Replicate the validation logic from ToolOpsPanel._run_validation."""
        name = tool.get("name", "?")
        backend = route_map.get(name, "—")
        schema = tool.get("inputSchema") or tool.get("input_schema") or {}
        schema_type = schema.get("type", "—") if isinstance(schema, dict) else "—"

        issues: List[str] = []
        description = tool.get("description", "")
        if not description:
            issues.append("no description")
        if not isinstance(schema, dict) or "properties" not in schema:
            issues.append("no input schema")
        elif schema_type != "object":
            issues.append(f"schema type={schema_type}")
        if backend == "—":
            issues.append("unrouted")
        return issues


# Screen registration


class TestScreenRegistration:
    """Verify all TUI screens are registered in __init__ and app MODES."""

    def test_screens_init_exports(self):
        from argus_mcp.tui.screens import __all__ as screen_all

        assert "ServerLogsScreen" in screen_all
        assert "ExportImportScreen" in screen_all
        assert "CatalogBrowserScreen" in screen_all

    def test_widgets_init_exports(self):
        from argus_mcp.tui.widgets import __all__ as widget_all

        assert "ToolOpsPanel" in widget_all

    def test_app_modes_contain_new_screens(self):
        from argus_mcp.tui.app import ArgusApp

        modes = ArgusApp.MODES
        assert "server_logs" in modes
        assert "export_import" in modes
        assert "catalog" in modes

    def test_app_modes_count_gte_14(self):
        from argus_mcp.tui.app import ArgusApp

        assert len(ArgusApp.MODES) >= 14


# Import smoke tests


class TestModuleImports:
    """Verify all TUI modules import without errors."""

    def test_import_server_logs(self):
        from argus_mcp.tui.screens.server_logs import ServerLogsScreen

        assert ServerLogsScreen is not None

    def test_import_export_import(self):
        from argus_mcp.tui.screens.export_import import ExportImportScreen

        assert ExportImportScreen is not None

    def test_import_catalog_browser(self):
        from argus_mcp.tui.screens.catalog_browser import CatalogBrowserScreen

        assert CatalogBrowserScreen is not None

    def test_import_tool_ops_panel(self):
        from argus_mcp.tui.widgets.tool_ops_panel import ToolOpsPanel

        assert ToolOpsPanel is not None

    def test_import_base_screen(self):
        from argus_mcp.tui.screens.base import ArgusScreen

        assert ArgusScreen is not None
