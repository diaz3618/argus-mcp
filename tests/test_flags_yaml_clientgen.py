"""Tests for FeatureFlags and YAML config loading"""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from argus_mcp.config.flags import _DEFAULTS, FeatureFlags

# FeatureFlags


class TestFeatureFlagsDefaults:
    """Verify default flag values when no overrides supplied."""

    def test_defaults_applied(self):
        ff = FeatureFlags()
        for name, expected in _DEFAULTS.items():
            assert ff.is_enabled(name) is expected

    def test_unknown_flag_returns_false(self):
        ff = FeatureFlags()
        assert ff.is_enabled("nonexistent_flag") is False

    def test_all_flags_returns_copy(self):
        ff = FeatureFlags()
        flags = ff.all_flags()
        assert flags == _DEFAULTS
        # Mutation should not affect internal state
        flags["optimizer"] = True
        assert ff.is_enabled("optimizer") is False


class TestFeatureFlagsOverrides:
    """Verify user overrides are applied correctly."""

    def test_override_existing_flag(self):
        ff = FeatureFlags({"optimizer": True})
        assert ff.is_enabled("optimizer") is True

    def test_override_multiple_flags(self):
        ff = FeatureFlags({"optimizer": True, "hot_reload": False})
        assert ff.is_enabled("optimizer") is True
        assert ff.is_enabled("hot_reload") is False

    def test_disable_default_on_flag(self):
        ff = FeatureFlags({"session_management": False})
        assert ff.is_enabled("session_management") is False

    def test_unknown_override_accepted(self):
        ff = FeatureFlags({"future_flag": True})
        assert ff.is_enabled("future_flag") is True

    def test_non_bool_override_skipped(self):
        ff = FeatureFlags({"optimizer": "yes"})  # type: ignore[dict-item]
        # Non-bool value should be skipped, default applies
        assert ff.is_enabled("optimizer") is False

    def test_none_overrides(self):
        ff = FeatureFlags(None)
        assert ff.all_flags() == _DEFAULTS


class TestFeatureFlagsRepr:
    """Verify string representation."""

    def test_repr_shows_enabled(self):
        ff = FeatureFlags({"optimizer": True, "hot_reload": False})
        r = repr(ff)
        assert "FeatureFlags" in r
        assert "optimizer" in r
        assert "hot_reload" not in r  # hot_reload is disabled


# YAML config loading


class TestReadConfigFile:
    """Test the _read_config_file helper for YAML."""

    def test_yaml_file(self):
        """YAML loading works."""
        from argus_mcp.config.loader import _read_config_file

        content = "version: v1\nbackends:\n  test:\n    type: stdio\n    command: echo\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write(content)
            f.flush()
            path = f.name

        try:
            result = _read_config_file(path)
            assert result["version"] == "v1"
            assert "test" in result["backends"]
        finally:
            os.unlink(path)

    def test_yml_extension(self):
        """The .yml extension is also recognized."""
        from argus_mcp.config.loader import _read_config_file

        content = "version: v1\nbackends: {}\n"
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yml", delete=False) as f:
            f.write(content)
            f.flush()
            path = f.name

        try:
            result = _read_config_file(path)
            assert result["version"] == "v1"
        finally:
            os.unlink(path)

    def test_unsupported_extension_raises(self):
        """A non-YAML extension raises ConfigurationError."""
        from argus_mcp.config.loader import _read_config_file
        from argus_mcp.errors import ConfigurationError

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{}")
            f.flush()
            path = f.name

        try:
            with pytest.raises(ConfigurationError, match="Unsupported config file extension"):
                _read_config_file(path)
        finally:
            os.unlink(path)

    def test_non_dict_raises(self):
        """A YAML list at the top level raises ConfigurationError."""
        from argus_mcp.config.loader import _read_config_file
        from argus_mcp.errors import ConfigurationError

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("- 1\n- 2\n- 3\n")
            f.flush()
            path = f.name

        try:
            with pytest.raises(ConfigurationError, match="dictionary"):
                _read_config_file(path)
        finally:
            os.unlink(path)


# Client config generator


class TestClientConfigGenerator:
    """Test generate_client_config for all supported clients."""

    def test_claude_desktop_sse(self):
        from argus_mcp.config.client_gen import generate_client_config

        result = json.loads(generate_client_config("claude-desktop"))
        assert "mcpServers" in result
        server = result["mcpServers"]["argus-mcp"]
        assert server["url"] == "http://127.0.0.1:9000/sse"
        assert server["transport"] == "sse"

    def test_claude_desktop_streamable_http(self):
        from argus_mcp.config.client_gen import generate_client_config

        result = json.loads(generate_client_config("claude-desktop", transport="streamable-http"))
        server = result["mcpServers"]["argus-mcp"]
        assert server["url"] == "http://127.0.0.1:9000/mcp"
        assert server["transport"] == "streamable-http"

    def test_cursor(self):
        from argus_mcp.config.client_gen import generate_client_config

        result = json.loads(generate_client_config("cursor"))
        server = result["mcpServers"]["argus-mcp"]
        assert "url" in server

    def test_vscode(self):
        from argus_mcp.config.client_gen import generate_client_config

        result = json.loads(generate_client_config("vscode"))
        server = result["mcp"]["servers"]["argus-mcp"]
        assert server["type"] == "sse"
        assert "/sse" in server["url"]

    def test_claude_code(self):
        from argus_mcp.config.client_gen import generate_client_config

        result = json.loads(generate_client_config("claude-code"))
        server = result["mcpServers"]["argus-mcp"]
        assert server["type"] == "sse"

    def test_custom_host_port(self):
        from argus_mcp.config.client_gen import generate_client_config

        result = json.loads(generate_client_config("claude-desktop", host="0.0.0.0", port=8080))
        server = result["mcpServers"]["argus-mcp"]
        assert "0.0.0.0:8080" in server["url"]

    def test_custom_server_name(self):
        from argus_mcp.config.client_gen import generate_client_config

        result = json.loads(generate_client_config("claude-desktop", server_name="my-proxy"))
        assert "my-proxy" in result["mcpServers"]
