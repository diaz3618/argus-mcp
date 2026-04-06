"""Tests for argus_cli.tui.screens.health — HealthScreen."""

from __future__ import annotations


def _import_health():
    return __import__("argus_cli.tui.screens.health", fromlist=["HealthScreen"])


class TestHealthScreenAttributes:
    """Verify class-level attributes without mounting."""

    def test_jump_targets(self):
        mod = _import_health()
        jt = mod.HealthScreen.JUMP_TARGETS
        assert "health-tabs" in jt
        assert "health-panel-widget" in jt
        assert "sessions-panel-widget" in jt
        assert "version-drift-widget" in jt
        assert "server-groups-widget" in jt
        assert "health-latency-chart" in jt
        assert "health-trend-chart" in jt

    def test_jump_target_letters(self):
        mod = _import_health()
        jt = mod.HealthScreen.JUMP_TARGETS
        assert jt["health-tabs"] == "t"
        assert jt["health-panel-widget"] == "h"
        assert jt["sessions-panel-widget"] == "s"
        assert jt["version-drift-widget"] == "v"
        assert jt["server-groups-widget"] == "g"
        assert jt["health-latency-chart"] == "l"
        assert jt["health-trend-chart"] == "r"

    def test_bindings_exist(self):
        mod = _import_health()
        bindings = mod.HealthScreen.BINDINGS
        keys = [b[0] for b in bindings]
        assert "slash" in keys

    def test_is_subclass_of_argus_screen(self):
        mod = _import_health()
        from argus_cli.tui.screens.base import ArgusScreen

        assert issubclass(mod.HealthScreen, ArgusScreen)

    def test_initial_focus_not_set(self):
        """HealthScreen does not set INITIAL_FOCUS."""
        mod = _import_health()
        assert mod.HealthScreen.INITIAL_FOCUS is None
