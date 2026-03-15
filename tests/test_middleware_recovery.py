"""Tests for argus_mcp.bridge.middleware.recovery — Recovery middleware.

Covers:
- Happy path passthrough
- Exception caught → ctx.error set
- Returns structured MCP error (CallToolResult with isError=True)
- Sanitised error messages (no internal details leaked)
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from argus_mcp.bridge.middleware.chain import RequestContext
from argus_mcp.bridge.middleware.recovery import RecoveryMiddleware


class TestRecoveryMiddlewareHappyPath:
    @pytest.mark.asyncio
    async def test_passthrough(self) -> None:
        """No error → result passed through unchanged."""
        rm = RecoveryMiddleware()
        next_handler = AsyncMock(return_value="success")
        ctx = RequestContext(capability_name="t", mcp_method="call_tool")
        result = await rm(ctx, next_handler)
        assert result == "success"
        assert ctx.error is None


class TestRecoveryMiddlewareErrorHandling:
    @pytest.mark.asyncio
    async def test_catches_exception(self) -> None:
        rm = RecoveryMiddleware()
        next_handler = AsyncMock(side_effect=ValueError("internal detail"))
        ctx = RequestContext(capability_name="echo", mcp_method="call_tool")
        _result = await rm(ctx, next_handler)
        # Error should be stored in context
        assert ctx.error is not None
        assert isinstance(ctx.error, ValueError)

    @pytest.mark.asyncio
    async def test_returns_structured_error(self) -> None:
        rm = RecoveryMiddleware()
        next_handler = AsyncMock(side_effect=RuntimeError("secret path /etc/db"))
        ctx = RequestContext(capability_name="echo", mcp_method="call_tool")
        result = await rm(ctx, next_handler)

        # Should be a CallToolResult or dict with error info
        # Check it's some kind of error response
        if hasattr(result, "isError"):
            # MCP CallToolResult
            assert result.isError is True
            # Should NOT leak internal secret path
            content_text = result.content[0].text
            assert "/etc/db" not in content_text
            assert "Internal error" in content_text
        else:
            # Dict fallback
            assert "error" in result
            assert "/etc/db" not in str(result)

    @pytest.mark.asyncio
    async def test_sanitised_message_no_stack_trace(self) -> None:
        rm = RecoveryMiddleware()
        next_handler = AsyncMock(
            side_effect=Exception("File '/home/user/secrets/key.pem' not found")
        )
        ctx = RequestContext(capability_name="tool", mcp_method="call_tool")
        result = await rm(ctx, next_handler)

        # Verify raw exception message is NOT in the user-facing result
        if hasattr(result, "content"):
            text = result.content[0].text
        else:
            text = str(result)
        assert "secrets/key.pem" not in text
        assert "Internal error" in text

    @pytest.mark.asyncio
    async def test_method_name_in_error_message(self) -> None:
        rm = RecoveryMiddleware()
        next_handler = AsyncMock(side_effect=RuntimeError("boom"))
        ctx = RequestContext(capability_name="echo", mcp_method="call_tool")
        result = await rm(ctx, next_handler)

        if hasattr(result, "content"):
            text = result.content[0].text
        else:
            text = str(result.get("error", {}).get("message", ""))
        assert "call_tool" in text

    @pytest.mark.asyncio
    async def test_handles_timeout_error(self) -> None:
        import asyncio

        rm = RecoveryMiddleware()
        next_handler = AsyncMock(side_effect=asyncio.TimeoutError())
        ctx = RequestContext(capability_name="slow", mcp_method="call_tool")
        _result = await rm(ctx, next_handler)
        assert ctx.error is not None

    @pytest.mark.asyncio
    async def test_handles_keyboard_interrupt(self) -> None:
        """KeyboardInterrupt is a BaseException, not Exception — should NOT be caught."""
        rm = RecoveryMiddleware()
        next_handler = AsyncMock(side_effect=KeyboardInterrupt())
        ctx = RequestContext(capability_name="t", mcp_method="call_tool")
        # KeyboardInterrupt should propagate (not caught by except Exception)
        with pytest.raises(KeyboardInterrupt):
            await rm(ctx, next_handler)
