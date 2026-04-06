"""Tests for argus_cli.tui.screens.skills — SkillsScreen and helpers."""

from __future__ import annotations


def _import_skills():
    return __import__("argus_cli.tui.screens.skills", fromlist=["SkillsScreen", "_trunc"])


class TestSkillsScreenAttributes:
    """Verify class-level attributes without mounting."""

    def test_initial_focus(self):
        mod = _import_skills()
        assert mod.SkillsScreen.INITIAL_FOCUS == "#skills-table"

    def test_jump_targets(self):
        mod = _import_skills()
        jt = mod.SkillsScreen.JUMP_TARGETS
        assert "skills-search" in jt
        assert "skills-table" in jt

    def test_jump_target_letters(self):
        mod = _import_skills()
        jt = mod.SkillsScreen.JUMP_TARGETS
        assert jt["skills-search"] == "s"
        assert jt["skills-table"] == "t"

    def test_bindings_exist(self):
        mod = _import_skills()
        bindings = mod.SkillsScreen.BINDINGS
        keys = [b[0] for b in bindings]
        assert "escape" in keys
        assert "e" in keys
        assert "a" in keys
        assert "u" in keys
        assert "slash" in keys

    def test_is_subclass_of_argus_screen(self):
        mod = _import_skills()
        from argus_cli.tui.screens.base import ArgusScreen

        assert issubclass(mod.SkillsScreen, ArgusScreen)


class TestTruncHelper:
    """Test the module-level _trunc function."""

    def test_short_text(self):
        mod = _import_skills()
        assert mod._trunc("hello", 50) == "hello"

    def test_exact_length(self):
        mod = _import_skills()
        text = "a" * 50
        assert mod._trunc(text, 50) == text

    def test_long_text_truncated(self):
        mod = _import_skills()
        text = "a" * 60
        result = mod._trunc(text, 50)
        assert len(result) == 50
        assert result.endswith("…")

    def test_empty_text(self):
        mod = _import_skills()
        assert mod._trunc("", 50) == ""

    def test_none_like_empty(self):
        mod = _import_skills()
        # _trunc checks `if not text` first
        assert mod._trunc("", 10) == ""

    def test_custom_max_len(self):
        mod = _import_skills()
        text = "abcdefghij"  # 10 chars
        result = mod._trunc(text, 5)
        assert len(result) == 5
        assert result == "abcd…"


class TestCollectSkillBackends:
    """Test the static _collect_skill_backends method."""

    def test_empty_tools(self):
        mod = _import_skills()
        result = mod.SkillsScreen._collect_skill_backends([])
        assert result == {}

    def test_single_backend(self):
        mod = _import_skills()
        tools = [{"name": "tool1", "backend": "my-server"}]
        result = mod.SkillsScreen._collect_skill_backends(tools)
        assert "my-server" in result
        assert result["my-server"]["type"] == "stdio"
        assert "my_server" in result["my-server"]["command"]

    def test_duplicate_backends(self):
        mod = _import_skills()
        tools = [
            {"name": "tool1", "backend": "srv-a"},
            {"name": "tool2", "backend": "srv-a"},
        ]
        result = mod.SkillsScreen._collect_skill_backends(tools)
        assert len(result) == 1

    def test_multiple_backends(self):
        mod = _import_skills()
        tools = [
            {"name": "t1", "backend": "srv-a"},
            {"name": "t2", "backend": "srv-b"},
        ]
        result = mod.SkillsScreen._collect_skill_backends(tools)
        assert len(result) == 2
        assert "srv-a" in result
        assert "srv-b" in result

    def test_no_backend_key(self):
        mod = _import_skills()
        tools = [{"name": "t1"}]
        result = mod.SkillsScreen._collect_skill_backends(tools)
        assert result == {}

    def test_empty_backend_name(self):
        mod = _import_skills()
        tools = [{"name": "t1", "backend": ""}]
        result = mod.SkillsScreen._collect_skill_backends(tools)
        assert result == {}
