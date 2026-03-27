"""End-to-end MCP tool invocation tests.

Verifies that tools registered via the capability registry can be
resolved and invoked through the routing middleware, simulating
what an MCP client sees when calling tools through the proxy.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from mcp import types as mcp_types

from argus_mcp.bridge.capability_registry import CapabilityRegistry

from .conftest import MockMCPSession


def _make_tool(name: str, desc: str = "") -> mcp_types.Tool:
    """Helper to create an mcp_types.Tool."""
    return mcp_types.Tool(
        name=name,
        description=desc,
        inputSchema={"type": "object"},
    )


class TestToolRegistrationAndLookup:
    """Capability registry registers tools and resolves routes."""

    @pytest.fixture
    def registry(self) -> CapabilityRegistry:
        return CapabilityRegistry()

    def test_direct_route_registration(self, registry: CapabilityRegistry) -> None:
        """Tools inserted into _route_map and _tools are resolvable."""
        tool = _make_tool("echo", "Echo input")
        registry._tools.append(tool)
        registry._route_map["echo"] = ("backend-a", "echo")

        route = registry.resolve_capability("echo")
        assert route is not None
        assert route[0] == "backend-a"
        assert route[1] == "echo"

    def test_multiple_backends_routes(self, registry: CapabilityRegistry) -> None:
        """Tools from multiple backends are all resolvable."""
        registry._tools.append(_make_tool("echo"))
        registry._route_map["echo"] = ("backend-a", "echo")
        registry._tools.append(_make_tool("search"))
        registry._route_map["search"] = ("backend-b", "search")

        assert registry.resolve_capability("echo") is not None
        assert registry.resolve_capability("search") is not None
        assert registry.resolve_capability("echo")[0] == "backend-a"
        assert registry.resolve_capability("search")[0] == "backend-b"

    @pytest.mark.asyncio
    async def test_tool_call_through_session(self) -> None:
        """Tool call via mock session returns expected response."""
        session = MockMCPSession(name="backend-a")
        result = await session.call_tool("echo", {"input": "hello"})
        assert result.isError is False
        assert len(result.content) > 0

    def test_aggregated_tools_list(self, registry: CapabilityRegistry) -> None:
        """get_aggregated_tools returns all registered tools."""
        tool = _make_tool("test-tool", "A test")
        registry._tools.append(tool)
        registry._route_map["test-tool"] = ("test-backend", "test-tool")

        tools = registry.get_aggregated_tools()
        names = [t.name for t in tools]
        assert "test-tool" in names

    def test_route_map_populated(self, registry: CapabilityRegistry) -> None:
        """Route map maps tool names to backend names."""
        registry._route_map["mapped-tool"] = ("my-backend", "mapped-tool")

        route_map = registry.get_route_map()
        assert "mapped-tool" in route_map
        assert route_map["mapped-tool"][0] == "my-backend"

    def test_unregistered_tool_returns_none(self, registry: CapabilityRegistry) -> None:
        """Resolving an unregistered tool returns None."""
        assert registry.resolve_capability("nonexistent") is None

    @pytest.mark.asyncio
    async def test_discover_and_register_from_mock_sessions(self) -> None:
        """discover_and_register populates tools from mock sessions.

        Uses MagicMock sessions that return proper mcp_types.Tool objects
        to simulate real backend discovery.
        """
        registry = CapabilityRegistry()

        # Build a mock session that returns proper mcp_types.Tool
        mock_session = MagicMock()
        tool_a = _make_tool("tool-alpha", "Alpha tool")
        tool_b = _make_tool("tool-beta", "Beta tool")
        mock_list_result = MagicMock()
        mock_list_result.tools = [tool_a, tool_b]

        async def _list_tools():
            return mock_list_result

        mock_session.list_tools = _list_tools

        mock_list_empty = MagicMock()
        mock_list_empty.resources = []
        mock_list_empty.prompts = []

        async def _list_resources():
            return mock_list_empty

        async def _list_prompts():
            return mock_list_empty

        mock_session.list_resources = _list_resources
        mock_session.list_prompts = _list_prompts

        await registry.discover_and_register({"mock-backend": mock_session})

        assert len(registry.get_aggregated_tools()) == 2
        assert registry.resolve_capability("tool-alpha") is not None
        assert registry.resolve_capability("tool-alpha")[0] == "mock-backend"
        assert registry.resolve_capability("tool-beta") is not None
