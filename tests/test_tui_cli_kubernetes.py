"""Tests for argus_cli.tui.screens.kubernetes — KubernetesScreen."""

from __future__ import annotations


def _import_kubernetes():
    return __import__("argus_cli.tui.screens.kubernetes", fromlist=["KubernetesScreen"])


class TestKubernetesScreenAttributes:
    """Verify class-level attributes without mounting."""

    def test_initial_focus(self):
        mod = _import_kubernetes()
        assert mod.KubernetesScreen.INITIAL_FOCUS == "#pod-dt"

    def test_jump_targets(self):
        mod = _import_kubernetes()
        jt = mod.KubernetesScreen.JUMP_TARGETS
        assert "kubernetes-tabs" in jt
        assert "pod-dt" in jt
        assert "pod-log" in jt

    def test_jump_target_letters(self):
        mod = _import_kubernetes()
        jt = mod.KubernetesScreen.JUMP_TARGETS
        assert jt["kubernetes-tabs"] == "t"
        assert jt["pod-dt"] == "k"
        assert jt["pod-log"] == "l"

    def test_bindings_exist(self):
        mod = _import_kubernetes()
        bindings = mod.KubernetesScreen.BINDINGS
        keys = [b[0] for b in bindings]
        assert "r" in keys
        assert "delete" in keys

    def test_is_subclass_of_argus_screen(self):
        mod = _import_kubernetes()
        from argus_cli.tui.screens.base import ArgusScreen

        assert issubclass(mod.KubernetesScreen, ArgusScreen)


class TestKubernetesParseKey:
    """Test the _parse_key helper method."""

    def test_parse_simple(self):
        mod = _import_kubernetes()
        screen = mod.KubernetesScreen.__new__(mod.KubernetesScreen)
        ns, name = screen._parse_key("default/my-pod")
        assert ns == "default"
        assert name == "my-pod"

    def test_parse_no_slash(self):
        mod = _import_kubernetes()
        screen = mod.KubernetesScreen.__new__(mod.KubernetesScreen)
        ns, name = screen._parse_key("standalone")
        assert ns == "standalone"
        assert name == ""

    def test_parse_multiple_slashes(self):
        mod = _import_kubernetes()
        screen = mod.KubernetesScreen.__new__(mod.KubernetesScreen)
        ns, name = screen._parse_key("kube-system/coredns/extra")
        assert ns == "kube-system"
        assert name == "coredns/extra"
