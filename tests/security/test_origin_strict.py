"""Origin strict mode tests (SEC-13).

Verify that the Origin validation middleware can operate in strict mode
where a missing Origin header on MCP routes is rejected (403 Forbidden),
versus permissive mode (default) where missing Origin is allowed.
"""

from __future__ import annotations

import importlib
from unittest.mock import AsyncMock

import pytest

# Import origin module directly to avoid the argus_mcp.server.__init__
# import chain which calls create_app() at module level and fails on
# missing get_config in isolated test environments.
_origin_mod = importlib.import_module("argus_mcp.server.origin")
OriginValidationMiddleware = _origin_mod.OriginValidationMiddleware

pytestmark = [pytest.mark.security]


def _make_scope(path: str = "/mcp", origin: str | None = None) -> dict:
    """Build a minimal ASGI HTTP scope for origin middleware tests."""
    headers: list[tuple[bytes, bytes]] = []
    if origin is not None:
        headers.append((b"origin", origin.encode("latin-1")))
    return {
        "type": "http",
        "path": path,
        "headers": headers,
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 8080),
    }


class TestOriginStrictMode:
    """Origin strict mode rejects missing Origin on MCP paths."""

    @pytest.mark.asyncio
    async def test_strict_rejects_missing_origin(self):
        """In strict mode, a request without Origin header on /mcp returns 403."""
        inner = AsyncMock()
        middleware = OriginValidationMiddleware(inner, require_origin="strict")
        scope = _make_scope("/mcp", origin=None)

        sent_responses: list[dict] = []

        async def capture_send(message):
            sent_responses.append(message)

        await middleware(scope, AsyncMock(), capture_send)
        # Should get a 403 response, not pass through to inner app
        assert inner.call_count == 0
        assert any(msg.get("status") == 403 for msg in sent_responses)

    @pytest.mark.asyncio
    async def test_strict_allows_localhost_origin(self):
        """In strict mode, localhost Origin is still accepted."""
        inner = AsyncMock()
        middleware = OriginValidationMiddleware(inner, require_origin="strict")
        scope = _make_scope("/mcp", origin="http://localhost:3000")

        await middleware(scope, AsyncMock(), AsyncMock())
        inner.assert_called_once()

    @pytest.mark.asyncio
    async def test_strict_allows_valid_origin(self):
        """In strict mode, a valid non-localhost origin is accepted."""
        inner = AsyncMock()
        with pytest.MonkeyPatch.context() as mp:
            mp.setenv("ARGUS_ALLOWED_ORIGINS", "https://app.example.com")
            middleware = OriginValidationMiddleware(inner, require_origin="strict")
        scope = _make_scope("/mcp", origin="https://app.example.com")

        await middleware(scope, AsyncMock(), AsyncMock())
        inner.assert_called_once()

    @pytest.mark.asyncio
    async def test_strict_rejects_disallowed_origin(self):
        """In strict mode, a non-allowed origin returns 403."""
        inner = AsyncMock()
        middleware = OriginValidationMiddleware(inner, require_origin="strict")
        scope = _make_scope("/mcp", origin="https://evil.example.com")

        sent_responses: list[dict] = []

        async def capture_send(message):
            sent_responses.append(message)

        await middleware(scope, AsyncMock(), capture_send)
        assert inner.call_count == 0
        assert any(msg.get("status") == 403 for msg in sent_responses)

    @pytest.mark.asyncio
    async def test_strict_ignores_non_mcp_paths(self):
        """Strict mode does not affect non-MCP paths (e.g. /manage)."""
        inner = AsyncMock()
        middleware = OriginValidationMiddleware(inner, require_origin="strict")
        scope = _make_scope("/manage/v1/status", origin=None)

        await middleware(scope, AsyncMock(), AsyncMock())
        inner.assert_called_once()


class TestOriginPermissiveMode:
    """Default permissive mode allows missing Origin."""

    @pytest.mark.asyncio
    async def test_permissive_allows_missing_origin(self):
        """In permissive mode (default), missing Origin is allowed."""
        inner = AsyncMock()
        middleware = OriginValidationMiddleware(inner, require_origin="permissive")
        scope = _make_scope("/mcp", origin=None)

        await middleware(scope, AsyncMock(), AsyncMock())
        inner.assert_called_once()

    @pytest.mark.asyncio
    async def test_default_is_strict(self):
        """Without require_origin parameter, middleware defaults to strict."""
        inner = AsyncMock()
        middleware = OriginValidationMiddleware(inner)
        scope = _make_scope("/mcp", origin=None)

        sent_responses: list[dict] = []

        async def capture_send(message):
            sent_responses.append(message)

        await middleware(scope, AsyncMock(), capture_send)
        assert inner.call_count == 0
        assert any(msg.get("status") == 403 for msg in sent_responses)

    @pytest.mark.asyncio
    async def test_permissive_still_rejects_bad_origin(self):
        """Even in permissive mode, a disallowed Origin is rejected."""
        inner = AsyncMock()
        middleware = OriginValidationMiddleware(inner, require_origin="permissive")
        scope = _make_scope("/mcp", origin="https://evil.example.com")

        sent_responses: list[dict] = []

        async def capture_send(message):
            sent_responses.append(message)

        await middleware(scope, AsyncMock(), capture_send)
        assert inner.call_count == 0
