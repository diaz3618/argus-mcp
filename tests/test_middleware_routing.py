"""Tests for argus_mcp.bridge.middleware.routing — Routing middleware.

Covers:
- Happy path: routes call_tool, read_resource, get_prompt to correct backend
- Context population (server_name, original_name)
- Missing registry/manager → BackendServerError
- Unknown capability → ValueError
- Missing session → RuntimeError
- Unsupported MCP method → NotImplementedError
- Timeout propagation
- Connection error propagation
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from argus_mcp.bridge.middleware.chain import RequestContext
from argus_mcp.bridge.middleware.routing import RoutingMiddleware
from argus_mcp.errors import BackendServerError


@pytest.fixture
def routing_deps():
    """Create registry + manager + session mocks for routing tests."""
    registry = MagicMock()
    manager = MagicMock()
    session = AsyncMock()

    # Default: resolve "echo" → ("backend-1", "echo")
    registry.resolve_capability = MagicMock(return_value=("backend-1", "echo"))
    manager.get_session = MagicMock(return_value=session)

    return registry, manager, session


class TestRoutingMiddlewareHappyPath:
    @pytest.mark.asyncio
    async def test_call_tool_routing(self, routing_deps: Any) -> None:
        registry, manager, session = routing_deps
        session.call_tool = AsyncMock(return_value="tool_result")

        mw = RoutingMiddleware(registry, manager)
        ctx = RequestContext(
            capability_name="echo",
            mcp_method="call_tool",
            arguments={"text": "hello"},
        )
        result = await mw(ctx)

        assert result == "tool_result"
        session.call_tool.assert_awaited_once_with(name="echo", arguments={"text": "hello"})
        assert ctx.server_name == "backend-1"
        assert ctx.original_name == "echo"

    @pytest.mark.asyncio
    async def test_read_resource_routing(self, routing_deps: Any) -> None:
        registry, manager, session = routing_deps
        registry.resolve_capability.return_value = ("backend-1", "file://data.txt")
        session.read_resource = AsyncMock(return_value="resource_data")

        mw = RoutingMiddleware(registry, manager)
        ctx = RequestContext(
            capability_name="file://data.txt",
            mcp_method="read_resource",
        )
        result = await mw(ctx)

        assert result == "resource_data"
        session.read_resource.assert_awaited_once_with(uri="file://data.txt")

    @pytest.mark.asyncio
    async def test_get_prompt_routing(self, routing_deps: Any) -> None:
        registry, manager, session = routing_deps
        registry.resolve_capability.return_value = ("backend-1", "my_prompt")
        session.get_prompt = AsyncMock(return_value="prompt_result")

        mw = RoutingMiddleware(registry, manager)
        ctx = RequestContext(
            capability_name="my_prompt",
            mcp_method="get_prompt",
            arguments={"key": "val"},
        )
        result = await mw(ctx)

        assert result == "prompt_result"
        session.get_prompt.assert_awaited_once_with(name="my_prompt", arguments={"key": "val"})

    @pytest.mark.asyncio
    async def test_call_tool_with_none_arguments(self, routing_deps: Any) -> None:
        """Arguments=None should be passed as empty dict."""
        registry, manager, session = routing_deps
        session.call_tool = AsyncMock(return_value="ok")

        mw = RoutingMiddleware(registry, manager)
        ctx = RequestContext(capability_name="echo", mcp_method="call_tool", arguments=None)
        await mw(ctx)

        session.call_tool.assert_awaited_once_with(name="echo", arguments={})


class TestRoutingMiddlewareErrors:
    @pytest.mark.asyncio
    async def test_no_registry(self) -> None:
        mw = RoutingMiddleware(None, MagicMock())
        ctx = RequestContext(capability_name="t", mcp_method="call_tool")
        with pytest.raises(BackendServerError, match="not initialized"):
            await mw(ctx)

    @pytest.mark.asyncio
    async def test_no_manager(self) -> None:
        mw = RoutingMiddleware(MagicMock(), None)
        ctx = RequestContext(capability_name="t", mcp_method="call_tool")
        with pytest.raises(BackendServerError, match="not initialized"):
            await mw(ctx)

    @pytest.mark.asyncio
    async def test_unknown_capability(self, routing_deps: Any) -> None:
        registry, manager, session = routing_deps
        registry.resolve_capability.return_value = None

        mw = RoutingMiddleware(registry, manager)
        ctx = RequestContext(capability_name="nonexistent", mcp_method="call_tool")
        with pytest.raises(ValueError, match="does not exist"):
            await mw(ctx)

    @pytest.mark.asyncio
    async def test_missing_session(self, routing_deps: Any) -> None:
        registry, manager, session = routing_deps
        manager.get_session.return_value = None

        mw = RoutingMiddleware(registry, manager)
        ctx = RequestContext(capability_name="echo", mcp_method="call_tool")
        with pytest.raises(RuntimeError, match="session missing"):
            await mw(ctx)

    @pytest.mark.asyncio
    async def test_unsupported_method(self, routing_deps: Any) -> None:
        registry, manager, session = routing_deps
        mw = RoutingMiddleware(registry, manager)
        ctx = RequestContext(capability_name="echo", mcp_method="unknown_method")
        with pytest.raises(NotImplementedError, match="unsupported method"):
            await mw(ctx)

    @pytest.mark.asyncio
    async def test_timeout_propagates(self, routing_deps: Any) -> None:
        registry, manager, session = routing_deps
        session.call_tool = AsyncMock(side_effect=asyncio.TimeoutError())

        mw = RoutingMiddleware(registry, manager)
        ctx = RequestContext(capability_name="echo", mcp_method="call_tool")
        with pytest.raises(asyncio.TimeoutError):
            await mw(ctx)

    @pytest.mark.asyncio
    async def test_connection_error_propagates(self, routing_deps: Any) -> None:
        registry, manager, session = routing_deps
        session.call_tool = AsyncMock(side_effect=ConnectionError("lost"))

        mw = RoutingMiddleware(registry, manager)
        ctx = RequestContext(capability_name="echo", mcp_method="call_tool")
        with pytest.raises(ConnectionError):
            await mw(ctx)

    @pytest.mark.asyncio
    async def test_broken_pipe_propagates(self, routing_deps: Any) -> None:
        registry, manager, session = routing_deps
        session.call_tool = AsyncMock(side_effect=BrokenPipeError("pipe broken"))

        mw = RoutingMiddleware(registry, manager)
        ctx = RequestContext(capability_name="echo", mcp_method="call_tool")
        with pytest.raises(BrokenPipeError):
            await mw(ctx)
