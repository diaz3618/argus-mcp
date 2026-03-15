"""Tests for argus_mcp.bridge.transport_factory — transport dispatch logic."""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp import StdioServerParameters

from argus_mcp.bridge.transport_factory import (
    _merge_headers,
    apply_network_env,
    create_transport_session,
)
from argus_mcp.errors import ConfigurationError

# apply_network_env ───────────────────────────────────────────────────


class TestApplyNetworkEnv:
    """Unit tests for proxy-injection logic."""

    def _params(self, env: Optional[Dict[str, str]] = None) -> StdioServerParameters:
        return StdioServerParameters(command="echo", args=["hi"], env=env)

    def test_no_network_section(self) -> None:
        p = self._params()
        result = apply_network_env("srv", {}, p)
        assert result is p  # unchanged identity

    def test_host_mode_passthrough(self) -> None:
        p = self._params()
        result = apply_network_env("srv", {"network": {"network_mode": "host"}}, p)
        assert result is p

    def test_none_mode_blocks_traffic(self) -> None:
        p = self._params(env={"EXISTING": "yes"})
        result = apply_network_env("srv", {"network": {"network_mode": "none"}}, p)
        assert result.env is not None
        assert result.env["HTTP_PROXY"] == "http://0.0.0.0:0"
        assert result.env["HTTPS_PROXY"] == "http://0.0.0.0:0"
        assert result.env["EXISTING"] == "yes"

    def test_bridge_mode_injects_proxy(self) -> None:
        conf: Dict[str, Any] = {
            "network": {
                "network_mode": "bridge",
                "http_proxy": "http://proxy:8080",
                "no_proxy": "localhost",
            }
        }
        result = apply_network_env("srv", conf, self._params())
        assert result.env is not None
        assert result.env["HTTP_PROXY"] == "http://proxy:8080"
        assert result.env["NO_PROXY"] == "localhost"

    def test_unknown_mode_passthrough(self) -> None:
        p = self._params()
        result = apply_network_env("srv", {"network": {"network_mode": "custom"}}, p)
        assert result is p


# _merge_headers ──────────────────────────────────────────────────────
# (Also tested in test_auth.py::TestMergeHeaders — kept minimal here.)


class TestMergeHeaders:
    def test_precedence(self) -> None:
        result = _merge_headers({"A": "old"}, {"A": "new"})
        assert result == {"A": "new"}


# create_transport_session ────────────────────────────────────────────


class TestCreateTransportSession:
    """Edge-case / error-path tests for the high-level dispatcher."""

    @pytest.mark.asyncio
    async def test_unsupported_type_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="Unsupported server type"):
            await create_transport_session(
                "srv",
                {},
                "grpc",  # unsupported
                None,
                AsyncMock(),
                MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_sse_missing_url_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="Invalid SSE 'url'"):
            await create_transport_session(
                "srv",
                {},  # no "url"
                "sse",
                None,
                AsyncMock(),
                MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_streamablehttp_missing_url_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="Invalid streamable-http 'url'"):
            await create_transport_session(
                "srv",
                {},
                "streamable-http",
                None,
                AsyncMock(),
                MagicMock(),
            )

    @pytest.mark.asyncio
    async def test_stdio_invalid_params_raises(self) -> None:
        with pytest.raises(ConfigurationError, match="type mismatch"):
            await create_transport_session(
                "srv",
                {"params": "not-a-StdioServerParameters"},
                "stdio",
                None,
                AsyncMock(),
                MagicMock(),
            )
