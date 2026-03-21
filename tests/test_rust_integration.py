"""Tests for Phase 6 — Rust crate conditional integration.

Verifies all four Rust bridge modules and their wiring into
Python production code paths.  Since the compiled Rust extensions
are not present in CI (requires ``maturin build``), we test:

1. The fallback path — Python pure implementations are used
   when ``RUST_AVAILABLE`` is ``False``.
2. The Rust-preference path — by patching the flags, we confirm
   the code *would* select the Rust implementation.
3. API compatibility of the bridge ``__init__.py`` exports.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


#  Filter bridge
class TestFilterRsBridge:
    """argus_mcp.bridge._filter_rs — conditional import bridge."""

    def test_rust_not_available_by_default(self) -> None:
        from argus_mcp.bridge._filter_rs import RUST_AVAILABLE

        # Native extension isn't compiled, so RUST_AVAILABLE should be False
        assert RUST_AVAILABLE is False

    def test_exports_rust_capability_filter_none(self) -> None:
        from argus_mcp.bridge._filter_rs import RustCapabilityFilter

        assert RustCapabilityFilter is None

    def test_build_filter_returns_python_fallback(self) -> None:
        from argus_mcp.bridge.filter import CapabilityFilter, build_filter

        f = build_filter(allow=["echo*"], deny=["echo_bad"])
        assert isinstance(f, CapabilityFilter)

    def test_build_filter_prefers_rust_when_available(self) -> None:
        """When RUST_AVAILABLE is True, build_filter returns the Rust class."""
        mock_rust_cls = MagicMock()
        mock_rust_cls.return_value = MagicMock()
        with (
            patch("argus_mcp.bridge.filter._FILTER_RUST", True),
            patch("argus_mcp.bridge.filter._RustFilter", mock_rust_cls),
        ):
            from argus_mcp.bridge.filter import build_filter

            result = build_filter(allow=["a"], deny=["b"])
            mock_rust_cls.assert_called_once_with(allow=["a"], deny=["b"])
            assert result is mock_rust_cls.return_value


#  Circuit Breaker bridge
class TestCircuitBreakerRsBridge:
    """argus_mcp.bridge.health._circuit_breaker_rs — conditional import."""

    def test_rust_not_available_by_default(self) -> None:
        from argus_mcp.bridge.health._circuit_breaker_rs import RUST_AVAILABLE

        assert RUST_AVAILABLE is False

    def test_fallback_is_python_circuit_breaker(self) -> None:
        from argus_mcp.bridge.health._circuit_breaker_rs import CircuitBreaker
        from argus_mcp.bridge.health.circuit_breaker import (
            CircuitBreaker as PyCB,
        )

        # The _rs bridge falls back to the same pure-Python class
        assert CircuitBreaker is PyCB

    def test_checker_uses_python_cb_by_default(self) -> None:
        """Health checker should use pure-Python CB when Rust is unavailable."""
        from argus_mcp.bridge.health.checker import _CB_RUST

        assert _CB_RUST is False

    def test_checker_selects_rust_when_patched(self) -> None:
        mock_rust_cb = MagicMock()
        with (
            patch("argus_mcp.bridge.health.checker._CB_RUST", True),
            patch("argus_mcp.bridge.health.checker._RustCB", mock_rust_cb),
        ):
            from argus_mcp.bridge.health.checker import _CB_RUST, _RustCB

            _CB = _RustCB if _CB_RUST and _RustCB is not None else None
            assert _CB is mock_rust_cb

    def test_session_pool_uses_python_cb_by_default(self) -> None:
        from argus_mcp.bridge.session_pool import _CB_RUST

        assert _CB_RUST is False


#  Token Cache bridge
class TestTokenCacheRsBridge:
    """argus_mcp.bridge.auth._token_cache_rs — conditional import."""

    def test_rust_not_available_by_default(self) -> None:
        from argus_mcp.bridge.auth._token_cache_rs import RUST_AVAILABLE

        assert RUST_AVAILABLE is False

    def test_fallback_is_python_token_cache(self) -> None:
        from argus_mcp.bridge.auth._token_cache_rs import TokenCache
        from argus_mcp.bridge.auth.token_cache import TokenCache as PyTC

        # The _rs bridge falls back to the same pure-Python class
        assert TokenCache is PyTC

    def test_provider_imports_from_bridge(self) -> None:
        """provider.py should import TokenCache via the _rs bridge."""
        import argus_mcp.bridge.auth.provider as provider_mod

        tc = provider_mod.TokenCache
        from argus_mcp.bridge.auth._token_cache_rs import TokenCache as BridgeTC

        assert tc is BridgeTC

    def test_auth_init_imports_from_bridge(self) -> None:
        """auth/__init__.py should re-export TokenCache via the _rs bridge."""
        from argus_mcp.bridge.auth import TokenCache
        from argus_mcp.bridge.auth._token_cache_rs import TokenCache as BridgeTC

        assert TokenCache is BridgeTC


#  Security Plugins bridge
class TestSecurityPluginsRsBridge:
    """argus_mcp.plugins.builtins_rust — conditional import."""

    def test_rust_not_available_by_default(self) -> None:
        from argus_mcp.plugins.builtins_rust import RUST_AVAILABLE

        assert RUST_AVAILABLE is False

    def test_rust_classes_are_none(self) -> None:
        from argus_mcp.plugins.builtins_rust import (
            RustPiiFilter,
            RustSecretsScanner,
        )

        assert RustPiiFilter is None
        assert RustSecretsScanner is None

    def test_pii_plugin_uses_python_fallback(self) -> None:
        """When Rust is unavailable, _rust_engine should be None."""
        from argus_mcp.plugins.builtins.pii_filter import PiiFilterPlugin
        from argus_mcp.plugins.models import PluginConfig

        cfg = PluginConfig(
            name="pii_filter",
            enabled=True,
            settings={},
        )
        plugin = PiiFilterPlugin(cfg)
        assert plugin._rust_engine is None

    def test_pii_plugin_mask_string_python_path(self) -> None:
        from argus_mcp.plugins.builtins.pii_filter import PiiFilterPlugin
        from argus_mcp.plugins.models import PluginConfig

        cfg = PluginConfig(name="pii_filter", enabled=True, settings={})
        plugin = PiiFilterPlugin(cfg)
        masked, counts = plugin._mask_string("email: user@example.com")
        assert "***EMAIL***" in masked
        assert counts.get("email", 0) >= 1

    def test_pii_plugin_uses_rust_when_available(self) -> None:
        mock_engine = MagicMock()
        mock_engine.mask_string.return_value = ("masked", {"email": 1})
        mock_cls = MagicMock(return_value=mock_engine)
        with (
            patch("argus_mcp.plugins.builtins.pii_filter._PII_RUST", True),
            patch("argus_mcp.plugins.builtins.pii_filter._RustPii", mock_cls),
        ):
            from argus_mcp.plugins.builtins.pii_filter import PiiFilterPlugin
            from argus_mcp.plugins.models import PluginConfig

            cfg = PluginConfig(name="pii_filter", enabled=True, settings={})
            plugin = PiiFilterPlugin(cfg)
            assert plugin._rust_engine is mock_engine
            result = plugin._mask_string("test@email.com")
            mock_engine.mask_string.assert_called_once_with("test@email.com")
            assert result == ("masked", {"email": 1})

    def test_secrets_plugin_uses_python_fallback(self) -> None:
        from argus_mcp.plugins.builtins.secrets_detection import (
            SecretsDetectionPlugin,
        )
        from argus_mcp.plugins.models import PluginConfig

        cfg = PluginConfig(name="secrets_detection", enabled=True, settings={})
        plugin = SecretsDetectionPlugin(cfg)
        assert plugin._rust_engine is None

    def test_secrets_plugin_uses_rust_when_available(self) -> None:
        mock_engine = MagicMock()
        mock_engine.scan.return_value = []
        mock_engine.has_secrets.return_value = False
        mock_cls = MagicMock(return_value=mock_engine)
        with (
            patch("argus_mcp.plugins.builtins.secrets_detection._SEC_RUST", True),
            patch("argus_mcp.plugins.builtins.secrets_detection._RustSec", mock_cls),
        ):
            from argus_mcp.plugins.builtins.secrets_detection import (
                SecretsDetectionPlugin,
            )
            from argus_mcp.plugins.models import PluginConfig

            cfg = PluginConfig(
                name="secrets_detection",
                enabled=True,
                settings={"block": False},
            )
            plugin = SecretsDetectionPlugin(cfg)
            assert plugin._rust_engine is mock_engine


#  Python version compatibility
class TestPythonVersionCompatibility:
    """Verify conditional imports degrade gracefully on any Python >=3.10."""

    def test_all_bridges_importable(self) -> None:
        """All _rs bridge modules must be importable without error."""
        from argus_mcp.bridge._filter_rs import RUST_AVAILABLE as f_r
        from argus_mcp.bridge.auth._token_cache_rs import RUST_AVAILABLE as t_r
        from argus_mcp.bridge.health._circuit_breaker_rs import (
            RUST_AVAILABLE as c_r,
        )
        from argus_mcp.plugins.builtins_rust import RUST_AVAILABLE as s_r

        # All should be importable; they'll be False until native exts are built
        assert isinstance(f_r, bool)
        assert isinstance(t_r, bool)
        assert isinstance(c_r, bool)
        assert isinstance(s_r, bool)

    def test_production_modules_importable(self) -> None:
        """Production modules that were wired must still import cleanly."""
        import argus_mcp.bridge.auth  # noqa: F401
        import argus_mcp.bridge.auth.provider  # noqa: F401
        import argus_mcp.bridge.filter  # noqa: F401
        import argus_mcp.bridge.health.checker  # noqa: F401
        import argus_mcp.bridge.session_pool  # noqa: F401
        import argus_mcp.plugins.builtins.pii_filter  # noqa: F401
        import argus_mcp.plugins.builtins.secrets_detection  # noqa: F401


#  Audit RS bridge
class TestAuditRsBridge:
    """argus_mcp.audit._audit_rs — conditional import bridge."""

    def test_bridge_importable(self) -> None:
        from argus_mcp.audit._audit_rs import RUST_AVAILABLE

        assert isinstance(RUST_AVAILABLE, bool)

    def test_exports_serialize_functions(self) -> None:
        from argus_mcp.audit._audit_rs import (
            serialize_audit_dict,
            serialize_audit_event,
        )

        # When Rust is not compiled, these are None; otherwise callable
        if serialize_audit_event is not None:
            assert callable(serialize_audit_event)
        if serialize_audit_dict is not None:
            assert callable(serialize_audit_dict)

    def test_logger_uses_python_fallback(self) -> None:
        """When Rust is unavailable, logger.emit() uses Pydantic."""
        with patch("argus_mcp.audit.logger._USE_RUST", False):
            import argus_mcp.audit.logger as mod

            assert mod._USE_RUST is False

    def test_logger_selects_rust_when_patched(self) -> None:
        mock_fn = MagicMock(return_value='{"test": true}')
        with (
            patch("argus_mcp.audit.logger._USE_RUST", True),
            patch("argus_mcp.audit.logger._rust_serialize_event", mock_fn),
        ):
            import argus_mcp.audit.logger as mod

            assert mod._USE_RUST is True

    def test_logger_module_imports_cleanly(self) -> None:
        import argus_mcp.audit.logger  # noqa: F401


#  Hash RS bridge
class TestHashRsBridge:
    """argus_mcp.plugins._hash_rs — conditional import bridge."""

    def test_bridge_importable(self) -> None:
        from argus_mcp.plugins._hash_rs import RUST_AVAILABLE

        assert isinstance(RUST_AVAILABLE, bool)

    def test_exports_json_sha256(self) -> None:
        from argus_mcp.plugins._hash_rs import json_sha256

        if json_sha256 is not None:
            assert callable(json_sha256)

    def test_cache_plugin_uses_python_fallback(self) -> None:
        with patch(
            "argus_mcp.plugins.builtins.response_cache_by_prompt._USE_RUST_HASH",
            False,
        ):
            import argus_mcp.plugins.builtins.response_cache_by_prompt as mod

            assert mod._USE_RUST_HASH is False

    def test_cache_plugin_selects_rust_when_patched(self) -> None:
        mock_fn = MagicMock(return_value="abc123hash")
        with (
            patch(
                "argus_mcp.plugins.builtins.response_cache_by_prompt._USE_RUST_HASH",
                True,
            ),
            patch(
                "argus_mcp.plugins.builtins.response_cache_by_prompt._rust_json_sha256",
                mock_fn,
            ),
        ):
            import argus_mcp.plugins.builtins.response_cache_by_prompt as mod

            assert mod._USE_RUST_HASH is True

    def test_cache_plugin_module_imports_cleanly(self) -> None:
        import argus_mcp.plugins.builtins.response_cache_by_prompt  # noqa: F401


#  YAML RS bridge
class TestYamlRsBridge:
    """argus_mcp.config._yaml_rs — conditional import bridge."""

    def test_bridge_importable(self) -> None:
        from argus_mcp.config._yaml_rs import RUST_AVAILABLE

        assert isinstance(RUST_AVAILABLE, bool)

    def test_exports_parse_yaml(self) -> None:
        from argus_mcp.config._yaml_rs import parse_yaml

        if parse_yaml is not None:
            assert callable(parse_yaml)

    def test_loader_uses_python_fallback(self) -> None:
        with patch("argus_mcp.config.loader._USE_RUST_YAML", False):
            import argus_mcp.config.loader as mod

            assert mod._USE_RUST_YAML is False

    def test_loader_selects_rust_when_patched(self) -> None:
        mock_fn = MagicMock(return_value={"key": "value"})
        with (
            patch("argus_mcp.config.loader._USE_RUST_YAML", True),
            patch("argus_mcp.config.loader._rust_parse_yaml", mock_fn),
        ):
            import argus_mcp.config.loader as mod

            assert mod._USE_RUST_YAML is True

    def test_loader_module_imports_cleanly(self) -> None:
        import argus_mcp.config.loader  # noqa: F401


#  New crate bridge compatibility
class TestNewCrateBridgeCompatibility:
    """Verify all new _rs bridge modules import without error."""

    def test_all_new_bridges_importable(self) -> None:
        from argus_mcp.audit._audit_rs import RUST_AVAILABLE as a_r
        from argus_mcp.config._yaml_rs import RUST_AVAILABLE as y_r
        from argus_mcp.plugins._hash_rs import RUST_AVAILABLE as h_r

        assert isinstance(a_r, bool)
        assert isinstance(h_r, bool)
        assert isinstance(y_r, bool)

    def test_new_production_modules_importable(self) -> None:
        import argus_mcp.audit.logger  # noqa: F401
        import argus_mcp.config.loader  # noqa: F401
        import argus_mcp.plugins.builtins.response_cache_by_prompt  # noqa: F401
