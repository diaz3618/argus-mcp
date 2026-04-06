"""Tests for argus_cli.tui.screens.tools — ToolsScreen."""

from __future__ import annotations

import pytest

pytest.importorskip("argus_cli")


def _import_tools():
    return __import__("argus_cli.tui.screens.tools", fromlist=["ToolsScreen"])


class TestToolsScreenAttributes:
    """Verify class-level attributes without mounting."""

    def test_initial_focus(self):
        mod = _import_tools()
        assert mod.ToolsScreen.INITIAL_FOCUS == "#dt-tools"

    def test_jump_targets(self):
        mod = _import_tools()
        jt = mod.ToolsScreen.JUMP_TARGETS
        assert "tools-search" in jt
        assert "dt-tools" in jt
        assert "tools-detail-panel" in jt
        assert "tools-freq-chart" in jt

    def test_jump_target_letters(self):
        mod = _import_tools()
        jt = mod.ToolsScreen.JUMP_TARGETS
        assert jt["tools-search"] == "s"
        assert jt["dt-tools"] == "t"
        assert jt["tools-detail-panel"] == "d"

    def test_bindings_exist(self):
        mod = _import_tools()
        bindings = mod.ToolsScreen.BINDINGS
        keys = [b[0] for b in bindings]
        assert "slash" in keys
        assert "escape" in keys
        assert "c" in keys
        assert "f" in keys

    def test_is_subclass_of_argus_screen(self):
        mod = _import_tools()
        from argus_cli.tui.screens.base import ArgusScreen

        assert issubclass(mod.ToolsScreen, ArgusScreen)


class TestToolsItemMatches:
    """Test the static _item_matches helper."""

    def test_matches_name(self):
        mod = _import_tools()
        item = {"name": "read_file", "description": "Read a file from disk"}
        assert mod.ToolsScreen._item_matches(item, "read", ("name", "description"))

    def test_matches_description(self):
        mod = _import_tools()
        item = {"name": "read_file", "description": "Read a file from disk"}
        assert mod.ToolsScreen._item_matches(item, "disk", ("name", "description"))

    def test_no_match(self):
        mod = _import_tools()
        item = {"name": "read_file", "description": "Read a file from disk"}
        assert not mod.ToolsScreen._item_matches(item, "write", ("name", "description"))

    def test_case_insensitive(self):
        mod = _import_tools()
        item = {"name": "Read_File", "description": "something"}
        # The method compares against lowered field values; query is already lower
        assert mod.ToolsScreen._item_matches(item, "read_file", ("name",))

    def test_missing_field(self):
        mod = _import_tools()
        item = {"name": "tool_x"}
        assert not mod.ToolsScreen._item_matches(item, "desc", ("description",))

    def test_none_field_value(self):
        mod = _import_tools()
        item = {"name": "tool_x", "description": None}
        assert not mod.ToolsScreen._item_matches(item, "anything", ("description",))

    def test_empty_query(self):
        mod = _import_tools()
        item = {"name": "tool_x"}
        # Empty string is in every string
        assert mod.ToolsScreen._item_matches(item, "", ("name",))

    def test_original_name_field(self):
        mod = _import_tools()
        item = {"name": "renamed_tool", "original_name": "original_tool"}
        assert mod.ToolsScreen._item_matches(item, "original", ("name", "original_name"))
