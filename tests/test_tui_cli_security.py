"""Tests for argus_cli.tui.screens.security — SecurityScreen."""

from __future__ import annotations


def _import_security():
    return __import__("argus_cli.tui.screens.security", fromlist=["SecurityScreen"])


class TestSecurityScreenAttributes:
    """Verify class-level attributes without mounting."""

    def test_jump_targets(self):
        mod = _import_security()
        jt = mod.SecurityScreen.JUMP_TARGETS
        assert "security-tabs" in jt
        assert "secrets-panel-widget" in jt
        assert "network-panel-widget" in jt

    def test_jump_target_letters(self):
        mod = _import_security()
        jt = mod.SecurityScreen.JUMP_TARGETS
        assert jt["security-tabs"] == "t"
        assert jt["secrets-panel-widget"] == "s"
        assert jt["network-panel-widget"] == "n"

    def test_is_subclass_of_argus_screen(self):
        mod = _import_security()
        from argus_cli.tui.screens.base import ArgusScreen

        assert issubclass(mod.SecurityScreen, ArgusScreen)

    def test_initial_focus_not_set(self):
        """SecurityScreen does not set INITIAL_FOCUS."""
        mod = _import_security()
        assert mod.SecurityScreen.INITIAL_FOCUS is None

    def test_no_custom_bindings(self):
        """SecurityScreen does not define custom bindings."""
        mod = _import_security()
        # BINDINGS may be inherited or empty
        own_bindings = mod.SecurityScreen.__dict__.get("BINDINGS")
        assert own_bindings is None
