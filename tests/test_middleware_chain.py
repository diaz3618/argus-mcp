"""Tests for argus_mcp.bridge.middleware.chain — Middleware chain infrastructure.

Covers:
- RequestContext: default values, elapsed_ms, metadata
- build_chain: single handler, single middleware, multiple middlewares
- Middleware execution order (outermost first)
- Context mutation by middleware
- Error propagation through chain
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock

import pytest

from argus_mcp.bridge.middleware.chain import (
    RequestContext,
    build_chain,
)


class TestRequestContext:
    """RequestContext is the per-request metadata bag."""

    def test_defaults(self) -> None:
        ctx = RequestContext(capability_name="echo", mcp_method="call_tool")
        assert ctx.capability_name == "echo"
        assert ctx.mcp_method == "call_tool"
        assert ctx.arguments is None
        assert ctx.server_name is None
        assert ctx.original_name is None
        assert ctx.error is None
        assert isinstance(ctx.request_id, str)
        assert len(ctx.request_id) == 12
        assert isinstance(ctx.metadata, dict)
        assert len(ctx.metadata) == 0

    def test_custom_values(self) -> None:
        ctx = RequestContext(
            capability_name="search",
            mcp_method="call_tool",
            arguments={"query": "test"},
            request_id="abc123",
            server_name="backend-1",
            original_name="raw_search",
        )
        assert ctx.capability_name == "search"
        assert ctx.arguments == {"query": "test"}
        assert ctx.request_id == "abc123"
        assert ctx.server_name == "backend-1"
        assert ctx.original_name == "raw_search"

    def test_elapsed_ms(self) -> None:
        ctx = RequestContext(capability_name="t", mcp_method="call_tool")
        # elapsed_ms should be >= 0 and small
        assert ctx.elapsed_ms >= 0
        assert ctx.elapsed_ms < 1000  # should be < 1 second

    def test_elapsed_ms_increases(self) -> None:
        ctx = RequestContext(capability_name="t", mcp_method="call_tool")
        t1 = ctx.elapsed_ms
        time.sleep(0.01)  # 10ms
        t2 = ctx.elapsed_ms
        assert t2 > t1

    def test_unique_request_ids(self) -> None:
        ids = {RequestContext(capability_name="t", mcp_method="m").request_id for _ in range(100)}
        assert len(ids) == 100

    def test_metadata_mutable(self) -> None:
        ctx = RequestContext(capability_name="t", mcp_method="m")
        ctx.metadata["key"] = "value"
        assert ctx.metadata["key"] == "value"

    def test_error_assignment(self) -> None:
        ctx = RequestContext(capability_name="t", mcp_method="m")
        err = ValueError("test")
        ctx.error = err
        assert ctx.error is err


class TestBuildChain:
    """build_chain composes middlewares around a final handler."""

    @pytest.mark.asyncio
    async def test_no_middleware(self) -> None:
        """Chain with zero middleware → handler called directly."""
        handler = AsyncMock(return_value="result")
        chain = build_chain([], handler)
        ctx = RequestContext(capability_name="t", mcp_method="m")
        result = await chain(ctx)
        assert result == "result"
        handler.assert_awaited_once_with(ctx)

    @pytest.mark.asyncio
    async def test_single_middleware(self) -> None:
        """Single middleware wraps the handler."""
        call_log: list = []

        async def middleware(ctx: RequestContext, next_handler: Any) -> Any:
            call_log.append("mw_before")
            result = await next_handler(ctx)
            call_log.append("mw_after")
            return result

        async def handler(ctx: RequestContext) -> str:
            call_log.append("handler")
            return "done"

        chain = build_chain([middleware], handler)
        ctx = RequestContext(capability_name="t", mcp_method="m")
        result = await chain(ctx)
        assert result == "done"
        assert call_log == ["mw_before", "handler", "mw_after"]

    @pytest.mark.asyncio
    async def test_multiple_middleware_order(self) -> None:
        """Middlewares execute in list order (first = outermost)."""
        call_log: list = []

        async def mw1(ctx: RequestContext, next_h: Any) -> Any:
            call_log.append("mw1_before")
            result = await next_h(ctx)
            call_log.append("mw1_after")
            return result

        async def mw2(ctx: RequestContext, next_h: Any) -> Any:
            call_log.append("mw2_before")
            result = await next_h(ctx)
            call_log.append("mw2_after")
            return result

        async def handler(ctx: RequestContext) -> str:
            call_log.append("handler")
            return "ok"

        chain = build_chain([mw1, mw2], handler)
        ctx = RequestContext(capability_name="t", mcp_method="m")
        await chain(ctx)
        assert call_log == [
            "mw1_before",
            "mw2_before",
            "handler",
            "mw2_after",
            "mw1_after",
        ]

    @pytest.mark.asyncio
    async def test_middleware_can_modify_context(self) -> None:
        """Middleware can mutate context before passing to handler."""

        async def tagging_mw(ctx: RequestContext, next_h: Any) -> Any:
            ctx.metadata["tagged"] = True
            return await next_h(ctx)

        async def handler(ctx: RequestContext) -> bool:
            return ctx.metadata.get("tagged", False)

        chain = build_chain([tagging_mw], handler)
        ctx = RequestContext(capability_name="t", mcp_method="m")
        result = await chain(ctx)
        assert result is True

    @pytest.mark.asyncio
    async def test_error_propagates(self) -> None:
        """Errors in handler propagate up through middleware."""

        async def passthrough_mw(ctx: RequestContext, next_h: Any) -> Any:
            return await next_h(ctx)

        async def failing_handler(ctx: RequestContext) -> None:
            raise ValueError("handler error")

        chain = build_chain([passthrough_mw], failing_handler)
        ctx = RequestContext(capability_name="t", mcp_method="m")
        with pytest.raises(ValueError, match="handler error"):
            await chain(ctx)

    @pytest.mark.asyncio
    async def test_middleware_can_catch_errors(self) -> None:
        """Middleware can intercept errors from downstream."""

        async def catching_mw(ctx: RequestContext, next_h: Any) -> Any:
            try:
                return await next_h(ctx)
            except ValueError:
                return "caught"

        async def failing_handler(ctx: RequestContext) -> None:
            raise ValueError("fail")

        chain = build_chain([catching_mw], failing_handler)
        ctx = RequestContext(capability_name="t", mcp_method="m")
        result = await chain(ctx)
        assert result == "caught"

    @pytest.mark.asyncio
    async def test_middleware_can_short_circuit(self) -> None:
        """Middleware can return without calling next_handler."""

        async def short_circuit_mw(ctx: RequestContext, next_h: Any) -> str:
            return "short-circuited"

        handler = AsyncMock(return_value="should not reach")
        chain = build_chain([short_circuit_mw], handler)
        ctx = RequestContext(capability_name="t", mcp_method="m")
        result = await chain(ctx)
        assert result == "short-circuited"
        handler.assert_not_awaited()
