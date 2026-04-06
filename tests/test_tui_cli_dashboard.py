"""Tests for argus_cli.tui.screens.dashboard — DashboardScreen."""

from __future__ import annotations

import pytest

pytest.importorskip("argus_cli")


def _import_dashboard():
    """Import with heavy Textual deps mocked."""
    return __import__("argus_cli.tui.screens.dashboard", fromlist=["DashboardScreen"])


class TestDashboardScreenAttributes:
    """Verify class-level attributes without mounting."""

    def test_jump_targets(self):
        mod = _import_dashboard()
        assert "srv-selector" in mod.DashboardScreen.JUMP_TARGETS
        assert "backends-module" in mod.DashboardScreen.JUMP_TARGETS
        assert "main-area" in mod.DashboardScreen.JUMP_TARGETS
        assert "cap-section" in mod.DashboardScreen.JUMP_TARGETS

    def test_jump_target_values(self):
        mod = _import_dashboard()
        jt = mod.DashboardScreen.JUMP_TARGETS
        assert jt["srv-selector"] == "s"
        assert jt["backends-module"] == "b"
        assert jt["main-area"] == "e"
        assert jt["cap-section"] == "c"

    def test_is_subclass_of_argus_screen(self):
        mod = _import_dashboard()
        from argus_cli.tui.screens.base import ArgusScreen

        assert issubclass(mod.DashboardScreen, ArgusScreen)

    def test_initial_focus_not_set(self):
        """DashboardScreen does not set INITIAL_FOCUS (inherits None)."""
        mod = _import_dashboard()
        assert mod.DashboardScreen.INITIAL_FOCUS is None
