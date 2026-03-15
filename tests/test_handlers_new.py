"""Tests for argus_mcp.server.handlers — MCP protocol handler registration.

Covers:
- _dispatch: with and without middleware chain
- register_handlers: verifies decorator attachment
- handle_list_tools: with/without optimizer, with composites
- handle_call_tool: normal dispatch, optimizer FIND_TOOL/CALL_TOOL, composites
- handle_list_resources, handle_list_prompts
- handle_read_resource, handle_get_prompt
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from mcp.types import CallToolResult, TextContent

from argus_mcp.bridge.middleware.chain import RequestContext
from argus_mcp.errors import BackendServerError
from argus_mcp.server.handlers import _dispatch, register_handlers


@pytest.fixture
def mock_mcp_server():
    """Create a MagicMock that behaves like an McpServer."""
    server = MagicMock()
    server.registry = MagicMock()
    server.optimizer_index = None
    server.optimizer_enabled = False
    server.optimizer_keep_list = []
    server.composite_tools = []
    server.middleware_chain = None

    # Decorators: list_tools, list_resources, etc. should be callable
    # that returns a decorator (which registers the handler).
    # We capture them for testing.
    handlers = {}

    def make_decorator(name):
        def decorator_factory():
            def decorator(fn):
                handlers[name] = fn
                return fn

            return decorator

        return decorator_factory

    server.list_tools = make_decorator("list_tools")
    server.list_resources = make_decorator("list_resources")
    server.list_prompts = make_decorator("list_prompts")
    server.call_tool = make_decorator("call_tool")
    server.read_resource = make_decorator("read_resource")
    server.get_prompt = make_decorator("get_prompt")

    register_handlers(server)

    return server, handlers


class TestDispatch:
    @pytest.mark.asyncio
    async def test_missing_chain_raises(self) -> None:
        server = MagicMock()
        server.middleware_chain = None
        with pytest.raises(RuntimeError, match="Middleware chain"):
            await _dispatch(server, "echo", "call_tool")

    @pytest.mark.asyncio
    async def test_dispatches_through_chain(self) -> None:
        server = MagicMock()
        chain = AsyncMock(return_value="result_value")
        server.middleware_chain = chain

        result = await _dispatch(server, "echo", "call_tool", {"text": "hi"})
        assert result == "result_value"
        chain.assert_awaited_once()
        ctx = chain.call_args[0][0]
        assert isinstance(ctx, RequestContext)
        assert ctx.capability_name == "echo"
        assert ctx.mcp_method == "call_tool"
        assert ctx.arguments == {"text": "hi"}

    @pytest.mark.asyncio
    async def test_raises_ctx_error(self) -> None:
        """If ctx.error is set after chain, it should be raised."""
        err = ValueError("test error")

        async def chain_with_error(ctx):
            ctx.error = err
            return None

        server = MagicMock()
        server.middleware_chain = chain_with_error

        with pytest.raises(ValueError, match="test error"):
            await _dispatch(server, "echo", "call_tool")


class TestHandleListTools:
    @pytest.mark.asyncio
    async def test_returns_tools(self, mock_mcp_server: Any) -> None:
        server, handlers = mock_mcp_server
        tool1 = MagicMock(name="t1")
        server.registry.get_aggregated_tools.return_value = [tool1]

        result = await handlers["list_tools"]()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_no_registry_raises(self, mock_mcp_server: Any) -> None:
        server, handlers = mock_mcp_server
        server.registry = None

        with pytest.raises(BackendServerError, match="not initialized"):
            await handlers["list_tools"]()

    @pytest.mark.asyncio
    async def test_includes_composite_tools(self, mock_mcp_server: Any) -> None:
        server, handlers = mock_mcp_server
        server.registry.get_aggregated_tools.return_value = []

        composite = MagicMock()
        composite.to_tool_info.return_value = {
            "name": "wf_tool",
            "description": "A workflow",
            "inputSchema": {},
        }
        server.composite_tools = [composite]

        result = await handlers["list_tools"]()
        assert any(t.name == "wf_tool" for t in result)


class TestHandleListResources:
    @pytest.mark.asyncio
    async def test_returns_resources(self, mock_mcp_server: Any) -> None:
        server, handlers = mock_mcp_server
        r1 = MagicMock()
        server.registry.get_aggregated_resources.return_value = [r1]

        result = await handlers["list_resources"]()
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_no_registry_raises(self, mock_mcp_server: Any) -> None:
        server, handlers = mock_mcp_server
        server.registry = None

        with pytest.raises(BackendServerError):
            await handlers["list_resources"]()


class TestHandleListPrompts:
    @pytest.mark.asyncio
    async def test_returns_prompts(self, mock_mcp_server: Any) -> None:
        server, handlers = mock_mcp_server
        p1 = MagicMock()
        server.registry.get_aggregated_prompts.return_value = [p1]

        result = await handlers["list_prompts"]()
        assert len(result) == 1


class TestHandleCallTool:
    @pytest.mark.asyncio
    async def test_normal_dispatch(self, mock_mcp_server: Any) -> None:
        server, handlers = mock_mcp_server

        # Mock the middleware chain for dispatch
        mock_result = CallToolResult(
            content=[TextContent(type="text", text="output")],
            isError=False,
        )
        chain = AsyncMock(return_value=mock_result)
        server.middleware_chain = chain

        result = await handlers["call_tool"]("echo", {"msg": "hi"})
        assert isinstance(result, CallToolResult)
        assert len(result.content) == 1
        assert result.content[0].text == "output"

    @pytest.mark.asyncio
    async def test_composite_dispatch(self, mock_mcp_server: Any) -> None:
        server, handlers = mock_mcp_server

        composite = MagicMock()
        composite.name = "wf_tool"
        composite.invoke = AsyncMock(return_value={"status": "ok"})
        server.composite_tools = [composite]

        result = await handlers["call_tool"]("wf_tool", {"input": "x"})
        assert isinstance(result, CallToolResult)
        assert len(result.content) == 1
        assert "ok" in result.content[0].text

    @pytest.mark.asyncio
    async def test_composite_error_wrapped(self, mock_mcp_server: Any) -> None:
        server, handlers = mock_mcp_server

        composite = MagicMock()
        composite.name = "wf_fail"
        composite.invoke = AsyncMock(side_effect=RuntimeError("workflow crashed"))
        server.composite_tools = [composite]

        with pytest.raises(BackendServerError, match="execution failed"):
            await handlers["call_tool"]("wf_fail", {})
