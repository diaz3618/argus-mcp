"""Regression tests for SEC-20 (VULN-020).

Payload limits middleware preventing oversized and deeply nested JSON payloads.
These tests verify that resource exhaustion via large or complex request bodies
is no longer possible.

See: internal/reports/security/p2/VULN-020-payload-limits.md

Covers:
1. Requests within body size limit pass through
2. Oversized body returns 413
3. JSON exceeding nesting depth returns 400
4. GET/HEAD/OPTIONS/DELETE skip body checks
5. Non-JSON content skips depth check
6. Disabled config passes all traffic
7. Non-HTTP scopes pass through
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from argus_mcp.config.schema_security import PayloadLimitsConfig
from argus_mcp.server.payload_limits import PayloadLimitsMiddleware

pytestmark = [pytest.mark.security]


def _make_scope(
    *,
    method: str = "POST",
    path: str = "/mcp",
    scope_type: str = "http",
    content_type: bytes = b"application/json",
) -> dict:
    return {
        "type": scope_type,
        "method": method,
        "path": path,
        "headers": [(b"content-type", content_type)],
        "server": ("127.0.0.1", 8080),
        "client": ("10.0.0.1", 54321),
    }


def _make_receive(body: bytes):
    """Return an async receive callable that yields *body* in one chunk."""
    called = False

    async def receive():
        nonlocal called
        if not called:
            called = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    return receive


class TestBodySizeLimit:
    """Request body size enforcement."""

    @pytest.mark.asyncio
    async def test_within_limit_passes(self, inner_app: AsyncMock, send_callable: AsyncMock):
        config = PayloadLimitsConfig(max_body_bytes=1024)
        mw = PayloadLimitsMiddleware(inner_app, config=config)
        scope = _make_scope()
        body = b"x" * 512

        await mw(scope, _make_receive(body), send_callable)

        inner_app.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_oversized_body_returns_413(self):
        inner = AsyncMock()
        config = PayloadLimitsConfig(max_body_bytes=1024)
        mw = PayloadLimitsMiddleware(inner, config=config)
        scope = _make_scope()
        body = b"x" * 2048

        captured = []

        async def capture_send(message):
            captured.append(message)

        await mw(scope, _make_receive(body), capture_send)

        inner.assert_not_awaited()
        start = captured[0]
        assert start["status"] == 413

    @pytest.mark.asyncio
    async def test_exact_limit_passes(self, inner_app: AsyncMock, send_callable: AsyncMock):
        config = PayloadLimitsConfig(max_body_bytes=1024)
        mw = PayloadLimitsMiddleware(inner_app, config=config)
        scope = _make_scope()
        body = b"x" * 1024

        await mw(scope, _make_receive(body), send_callable)

        inner_app.assert_awaited_once()


class TestJsonDepthLimit:
    """JSON nesting depth enforcement."""

    @pytest.mark.asyncio
    async def test_shallow_json_passes(self, inner_app: AsyncMock, send_callable: AsyncMock):
        config = PayloadLimitsConfig(max_json_depth=5)
        mw = PayloadLimitsMiddleware(inner_app, config=config)
        scope = _make_scope()
        body = json.dumps({"a": {"b": {"c": 1}}}).encode()

        await mw(scope, _make_receive(body), send_callable)

        inner_app.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_deep_json_returns_400(self):
        inner = AsyncMock()
        config = PayloadLimitsConfig(max_json_depth=3)
        mw = PayloadLimitsMiddleware(inner, config=config)
        scope = _make_scope()
        # Build deeply nested JSON: {"a": {"a": {"a": {"a": 1}}}}
        nested: dict | int = 1
        for _ in range(5):
            nested = {"a": nested}
        body = json.dumps(nested).encode()

        captured = []

        async def capture_send(message):
            captured.append(message)

        await mw(scope, _make_receive(body), capture_send)

        inner.assert_not_awaited()
        start = captured[0]
        assert start["status"] == 400

    @pytest.mark.asyncio
    async def test_non_json_content_skips_depth_check(
        self, inner_app: AsyncMock, send_callable: AsyncMock
    ):
        """Non-JSON content type should skip depth check even with deep data."""
        config = PayloadLimitsConfig(max_json_depth=1)
        mw = PayloadLimitsMiddleware(inner_app, config=config)
        scope = _make_scope(content_type=b"application/octet-stream")
        body = b"not json but large enough"

        await mw(scope, _make_receive(body), send_callable)

        inner_app.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_malformed_json_passes_to_app(
        self, inner_app: AsyncMock, send_callable: AsyncMock
    ):
        """Malformed JSON should be passed through to the app layer."""
        config = PayloadLimitsConfig(max_json_depth=1)
        mw = PayloadLimitsMiddleware(inner_app, config=config)
        scope = _make_scope()
        body = b"{not valid json"

        await mw(scope, _make_receive(body), send_callable)

        inner_app.assert_awaited_once()


class TestMethodSkipping:
    """Body-less methods bypass payload checks."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "DELETE"])
    async def test_bodyless_methods_skip(
        self, method: str, inner_app: AsyncMock, send_callable: AsyncMock
    ):
        config = PayloadLimitsConfig(max_body_bytes=1024)  # Minimum allowed limit
        mw = PayloadLimitsMiddleware(inner_app, config=config)
        scope = _make_scope(method=method)

        await mw(scope, AsyncMock(), send_callable)

        inner_app.assert_awaited_once()


class TestDisabled:
    """Disabled payload limits passes all traffic."""

    @pytest.mark.asyncio
    async def test_disabled_passes_oversized(self, inner_app: AsyncMock, send_callable: AsyncMock):
        config = PayloadLimitsConfig(enabled=False)
        mw = PayloadLimitsMiddleware(inner_app, config=config)
        scope = _make_scope()

        await mw(scope, AsyncMock(), send_callable)

        inner_app.assert_awaited_once()


class TestNonHttpScope:
    """Non-HTTP scopes pass through unconditionally."""

    @pytest.mark.asyncio
    async def test_websocket_passes(self, inner_app: AsyncMock, send_callable: AsyncMock):
        mw = PayloadLimitsMiddleware(inner_app)
        scope = _make_scope(scope_type="websocket")

        await mw(scope, AsyncMock(), send_callable)

        inner_app.assert_awaited_once()
