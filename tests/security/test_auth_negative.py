"""Security-focused negative tests for management API authentication.

Tests cover:
- Token bypass attempts (path traversal, header manipulation)
- Invalid/malformed tokens
- Exposed-bind warning behaviour
- Non-HTTP scope passthrough
- Constant-time comparison guarantees
"""

from __future__ import annotations

import hmac
from unittest.mock import AsyncMock, patch

import pytest

from argus_mcp.server.management.auth import (
    MGMT_TOKEN_ENV_VAR,
    BearerAuthMiddleware,
    resolve_token,
)

pytestmark = [pytest.mark.security]


# Helpers ────────────────────────────────────────────────────────


def _make_scope(
    path: str = "/manage/v1/reload",
    *,
    headers: dict[str, str] | None = None,
    scope_type: str = "http",
    server: tuple[str, int] = ("127.0.0.1", 8080),
    client: tuple[str, int] = ("10.0.0.5", 54321),
) -> dict:
    raw_headers: list[tuple[bytes, bytes]] = []
    if headers:
        for k, v in headers.items():
            raw_headers.append((k.lower().encode(), v.encode()))
    return {
        "type": scope_type,
        "path": path,
        "headers": raw_headers,
        "server": server,
        "client": client,
    }


def _make_middleware(token: str | None = "test-secret") -> tuple[BearerAuthMiddleware, AsyncMock]:
    inner = AsyncMock()
    mw = BearerAuthMiddleware(inner, token=token)
    return mw, inner


# Token bypass attempts ──────────────────────────────────────────


class TestTokenBypass:
    """Attempts to bypass token auth that must fail."""

    @pytest.mark.asyncio
    async def test_wrong_token_rejected(self):
        mw, inner = _make_middleware("correct-token")
        scope = _make_scope(headers={"authorization": "Bearer wrong-token"})
        send = AsyncMock()

        await mw(scope, AsyncMock(), send)

        inner.assert_not_awaited()
        start = send.call_args_list[0][0][0]
        assert start.get("status") == 401

    @pytest.mark.asyncio
    async def test_empty_bearer_token_rejected(self):
        mw, inner = _make_middleware("secret")
        scope = _make_scope(headers={"authorization": "Bearer "})
        send = AsyncMock()

        await mw(scope, AsyncMock(), send)

        inner.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_auth_header_rejected(self):
        mw, inner = _make_middleware("secret")
        scope = _make_scope()  # no headers
        send = AsyncMock()

        await mw(scope, AsyncMock(), send)

        inner.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_basic_auth_scheme_rejected(self):
        """Using Basic instead of Bearer must be rejected."""
        mw, inner = _make_middleware("secret")
        scope = _make_scope(headers={"authorization": "Basic c2VjcmV0"})
        send = AsyncMock()

        await mw(scope, AsyncMock(), send)

        inner.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_bearer_lowercase_rejected(self):
        """'bearer' (lowercase) is not the canonical prefix."""
        mw, inner = _make_middleware("secret")
        scope = _make_scope(headers={"authorization": "bearer secret"})
        send = AsyncMock()

        await mw(scope, AsyncMock(), send)

        inner.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_token_with_extra_spaces_rejected(self):
        """Token with leading/trailing spaces must not match stripped token."""
        mw, inner = _make_middleware("secret")
        scope = _make_scope(headers={"authorization": "Bearer  secret"})
        send = AsyncMock()

        await mw(scope, AsyncMock(), send)

        # Extra space means provided_token is " secret", which != "secret"
        inner.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_multiple_authorization_headers_first_wins(self):
        """Only the first authorization header should be read."""
        mw, inner = _make_middleware("correct")
        # Manually craft scope with two authorization headers
        scope = {
            "type": "http",
            "path": "/manage/v1/reload",
            "headers": [
                (b"authorization", b"Bearer wrong"),
                (b"authorization", b"Bearer correct"),
            ],
            "server": ("127.0.0.1", 8080),
            "client": ("10.0.0.5", 54321),
        }
        send = AsyncMock()

        await mw(scope, AsyncMock(), send)

        # The middleware reads the first match; "wrong" should fail
        inner.assert_not_awaited()


# Public path behaviour ──────────────────────────────────────────


class TestPublicPathEnforcement:
    """Verify public path bypass is narrow and cannot be abused."""

    @pytest.mark.asyncio
    async def test_health_always_public(self):
        mw, inner = _make_middleware("secret")
        scope = _make_scope(path="/manage/v1/health")
        await mw(scope, AsyncMock(), AsyncMock())
        inner.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_health_trailing_slash_public(self):
        mw, inner = _make_middleware("secret")
        scope = _make_scope(path="/manage/v1/health/")
        await mw(scope, AsyncMock(), AsyncMock())
        inner.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_health_path_requires_auth(self):
        """Paths outside PUBLIC_PATH_SUFFIXES require auth."""
        mw, inner = _make_middleware("secret")
        scope = _make_scope(path="/manage/v1/reload")
        send = AsyncMock()

        await mw(scope, AsyncMock(), send)

        inner.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_health_substring_not_public(self):
        """'/healthcheck' should not match the '/health' suffix."""
        mw, inner = _make_middleware("secret")
        scope = _make_scope(path="/manage/v1/healthcheck")
        send = AsyncMock()

        await mw(scope, AsyncMock(), send)

        # '/healthcheck'.rstrip('/') == '/healthcheck', endswith('/health') is False
        inner.assert_not_awaited()


# Non-HTTP scope passthrough ─────────────────────────────────────


class TestNonHttpScope:
    """Non-HTTP scopes must always pass through regardless of auth config."""

    @pytest.mark.asyncio
    async def test_websocket_passes(self):
        mw, inner = _make_middleware("secret")
        scope = {"type": "websocket"}
        await mw(scope, AsyncMock(), AsyncMock())
        inner.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_lifespan_passes(self):
        mw, inner = _make_middleware("secret")
        scope = {"type": "lifespan"}
        await mw(scope, AsyncMock(), AsyncMock())
        inner.assert_awaited_once()


# Exposed bind warnings ─────────────────────────────────────────


class TestExposedBindWarnings:
    """Verify security warnings for unauthenticated exposed binds."""

    @pytest.mark.asyncio
    async def test_exposed_bind_no_token_warns(self):
        """Exposed bind without token should log security warning."""
        mw, inner = _make_middleware(token=None)
        scope = _make_scope(
            path="/manage/v1/reload",
            server=("0.0.0.0", 8080),
        )
        with patch("argus_mcp.server.management.auth.logger") as mock_logger:
            await mw(scope, AsyncMock(), AsyncMock())
            # Should have called warning for exposed bind
            assert mock_logger.warning.called

    @pytest.mark.asyncio
    async def test_exposed_bind_warning_once(self):
        """Exposure warning should be emitted at most once."""
        mw, inner = _make_middleware(token=None)

        for _ in range(3):
            scope = _make_scope(
                path="/manage/v1/reload",
                server=("0.0.0.0", 8080),
            )
            await mw(scope, AsyncMock(), AsyncMock())

        # _warned_exposed should be set after first call
        assert mw._warned_exposed is True

    @pytest.mark.asyncio
    async def test_localhost_bind_no_warning(self):
        """Localhost bind without token should not emit SECURITY WARNING."""
        mw, inner = _make_middleware(token=None)
        scope = _make_scope(
            path="/manage/v1/reload",
            server=("127.0.0.1", 8080),
        )
        with patch("argus_mcp.server.management.auth.logger") as mock_logger:
            await mw(scope, AsyncMock(), AsyncMock())
            # Filter for the specific SECURITY WARNING string
            sec_warnings = [
                call
                for call in mock_logger.warning.call_args_list
                if "SECURITY WARNING" in str(call)
            ]
            assert len(sec_warnings) == 0


# resolve_token ──────────────────────────────────────────────────


class TestResolveToken:
    """Test token resolution from environment."""

    def test_env_var_resolved(self):
        with patch.dict("os.environ", {MGMT_TOKEN_ENV_VAR: "my-token"}):
            assert resolve_token() == "my-token"

    def test_whitespace_env_var_ignored(self):
        with patch.dict("os.environ", {MGMT_TOKEN_ENV_VAR: "   "}):
            assert resolve_token() is None

    def test_empty_env_var_ignored(self):
        with patch.dict("os.environ", {MGMT_TOKEN_ENV_VAR: ""}):
            assert resolve_token() is None

    def test_no_env_var_returns_none(self):
        with patch.dict("os.environ", {}, clear=True):
            assert resolve_token() is None

    def test_env_var_stripped(self):
        with patch.dict("os.environ", {MGMT_TOKEN_ENV_VAR: "  tok  "}):
            assert resolve_token() == "tok"


# Timing safety ──────────────────────────────────────────────────


class TestTimingSafety:
    """Ensure constant-time comparison is used to prevent timing attacks."""

    def test_hmac_compare_digest_used(self):
        """Verify the module uses hmac for comparison (source-level)."""
        import inspect

        import argus_mcp.server.management.auth as auth_mod

        src = inspect.getsource(auth_mod.BearerAuthMiddleware.__call__)
        assert "hmac.compare_digest" in src

    def test_equal_tokens_match(self):
        assert hmac.compare_digest("token-abc", "token-abc") is True

    def test_unequal_tokens_reject(self):
        assert hmac.compare_digest("token-abc", "token-xyz") is False

    def test_empty_vs_nonempty_reject(self):
        assert hmac.compare_digest("", "nonempty") is False

    def test_unicode_normalization_not_applied(self):
        """Tokens should be compared byte-for-byte, no normalization."""
        # \u00e9 (é) vs e\u0301 (e + combining accent) are visually identical
        # hmac.compare_digest rejects non-ASCII str; encode to bytes
        assert hmac.compare_digest("\u00e9".encode(), "e\u0301".encode()) is False


# 401 response format ───────────────────────────────────────────


class TestUnauthorizedResponse:
    """Verify 401 responses include correct headers and body structure."""

    @pytest.mark.asyncio
    async def test_401_has_www_authenticate_header(self):
        mw, inner = _make_middleware("secret")
        scope = _make_scope(headers={"authorization": "Bearer wrong"})
        send = AsyncMock()

        await mw(scope, AsyncMock(), send)

        # Find the response.start message
        calls = send.call_args_list
        start_msg = calls[0][0][0]
        assert start_msg["status"] == 401
        response_headers = {k: v for k, v in start_msg.get("headers", [])}
        assert response_headers.get(b"www-authenticate") == b"Bearer"

    @pytest.mark.asyncio
    async def test_401_body_is_json(self):
        import json

        mw, inner = _make_middleware("secret")
        scope = _make_scope(headers={"authorization": "Bearer wrong"})
        send = AsyncMock()

        await mw(scope, AsyncMock(), send)

        calls = send.call_args_list
        # The body message is the second call
        body_msg = calls[1][0][0]
        body_bytes = body_msg.get("body", b"")
        parsed = json.loads(body_bytes)
        assert "error" in parsed
        assert parsed["error"] == "unauthorized"
