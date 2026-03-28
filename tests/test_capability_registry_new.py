"""Tests for argus_mcp.bridge.capability_registry — Capability discovery and routing.

Covers:
- resolve_capability happy path and miss
- get_aggregated_tools/resources/prompts return copies
- remove_backend removes all entries for a server
- get_route_map returns a copy
- discover_and_register end-to-end with mock sessions
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus_mcp.bridge.capability_registry import CapabilityRegistry
from argus_mcp.bridge.conflict import (
    PrefixStrategy,
)


def _mock_tool(name: str, description: str = "") -> MagicMock:
    """Create a MagicMock that looks like an mcp_types.Tool."""
    t = MagicMock()
    t.name = name
    t.description = description
    t.model_copy = MagicMock(
        side_effect=lambda update: _mock_tool(
            update.get("name", name),
            update.get("description", description),
        )
    )
    return t


def _mock_resource(name: str) -> MagicMock:
    r = MagicMock()
    r.name = name
    r.uri = name
    r.model_copy = MagicMock(
        side_effect=lambda update: _mock_resource(
            update.get("name", name),
        )
    )
    return r


def _mock_prompt(name: str) -> MagicMock:
    p = MagicMock()
    p.name = name
    p.model_copy = MagicMock(
        side_effect=lambda update: _mock_prompt(
            update.get("name", name),
        )
    )
    return p


def _make_session(tools=None, resources=None, prompts=None) -> AsyncMock:
    """Create a mock ClientSession that returns specified capabilities."""
    session = AsyncMock()

    # list_tools returns an object with .tools attr
    tools_result = MagicMock()
    tools_result.tools = tools or []
    session.list_tools = AsyncMock(return_value=tools_result)

    resources_result = MagicMock()
    resources_result.resources = resources or []
    session.list_resources = AsyncMock(return_value=resources_result)

    prompts_result = MagicMock()
    prompts_result.prompts = prompts or []
    session.list_prompts = AsyncMock(return_value=prompts_result)

    return session


class TestCapabilityRegistryInit:
    def test_defaults(self) -> None:
        reg = CapabilityRegistry()
        assert reg.get_aggregated_tools() == []
        assert reg.get_aggregated_resources() == []
        assert reg.get_aggregated_prompts() == []
        assert reg.get_route_map() == {}

    def test_custom_strategy(self) -> None:
        strategy = PrefixStrategy()
        reg = CapabilityRegistry(conflict_strategy=strategy)
        assert reg._strategy is strategy


class TestResolveCapability:
    def test_existing(self) -> None:
        reg = CapabilityRegistry()
        reg._route_map["echo"] = ("backend-1", "echo")
        result = reg.resolve_capability("echo")
        assert result == ("backend-1", "echo")

    def test_missing(self) -> None:
        reg = CapabilityRegistry()
        assert reg.resolve_capability("nonexistent") is None

    def test_renamed(self) -> None:
        reg = CapabilityRegistry()
        reg._route_map["backend-1__echo"] = ("backend-1", "echo")
        result = reg.resolve_capability("backend-1__echo")
        assert result == ("backend-1", "echo")


class TestRemoveBackend:
    def test_remove_all_for_server(self) -> None:
        reg = CapabilityRegistry()
        reg._route_map["a"] = ("svr1", "a")
        reg._route_map["b"] = ("svr1", "b")
        reg._route_map["c"] = ("svr2", "c")

        t1 = _mock_tool("a")
        t2 = _mock_tool("b")
        t3 = _mock_tool("c")
        reg._tools = [t1, t2, t3]

        removed = reg.remove_backend("svr1")
        assert removed == 2
        assert len(reg._tools) == 1
        assert reg._tools[0].name == "c"
        assert "a" not in reg._route_map
        assert "b" not in reg._route_map
        assert "c" in reg._route_map

    def test_remove_nonexistent_server(self) -> None:
        reg = CapabilityRegistry()
        removed = reg.remove_backend("ghost")
        assert removed == 0


class TestGetAggregatedCopies:
    def test_tools_returns_copy(self) -> None:
        reg = CapabilityRegistry()
        t = _mock_tool("x")
        reg._tools = [t]
        result = reg.get_aggregated_tools()
        result.clear()
        assert len(reg._tools) == 1

    def test_resources_returns_copy(self) -> None:
        reg = CapabilityRegistry()
        r = _mock_resource("x")
        reg._resources = [r]
        result = reg.get_aggregated_resources()
        result.clear()
        assert len(reg._resources) == 1

    def test_prompts_returns_copy(self) -> None:
        reg = CapabilityRegistry()
        p = _mock_prompt("x")
        reg._prompts = [p]
        result = reg.get_aggregated_prompts()
        result.clear()
        assert len(reg._prompts) == 1

    def test_route_map_returns_copy(self) -> None:
        reg = CapabilityRegistry()
        reg._route_map["x"] = ("svr", "x")
        m = reg.get_route_map()
        m.clear()
        assert len(reg._route_map) == 1


class TestDiscoverAndRegister:
    @pytest.mark.asyncio
    async def test_single_backend_tools(self) -> None:
        """Discover tools from a single backend."""
        tool1 = _mock_tool("search")
        tool2 = _mock_tool("echo")
        session = _make_session(tools=[tool1, tool2])

        # Patch mcp_types so isinstance checks work
        with patch("argus_mcp.bridge.capability_registry.mcp_types") as mock_types:
            mock_types.Tool = MagicMock
            mock_types.Resource = MagicMock
            mock_types.Prompt = MagicMock
            mock_types.Error = Exception

            reg = CapabilityRegistry()
            await reg.discover_and_register({"svr1": session})

        assert len(reg.get_aggregated_tools()) == 2
        route = reg.resolve_capability("search")
        assert route == ("svr1", "search")

    @pytest.mark.asyncio
    async def test_skips_none_sessions(self) -> None:
        with patch("argus_mcp.bridge.capability_registry.mcp_types") as mock_types:
            mock_types.Tool = MagicMock
            mock_types.Resource = MagicMock
            mock_types.Prompt = MagicMock

            reg = CapabilityRegistry()
            await reg.discover_and_register({"svr1": None})

        assert len(reg.get_aggregated_tools()) == 0

    @pytest.mark.asyncio
    async def test_clears_previous_state(self) -> None:
        """discover_and_register clears tools/resources/prompts/routes before re-discovering."""
        reg = CapabilityRegistry()
        reg._tools = [_mock_tool("old")]
        reg._route_map["old"] = ("svr", "old")

        with patch("argus_mcp.bridge.capability_registry.mcp_types") as mock_types:
            mock_types.Tool = MagicMock
            mock_types.Resource = MagicMock
            mock_types.Prompt = MagicMock

            session = _make_session()  # empty
            await reg.discover_and_register({"svr1": session})

        assert len(reg.get_aggregated_tools()) == 0
        assert reg.resolve_capability("old") is None

    @pytest.mark.asyncio
    async def test_timeout_is_handled(self) -> None:
        """Timeout during list_tools should not crash discovery."""
        session = AsyncMock()
        session.list_tools = AsyncMock(side_effect=asyncio.TimeoutError())
        session.list_resources = AsyncMock(side_effect=asyncio.TimeoutError())
        session.list_prompts = AsyncMock(side_effect=asyncio.TimeoutError())

        with patch("argus_mcp.bridge.capability_registry.mcp_types") as mock_types:
            mock_types.Tool = MagicMock
            mock_types.Resource = MagicMock
            mock_types.Prompt = MagicMock
            mock_types.Error = Exception

            reg = CapabilityRegistry()
            # Should not raise
            await reg.discover_and_register({"svr1": session})

        assert len(reg.get_aggregated_tools()) == 0


class TestDiscoverSingleBackend:
    @pytest.mark.asyncio
    async def test_rediscover_after_removal(self) -> None:
        """discover_single_backend re-adds capabilities for a recovered backend."""
        tool = _mock_tool("echo")
        session = _make_session(tools=[tool])

        with patch("argus_mcp.bridge.capability_registry.mcp_types") as mock_types:
            mock_types.Tool = MagicMock
            mock_types.Resource = MagicMock
            mock_types.Prompt = MagicMock
            mock_types.Error = Exception

            reg = CapabilityRegistry()
            await reg.discover_single_backend("svr1", session)

        assert len(reg.get_aggregated_tools()) == 1
        assert reg.resolve_capability("echo") is not None
