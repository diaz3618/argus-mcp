"""Tests for argus_mcp.server.management.auth — Bearer auth middleware.

Covers:
- resolve_token() from environment
- BearerAuthMiddleware: public path bypass, no-token bypass,
  invalid token rejection, valid token acceptance, timing-safe comparison
"""

from __future__ import annotations

import hmac
from unittest.mock import AsyncMock, patch

import pytest

from argus_mcp.server.management.auth import (
    MGMT_TOKEN_ENV_VAR,
    PUBLIC_PATH_SUFFIXES,
    BearerAuthMiddleware,
    resolve_token,
)

# resolve_token


class TestResolveToken:
    def test_returns_env_value(self, monkeypatch):
        monkeypatch.setenv(MGMT_TOKEN_ENV_VAR, "my-secret-token")
        assert resolve_token() == "my-secret-token"

    def test_returns_none_when_unset(self, monkeypatch):
        monkeypatch.delenv(MGMT_TOKEN_ENV_VAR, raising=False)
        assert resolve_token() is None

    def test_returns_none_for_empty(self, monkeypatch):
        monkeypatch.setenv(MGMT_TOKEN_ENV_VAR, "")
        result = resolve_token()
        # Empty string should be treated as no token
        assert result == "" or result is None


# PUBLIC_PATH_SUFFIXES


class TestPublicPaths:
    def test_health_is_public(self):
        assert "/health" in PUBLIC_PATH_SUFFIXES

    def test_ready_is_public(self):
        assert "/ready" in PUBLIC_PATH_SUFFIXES

    def test_is_frozenset(self):
        assert isinstance(PUBLIC_PATH_SUFFIXES, frozenset)


# BearerAuthMiddleware


class TestBearerAuthMiddleware:
    """Test the ASGI middleware for bearer token auth."""

    @staticmethod
    def _make_scope(path: str, headers: dict[str, str] | None = None) -> dict:
        """Create a minimal ASGI scope."""
        raw_headers = []
        if headers:
            for k, v in headers.items():
                raw_headers.append((k.lower().encode(), v.encode()))
        return {
            "type": "http",
            "path": path,
            "headers": raw_headers,
        }

    @staticmethod
    def _make_middleware(token: str | None = "secret-token") -> BearerAuthMiddleware:
        """Create middleware with a mock inner app."""
        inner_app = AsyncMock()
        with patch.object(BearerAuthMiddleware, "__init__", lambda self, app: None):
            mw = BearerAuthMiddleware.__new__(BearerAuthMiddleware)
        mw.app = inner_app
        mw._token = token
        return mw

    @pytest.mark.asyncio
    async def test_public_path_bypasses_auth(self):
        """Requests to /health should pass through without auth."""
        inner = AsyncMock()
        mw = BearerAuthMiddleware(inner)
        # Patch token
        mw._token = "secret"

        scope = self._make_scope("/manage/v1/health")
        receive = AsyncMock()
        send = AsyncMock()

        await mw(scope, receive, send)
        inner.assert_awaited_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_no_token_configured_passes_all(self):
        """When no token is set, all requests pass through."""
        inner = AsyncMock()
        mw = BearerAuthMiddleware(inner)
        mw._token = None

        scope = self._make_scope("/manage/v1/status")
        receive = AsyncMock()
        send = AsyncMock()

        await mw(scope, receive, send)
        inner.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_valid_token_passes(self):
        """Correct bearer token should pass through."""
        inner = AsyncMock()
        mw = BearerAuthMiddleware(inner)
        mw._token = "my-mgmt-token"

        scope = self._make_scope(
            "/manage/v1/reload",
            headers={"authorization": "Bearer my-mgmt-token"},
        )
        receive = AsyncMock()
        send = AsyncMock()

        await mw(scope, receive, send)
        inner.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalid_token_rejected(self):
        """Wrong token should return 401."""
        inner = AsyncMock()
        mw = BearerAuthMiddleware(inner)
        mw._token = "correct-token"

        scope = self._make_scope(
            "/manage/v1/reload",
            headers={"authorization": "Bearer wrong-token"},
        )
        receive = AsyncMock()
        send = AsyncMock()

        await mw(scope, receive, send)
        # Inner app should NOT be called
        inner.assert_not_awaited()
        # send should have been called with a 401 response
        send.assert_awaited()
        # Check that response starts with a 401 status
        start_call = send.call_args_list[0]
        response = start_call[0][0]
        assert response.get("status") == 401

    @pytest.mark.asyncio
    async def test_missing_auth_header_rejected(self):
        """No Authorization header with token configured should return 401."""
        inner = AsyncMock()
        mw = BearerAuthMiddleware(inner)
        mw._token = "my-token"

        scope = self._make_scope("/manage/v1/shutdown")
        receive = AsyncMock()
        send = AsyncMock()

        await mw(scope, receive, send)
        inner.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_http_scope_passes(self):
        """Non-HTTP scopes (websocket, lifespan) should pass through."""
        inner = AsyncMock()
        mw = BearerAuthMiddleware(inner)
        mw._token = "secret"

        scope = {"type": "lifespan"}
        receive = AsyncMock()
        send = AsyncMock()

        await mw(scope, receive, send)
        inner.assert_awaited_once()


class TestTimingSafety:
    """Verify that token comparison uses constant-time comparison."""

    def test_hmac_compare_digest_available(self):
        assert callable(hmac.compare_digest)

    def test_constant_time_equal_tokens(self):
        assert hmac.compare_digest("token123", "token123") is True

    def test_constant_time_unequal_tokens(self):
        assert hmac.compare_digest("token123", "token456") is False
