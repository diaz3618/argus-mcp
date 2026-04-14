"""Tests for argus_mcp.config.migration — environment variable expansion.

Covers:
- string substitution (present env vars)
- unset env vars left unchanged
- recursive dict / list / nested walking
- non-string leaves returned as-is
- multiple vars in one string
- recursion depth limit
"""

from __future__ import annotations

import pytest

from argus_mcp.config.migration import expand_env_vars


class TestExpandEnvVars:
    def test_simple_string(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "hello")
        assert expand_env_vars("${MY_VAR}") == "hello"

    def test_unset_var_left_unchanged(self, monkeypatch):
        monkeypatch.delenv("UNDEFINED_XYZ", raising=False)
        assert expand_env_vars("${UNDEFINED_XYZ}") == "${UNDEFINED_XYZ}"

    def test_partial_string(self, monkeypatch):
        monkeypatch.setenv("HOST", "localhost")
        assert expand_env_vars("http://${HOST}:9000") == "http://localhost:9000"

    def test_multiple_vars(self, monkeypatch):
        monkeypatch.setenv("A", "1")
        monkeypatch.setenv("B", "2")
        assert expand_env_vars("${A}-${B}") == "1-2"

    def test_dict_recursive(self, monkeypatch):
        monkeypatch.setenv("K", "val")
        result = expand_env_vars({"key": "${K}", "other": "plain"})
        assert result == {"key": "val", "other": "plain"}

    def test_list_recursive(self, monkeypatch):
        monkeypatch.setenv("X", "expanded")
        result = expand_env_vars(["${X}", "static"])
        assert result == ["expanded", "static"]

    def test_nested_structure(self, monkeypatch):
        monkeypatch.setenv("PORT", "8080")
        val = {"server": {"bind": "0.0.0.0:${PORT}", "workers": 4}}
        result = expand_env_vars(val)
        assert result == {"server": {"bind": "0.0.0.0:8080", "workers": 4}}

    def test_int_passthrough(self):
        assert expand_env_vars(42) == 42

    def test_none_passthrough(self):
        assert expand_env_vars(None) is None

    def test_bool_passthrough(self):
        assert expand_env_vars(True) is True

    def test_float_passthrough(self):
        assert expand_env_vars(3.14) == 3.14

    def test_empty_string(self):
        assert expand_env_vars("") == ""

    def test_no_placeholder(self):
        assert expand_env_vars("hello world") == "hello world"

    def test_dollar_without_braces(self):
        """$VAR without braces should NOT be expanded."""
        assert expand_env_vars("$NOT_EXPANDED") == "$NOT_EXPANDED"

    def test_list_with_mixed_types(self, monkeypatch):
        monkeypatch.setenv("Z", "zval")
        result = expand_env_vars(["${Z}", 42, None, True])
        assert result == ["zval", 42, None, True]


class TestExpandEnvVarsDepthLimit:
    def test_depth_limit_exceeded(self):
        nested: dict = {"leaf": "val"}
        for _ in range(25):
            nested = {"child": nested}
        with pytest.raises(ValueError, match="recursion depth limit"):
            expand_env_vars(nested)

    def test_normal_depth_succeeds(self):
        nested: dict = {"leaf": "val"}
        for _ in range(15):
            nested = {"child": nested}
        result = expand_env_vars(nested)
        assert result is not None
