"""Tests for argus_cli.tui.screens.containers — ContainersScreen."""

from __future__ import annotations


def _import_containers():
    return __import__("argus_cli.tui.screens.containers", fromlist=["ContainersScreen"])


class TestContainersScreenAttributes:
    """Verify class-level attributes without mounting."""

    def test_initial_focus(self):
        mod = _import_containers()
        assert mod.ContainersScreen.INITIAL_FOCUS == "#container-dt"

    def test_jump_targets(self):
        mod = _import_containers()
        jt = mod.ContainersScreen.JUMP_TARGETS
        assert "containers-tabs" in jt
        assert "container-dt" in jt
        assert "container-log" in jt
        assert "stats-cpu-bar" in jt

    def test_jump_target_letters(self):
        mod = _import_containers()
        jt = mod.ContainersScreen.JUMP_TARGETS
        assert jt["containers-tabs"] == "t"
        assert jt["container-dt"] == "c"

    def test_bindings_exist(self):
        mod = _import_containers()
        bindings = mod.ContainersScreen.BINDINGS
        keys = [b[0] for b in bindings]
        assert "r" in keys
        assert "delete" in keys

    def test_is_subclass_of_argus_screen(self):
        mod = _import_containers()
        from argus_cli.tui.screens.base import ArgusScreen

        assert issubclass(mod.ContainersScreen, ArgusScreen)
