"""Tests for security headers middleware.

Verifies that ``SecurityHeadersMiddleware`` injects the required
security response headers on HTTP responses and conditionally includes
HSTS for TLS connections.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from argus_mcp.config.schema_security import SecurityHeadersConfig
from argus_mcp.server.security_headers import SecurityHeadersMiddleware

pytestmark = [pytest.mark.security]


def _make_scope(
    *,
    scheme: str = "http",
    path: str = "/mcp",
    scope_type: str = "http",
) -> dict:
    return {
        "type": scope_type,
        "scheme": scheme,
        "path": path,
        "headers": [],
        "server": ("127.0.0.1", 8080),
        "client": ("10.0.0.1", 54321),
    }


class TestSecurityHeaders:
    """Core security header injection tests."""

    @pytest.mark.asyncio
    async def test_static_headers_injected(self, inner_app: AsyncMock, send_callable: AsyncMock):
        """All four static headers must be present on HTTP responses."""

        async def fake_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = SecurityHeadersMiddleware(fake_app)
        scope = _make_scope()

        captured = []

        async def capture_send(message):
            captured.append(message)

        await mw(scope, AsyncMock(), capture_send)

        start = captured[0]
        header_dict = {k: v for k, v in start["headers"]}
        assert header_dict[b"x-content-type-options"] == b"nosniff"
        assert header_dict[b"x-frame-options"] == b"DENY"
        assert header_dict[b"cache-control"] == b"no-store"
        assert header_dict[b"content-security-policy"] == b"default-src 'none'"

    @pytest.mark.asyncio
    async def test_hsts_not_on_http(self):
        """HSTS must NOT be sent over plain HTTP."""

        async def fake_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = SecurityHeadersMiddleware(fake_app)
        scope = _make_scope(scheme="http")

        captured = []

        async def capture_send(message):
            captured.append(message)

        await mw(scope, AsyncMock(), capture_send)

        start = captured[0]
        header_keys = {k for k, _ in start["headers"]}
        assert b"strict-transport-security" not in header_keys

    @pytest.mark.asyncio
    async def test_hsts_on_https(self):
        """HSTS must be sent over TLS connections."""

        async def fake_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        mw = SecurityHeadersMiddleware(fake_app)
        scope = _make_scope(scheme="https")

        captured = []

        async def capture_send(message):
            captured.append(message)

        await mw(scope, AsyncMock(), capture_send)

        start = captured[0]
        header_dict = {k: v for k, v in start["headers"]}
        assert b"strict-transport-security" in header_dict
        assert b"max-age=" in header_dict[b"strict-transport-security"]

    @pytest.mark.asyncio
    async def test_disabled_passes_through(self, inner_app: AsyncMock, send_callable: AsyncMock):
        """When disabled, middleware passes through without adding headers."""
        config = SecurityHeadersConfig(enabled=False)
        mw = SecurityHeadersMiddleware(inner_app, config=config)
        scope = _make_scope()

        await mw(scope, AsyncMock(), send_callable)

        inner_app.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_http_passes_through(self, inner_app: AsyncMock, send_callable: AsyncMock):
        """Non-HTTP scopes bypass the middleware."""
        mw = SecurityHeadersMiddleware(inner_app)
        scope = _make_scope(scope_type="websocket")

        await mw(scope, AsyncMock(), send_callable)

        inner_app.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_custom_hsts_max_age(self):
        """Custom HSTS max-age must be reflected in the header value."""

        async def fake_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        config = SecurityHeadersConfig(hsts_max_age=3600)
        mw = SecurityHeadersMiddleware(fake_app, config=config)
        scope = _make_scope(scheme="https")

        captured = []

        async def capture_send(message):
            captured.append(message)

        await mw(scope, AsyncMock(), capture_send)

        start = captured[0]
        header_dict = {k: v for k, v in start["headers"]}
        assert b"max-age=3600" in header_dict[b"strict-transport-security"]
