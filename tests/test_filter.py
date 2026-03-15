"""Tests for argus_mcp.bridge.filter — Capability filtering with glob patterns.

Covers:
- CapabilityFilter with no patterns (pass-through)
- Allow-only patterns (glob matching)
- Deny-only patterns (deny overrides)
- Combined allow+deny (deny takes precedence)
- Glob pattern edge cases: wildcards, character classes, exact match
- is_active property
- build_filter factory
"""

from __future__ import annotations

from argus_mcp.bridge.filter import CapabilityFilter, build_filter


class TestCapabilityFilterPassthrough:
    """No filters configured → everything passes."""

    def test_no_patterns(self) -> None:
        f = CapabilityFilter()
        assert f.is_allowed("anything") is True
        assert f.is_allowed("") is True

    def test_is_active_false(self) -> None:
        f = CapabilityFilter()
        assert f.is_active is False

    def test_empty_lists(self) -> None:
        f = CapabilityFilter(allow=[], deny=[])
        assert f.is_allowed("tool") is True
        assert f.is_active is False


class TestCapabilityFilterAllow:
    """Allow-only patterns: name must match at least one."""

    def test_exact_match(self) -> None:
        f = CapabilityFilter(allow=["echo"])
        assert f.is_allowed("echo") is True
        assert f.is_allowed("search") is False

    def test_glob_wildcard(self) -> None:
        f = CapabilityFilter(allow=["db_*"])
        assert f.is_allowed("db_search") is True
        assert f.is_allowed("db_execute") is True
        assert f.is_allowed("search") is False

    def test_multiple_patterns(self) -> None:
        f = CapabilityFilter(allow=["echo", "search_*"])
        assert f.is_allowed("echo") is True
        assert f.is_allowed("search_web") is True
        assert f.is_allowed("delete") is False

    def test_question_mark_glob(self) -> None:
        f = CapabilityFilter(allow=["tool_?"])
        assert f.is_allowed("tool_a") is True
        assert f.is_allowed("tool_ab") is False

    def test_character_class_glob(self) -> None:
        f = CapabilityFilter(allow=["tool_[abc]"])
        assert f.is_allowed("tool_a") is True
        assert f.is_allowed("tool_d") is False

    def test_is_active_true(self) -> None:
        f = CapabilityFilter(allow=["something"])
        assert f.is_active is True


class TestCapabilityFilterDeny:
    """Deny-only patterns: denied names are hidden, all others pass."""

    def test_deny_exact(self) -> None:
        f = CapabilityFilter(deny=["dangerous_tool"])
        assert f.is_allowed("dangerous_tool") is False
        assert f.is_allowed("safe_tool") is True

    def test_deny_glob(self) -> None:
        f = CapabilityFilter(deny=["internal_*"])
        assert f.is_allowed("internal_debug") is False
        assert f.is_allowed("public_api") is True

    def test_is_active_true(self) -> None:
        f = CapabilityFilter(deny=["x"])
        assert f.is_active is True


class TestCapabilityFilterCombined:
    """Combined allow+deny: deny takes precedence over allow."""

    def test_deny_overrides_allow(self) -> None:
        f = CapabilityFilter(allow=["db_*"], deny=["db_drop"])
        assert f.is_allowed("db_search") is True
        assert f.is_allowed("db_drop") is False

    def test_deny_all_in_allow(self) -> None:
        """Denying everything that's allowed → nothing passes."""
        f = CapabilityFilter(allow=["tool_*"], deny=["tool_*"])
        assert f.is_allowed("tool_a") is False

    def test_allow_and_deny_disjoint(self) -> None:
        f = CapabilityFilter(allow=["read_*"], deny=["write_*"])
        assert f.is_allowed("read_file") is True
        assert f.is_allowed("write_file") is False
        assert f.is_allowed("other") is False  # not in allow list


class TestBuildFilter:
    def test_default(self) -> None:
        f = build_filter()
        assert isinstance(f, CapabilityFilter)
        assert f.is_active is False

    def test_with_allow(self) -> None:
        f = build_filter(allow=["tool_*"])
        assert f.is_allowed("tool_x") is True

    def test_with_deny(self) -> None:
        f = build_filter(deny=["bad_*"])
        assert f.is_allowed("bad_tool") is False

    def test_with_both(self) -> None:
        f = build_filter(allow=["a_*"], deny=["a_secret"])
        assert f.is_allowed("a_public") is True
        assert f.is_allowed("a_secret") is False


class TestFilterEdgeCases:
    """Boundary and edge-case tests for filter patterns."""

    def test_empty_string_name(self) -> None:
        f = CapabilityFilter(allow=["*"])
        assert f.is_allowed("") is True

    def test_allow_star_matches_everything(self) -> None:
        f = CapabilityFilter(allow=["*"])
        assert f.is_allowed("anything_at_all") is True
        assert f.is_allowed("") is True

    def test_deny_star_blocks_everything(self) -> None:
        f = CapabilityFilter(deny=["*"])
        assert f.is_allowed("anything") is False

    def test_case_sensitive_matching(self) -> None:
        """fnmatch is case-sensitive on Unix."""
        f = CapabilityFilter(allow=["Tool"])
        assert f.is_allowed("Tool") is True
        assert f.is_allowed("tool") is False

    def test_special_characters_in_name(self) -> None:
        f = CapabilityFilter(allow=["my-tool.v2"])
        assert f.is_allowed("my-tool.v2") is True
        assert f.is_allowed("my-toolXv2") is False
