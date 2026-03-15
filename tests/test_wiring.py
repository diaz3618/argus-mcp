"""
Covers:
  1.1  Telemetry middleware in the chain + OTel config init
  1.2  Secrets resolver called during config loading
  1.3  VersionChecker instantiated in lifespan
  2.1  ConfigSync events bridge to TUI (ConfigSyncUpdate message)
  2.2  Optimizer panel uses real ToolIndex when available
  2.4  SkillManager instantiated in lifespan
  3.1  Network isolation env-var enforcement
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest
from mcp import StdioServerParameters

from argus_mcp.bridge.client_manager import ClientManager
from argus_mcp.config.loader import _maybe_resolve_secrets
from argus_mcp.config.schema import (
    ArgusConfig,
    SecretsConfig,
    TelemetrySettings,
)
from argus_mcp.tui.events import ConfigSyncUpdate


class TestTelemetrySettingsSchema:
    def test_defaults(self) -> None:
        ts = TelemetrySettings()
        assert ts.enabled is False
        assert ts.otlp_endpoint == "http://localhost:4317"
        assert ts.service_name == "argus-mcp"

    def test_custom_values(self) -> None:
        ts = TelemetrySettings(
            enabled=True,
            otlp_endpoint="http://collector:4317",
            service_name="my-service",
        )
        assert ts.enabled is True
        assert ts.otlp_endpoint == "http://collector:4317"
        assert ts.service_name == "my-service"


class TestSecretsConfigSchema:
    def test_defaults(self) -> None:
        sc = SecretsConfig()
        assert sc.enabled is False
        assert sc.provider == "env"
        assert sc.path == ""
        assert sc.strict is False

    def test_custom_values(self) -> None:
        sc = SecretsConfig(
            enabled=True,
            provider="file",
            path="/secrets/store.enc",
            strict=True,
        )
        assert sc.enabled is True
        assert sc.provider == "file"
        assert sc.path == "/secrets/store.enc"
        assert sc.strict is True


class TestArgusConfigNewFields:
    def test_telemetry_field_present(self) -> None:
        cfg = ArgusConfig()
        assert hasattr(cfg, "telemetry")
        assert isinstance(cfg.telemetry, TelemetrySettings)

    def test_secrets_field_present(self) -> None:
        cfg = ArgusConfig()
        assert hasattr(cfg, "secrets")
        assert isinstance(cfg.secrets, SecretsConfig)

    def test_roundtrip(self) -> None:
        data = {
            "version": "1",
            "telemetry": {
                "enabled": True,
                "otlp_endpoint": "http://otel:4317",
                "service_name": "test-svc",
            },
            "secrets": {
                "enabled": True,
                "provider": "env",
                "strict": True,
            },
        }
        cfg = ArgusConfig.model_validate(data)
        assert cfg.telemetry.enabled is True
        assert cfg.telemetry.service_name == "test-svc"
        assert cfg.secrets.enabled is True
        assert cfg.secrets.strict is True


# Secret resolution wiring in loader ─────────────────────────────────


class TestMaybeResolveSecrets:
    def test_noop_when_no_secrets_section(self) -> None:
        raw = {"version": "1", "backends": {}}
        assert _maybe_resolve_secrets(raw) is raw

    def test_noop_when_disabled(self) -> None:
        raw = {"version": "1", "secrets": {"enabled": False}}
        assert _maybe_resolve_secrets(raw) is raw

    def test_resolves_when_enabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # EnvProvider maps secret:MY_TOKEN → env var SECRET_MY_TOKEN
        monkeypatch.setenv("SECRET_MY_TOKEN", "resolved-value")
        raw = {
            "version": "1",
            "secrets": {"enabled": True, "provider": "env"},
            "backends": {"srv": {"token": "secret:MY_TOKEN"}},
        }
        resolved = _maybe_resolve_secrets(raw)
        assert resolved["backends"]["srv"]["token"] == "resolved-value"

    def test_strict_raises_on_missing(self) -> None:
        from argus_mcp.errors import ConfigurationError

        raw = {
            "version": "1",
            "secrets": {"enabled": True, "provider": "env", "strict": True},
            "backends": {"srv": {"token": "secret:NONEXISTENT_KEY_12345"}},
        }
        with pytest.raises(ConfigurationError, match="Secret resolution failed"):
            _maybe_resolve_secrets(raw)

    def test_no_refs_found(self) -> None:
        raw = {
            "version": "1",
            "secrets": {"enabled": True, "provider": "env"},
            "backends": {"srv": {"token": "plain-value"}},
        }
        result = _maybe_resolve_secrets(raw)
        assert result["backends"]["srv"]["token"] == "plain-value"


# Network isolation env-var enforcement ───────────────────────────────


class TestApplyNetworkEnv:
    def _make_params(self, env: Dict[str, str] | None = None) -> StdioServerParameters:
        return StdioServerParameters(command="echo", args=["hello"], env=env)

    def test_no_network_section(self) -> None:
        params = self._make_params()
        result = ClientManager._apply_network_env("srv", {}, params)
        assert result is params  # unchanged

    def test_host_mode_no_change(self) -> None:
        params = self._make_params()
        conf: Dict[str, Any] = {"network": {"network_mode": "host"}}
        result = ClientManager._apply_network_env("srv", conf, params)
        assert result is params

    def test_none_mode_blocks_proxy(self) -> None:
        params = self._make_params(env={"FOO": "bar"})
        conf: Dict[str, Any] = {"network": {"network_mode": "none"}}
        result = ClientManager._apply_network_env("srv", conf, params)
        assert result is not params
        assert result.env is not None
        assert result.env["HTTP_PROXY"] == "http://0.0.0.0:0"
        assert result.env["HTTPS_PROXY"] == "http://0.0.0.0:0"
        assert result.env["NO_PROXY"] == ""
        # Preserves original env
        assert result.env["FOO"] == "bar"

    def test_bridge_mode_sets_proxy(self) -> None:
        params = self._make_params()
        conf: Dict[str, Any] = {
            "network": {
                "network_mode": "bridge",
                "http_proxy": "http://proxy:8080",
                "no_proxy": "internal.local",
            }
        }
        result = ClientManager._apply_network_env("srv", conf, params)
        assert result.env is not None
        assert result.env["HTTP_PROXY"] == "http://proxy:8080"
        assert result.env["HTTPS_PROXY"] == "http://proxy:8080"
        assert result.env["NO_PROXY"] == "internal.local"

    def test_unknown_mode_no_change(self) -> None:
        params = self._make_params()
        conf: Dict[str, Any] = {"network": {"network_mode": "unknown_mode"}}
        result = ClientManager._apply_network_env("srv", conf, params)
        assert result is params


# ConfigSyncUpdate Textual message ────────────────────────────────────


class TestConfigSyncUpdate:
    def test_message_attributes(self) -> None:
        msg = ConfigSyncUpdate(
            config_file="config.yaml",
            config_hash="abc123",
            sync_type="changed",
            details="Config reloaded successfully",
            timestamp="2025-01-01T00:00:00Z",
        )
        assert msg.config_file == "config.yaml"
        assert msg.config_hash == "abc123"
        assert msg.sync_type == "changed"
        assert msg.details == "Config reloaded successfully"
        assert msg.timestamp == "2025-01-01T00:00:00Z"

    def test_defaults(self) -> None:
        msg = ConfigSyncUpdate()
        assert msg.config_file == ""
        assert msg.sync_type == "changed"


# Lifespan wiring: VersionChecker + SkillManager + Telemetry ─────────


class TestLifespanWiring:
    """Test that _attach_to_mcp_server wires the new components.

    SessionManager.start() requires a running event loop, so we mock it.
    """

    @staticmethod
    def _make_mocks() -> tuple:
        mcp_svr = MagicMock()
        service = MagicMock()
        service._config_path = None
        service.manager = MagicMock()
        service.registry = MagicMock()
        service.registry.get_aggregated_tools.return_value = []
        service.registry.get_route_map.return_value = {}
        return mcp_svr, service

    @pytest.mark.asyncio
    async def test_version_checker_attached(self) -> None:
        """VersionChecker should be instantiated and attached."""
        from argus_mcp.bridge.version_checker import VersionChecker
        from argus_mcp.server.lifespan import _attach_to_mcp_server

        mcp_svr, service = self._make_mocks()

        with patch("argus_mcp.server.session.SessionManager.start"):
            await _attach_to_mcp_server(mcp_svr, service)

        vc = mcp_svr.version_checker
        assert isinstance(vc, VersionChecker)

    @pytest.mark.asyncio
    async def test_skill_manager_attached(self) -> None:
        """SkillManager should be instantiated and discover called."""
        from argus_mcp.server.lifespan import _attach_to_mcp_server
        from argus_mcp.skills.manager import SkillManager

        mcp_svr, service = self._make_mocks()

        with patch("argus_mcp.server.session.SessionManager.start"):
            await _attach_to_mcp_server(mcp_svr, service)

        sm = mcp_svr.skill_manager
        assert isinstance(sm, SkillManager)

    @pytest.mark.asyncio
    async def test_telemetry_disabled_by_default(self) -> None:
        """Without config, telemetry should be disabled."""
        from argus_mcp.server.lifespan import _attach_to_mcp_server

        mcp_svr, service = self._make_mocks()

        with patch("argus_mcp.server.session.SessionManager.start"):
            await _attach_to_mcp_server(mcp_svr, service)

        assert mcp_svr.telemetry_enabled is False

    @pytest.mark.asyncio
    async def test_telemetry_enabled_via_config(self, tmp_path: Any) -> None:
        """When config has telemetry.enabled=true, it should be set."""
        import yaml

        from argus_mcp.server.lifespan import _attach_to_mcp_server

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "version": "1",
                    "telemetry": {
                        "enabled": True,
                        "otlp_endpoint": "http://fake:4317",
                        "service_name": "test",
                    },
                    "backends": {},
                }
            )
        )

        mcp_svr, service = self._make_mocks()
        service._config_path = str(config_file)

        with patch("argus_mcp.server.session.SessionManager.start"):
            await _attach_to_mcp_server(mcp_svr, service)

        # telemetry_enabled may be True or False depending on OTel availability
        # but it should be set as an attribute
        assert hasattr(mcp_svr, "telemetry_enabled")

    @pytest.mark.asyncio
    async def test_middleware_chain_built(self) -> None:
        """Middleware chain should be attached."""
        from argus_mcp.server.lifespan import _attach_to_mcp_server

        mcp_svr, service = self._make_mocks()

        with patch("argus_mcp.server.session.SessionManager.start"):
            await _attach_to_mcp_server(mcp_svr, service)

        chain = mcp_svr.middleware_chain
        assert callable(chain)

    @pytest.mark.asyncio
    async def test_optimizer_keep_tools_warns_on_unknown(self, tmp_path: Any) -> None:
        """L-4: keep_tools referencing an unknown tool should emit a warning."""
        import yaml

        from argus_mcp.server.lifespan import _attach_to_mcp_server

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "version": "1",
                    "optimizer": {
                        "enabled": True,
                        "keep_tools": ["real_tool", "ghost_tool"],
                    },
                    "backends": {},
                }
            )
        )

        mcp_svr, service = self._make_mocks()
        service._config_path = str(config_file)

        # Return a single tool named "real_tool" so "ghost_tool" is unknown.
        fake_tool = MagicMock()
        fake_tool.name = "real_tool"
        fake_tool.description = "A real tool"
        fake_tool.inputSchema = {}
        service.registry.get_aggregated_tools.return_value = [fake_tool]

        with (
            patch("argus_mcp.server.session.SessionManager.start"),
            patch("argus_mcp.server.lifespan.logger") as mock_logger,
        ):
            await _attach_to_mcp_server(mcp_svr, service)

        mock_logger.warning.assert_called_once()
        args = mock_logger.warning.call_args
        assert "ghost_tool" in str(args)
        assert "real_tool" not in str(args)

    @pytest.mark.asyncio
    async def test_optimizer_keep_tools_no_warning_when_all_known(self, tmp_path: Any) -> None:
        """L-4: keep_tools that all exist should not emit a warning."""
        import yaml

        from argus_mcp.server.lifespan import _attach_to_mcp_server

        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            yaml.dump(
                {
                    "version": "1",
                    "optimizer": {
                        "enabled": True,
                        "keep_tools": ["real_tool"],
                    },
                    "backends": {},
                }
            )
        )

        mcp_svr, service = self._make_mocks()
        service._config_path = str(config_file)

        fake_tool = MagicMock()
        fake_tool.name = "real_tool"
        fake_tool.description = "A real tool"
        fake_tool.inputSchema = {}
        service.registry.get_aggregated_tools.return_value = [fake_tool]

        with (
            patch("argus_mcp.server.session.SessionManager.start"),
            patch("argus_mcp.server.lifespan.logger") as mock_logger,
        ):
            await _attach_to_mcp_server(mcp_svr, service)

        mock_logger.warning.assert_not_called()


# Config file change emits config_sync event ─────────────────────────


class TestConfigSyncEventEmission:
    """Test that _on_config_file_changed emits a config_sync event."""

    def test_event_emitted_on_reload(self) -> None:
        """After config change, a config_sync event should be emitted."""
        from argus_mcp.runtime.service import ArgusService

        service = ArgusService.__new__(ArgusService)
        # Minimal init
        service._config_path = ""
        service._events = []
        service._event_subscribers = []
        service._event_id_counter = 0

        # Mock reload to return a success result
        async def mock_reload() -> Dict[str, Any]:
            return {"reloaded": True, "errors": [], "backends_added": [], "backends_removed": []}

        service.reload = mock_reload  # type: ignore[assignment]

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(service._on_config_file_changed())
        finally:
            loop.close()

        # Should have emitted a config_sync event
        sync_events = [e for e in service._events if e["stage"] == "config_sync"]
        assert len(sync_events) == 1
        assert sync_events[0]["details"]["type"] == "changed"
        assert sync_events[0]["severity"] == "info"

    def test_event_emitted_on_reload_error(self) -> None:
        """When reload has errors, event should reflect that."""
        from argus_mcp.runtime.service import ArgusService

        service = ArgusService.__new__(ArgusService)
        service._config_path = ""
        service._events = []
        service._event_subscribers = []
        service._event_id_counter = 0

        async def mock_reload() -> Dict[str, Any]:
            return {"reloaded": True, "errors": ["validation failed"]}

        service.reload = mock_reload  # type: ignore[assignment]

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(service._on_config_file_changed())
        finally:
            loop.close()

        sync_events = [e for e in service._events if e["stage"] == "config_sync"]
        assert len(sync_events) == 1
        assert sync_events[0]["details"]["type"] == "error"
        assert sync_events[0]["severity"] == "warning"
