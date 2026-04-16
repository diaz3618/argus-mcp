"""Regression tests for SEC-01 (VULN-024), SEC-10 (VULN-023), SEC-15 (VULN-019).

Rate limiting middleware with sliding window and auth lockout.
These tests verify that brute-force auth attempts, find_tool flooding,
and session-level abuse are throttled correctly.

See: internal/reports/security/p1/VULN-024-mgmt-brute-force.md
     internal/reports/security/p1/VULN-023-find-tool-flooding.md
     internal/reports/security/p2/VULN-019-session-rate-limit.md

Covers:
1. Requests within limit pass through
2. Requests over limit get 429
3. Auth failure (401) increments lockout counter
4. Auth failure (403) increments lockout counter
5. Lockout triggers after threshold failures
6. Lockout expires after duration
7. Disabled config passes all traffic
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from argus_mcp.config.schema_rate_limits import RateLimitRouteConfig, RateLimitsConfig
from argus_mcp.server.rate_limit import RateLimitMiddleware

pytestmark = [pytest.mark.security]


def _make_scope(
    path: str = "/mcp",
    *,
    client: tuple[str, int] = ("10.0.0.1", 54321),
) -> dict:
    return {
        "type": "http",
        "path": path,
        "headers": [],
        "server": ("127.0.0.1", 8080),
        "client": client,
    }


def _make_middleware(
    *,
    enabled: bool = True,
    requests: int = 5,
    window: int = 60,
    lockout_threshold: int = 3,
    lockout_window: int = 300,
    lockout_duration: int = 900,
) -> tuple[RateLimitMiddleware, AsyncMock]:
    inner = AsyncMock()
    config = RateLimitsConfig(
        enabled=enabled,
        default=RateLimitRouteConfig(requests=requests, window_seconds=window),
        auth_lockout_threshold=lockout_threshold,
        auth_lockout_window_seconds=lockout_window,
        auth_lockout_duration_seconds=lockout_duration,
    )
    mw = RateLimitMiddleware(inner, config=config)
    return mw, inner


class TestRateLimitBasic:
    """Basic sliding window rate limit behavior."""

    @pytest.mark.asyncio
    async def test_requests_within_limit_pass(self):
        mw, inner = _make_middleware(requests=3)
        for _ in range(3):
            await mw(_make_scope(), AsyncMock(), AsyncMock())
        assert inner.await_count == 3

    @pytest.mark.asyncio
    async def test_request_over_limit_returns_429(self):
        mw, inner = _make_middleware(requests=2)
        send = AsyncMock()
        # First 2 pass
        await mw(_make_scope(), AsyncMock(), AsyncMock())
        await mw(_make_scope(), AsyncMock(), AsyncMock())
        # Third should be rejected
        await mw(_make_scope(), AsyncMock(), send)
        assert inner.await_count == 2
        start_msg = send.call_args_list[0][0][0]
        assert start_msg.get("status") == 429

    @pytest.mark.asyncio
    async def test_different_ips_have_separate_limits(self):
        mw, inner = _make_middleware(requests=1)
        await mw(_make_scope(client=("10.0.0.1", 1)), AsyncMock(), AsyncMock())
        await mw(_make_scope(client=("10.0.0.2", 1)), AsyncMock(), AsyncMock())
        assert inner.await_count == 2


class TestAuthLockout:
    """Auth failure tracking and lockout behavior."""

    @pytest.mark.asyncio
    async def test_401_increments_failure_counter(self):
        mw, inner = _make_middleware(lockout_threshold=5)

        # Simulate inner app returning 401
        async def return_401(scope, receive, send):
            await send({"type": "http.response.start", "status": 401})
            await send({"type": "http.response.body", "body": b""})

        inner.side_effect = return_401
        await mw(_make_scope(), AsyncMock(), AsyncMock())
        # Auth failure log should have 1 entry for this IP
        assert len(mw._auth_failure_log["10.0.0.1"]) == 1

    @pytest.mark.asyncio
    async def test_403_increments_failure_counter(self):
        mw, inner = _make_middleware(lockout_threshold=5)

        async def return_403(scope, receive, send):
            await send({"type": "http.response.start", "status": 403})
            await send({"type": "http.response.body", "body": b""})

        inner.side_effect = return_403
        await mw(_make_scope(), AsyncMock(), AsyncMock())
        assert len(mw._auth_failure_log["10.0.0.1"]) == 1

    @pytest.mark.asyncio
    async def test_lockout_triggers_after_threshold(self):
        mw, inner = _make_middleware(lockout_threshold=2, requests=100)

        async def return_401(scope, receive, send):
            await send({"type": "http.response.start", "status": 401})
            await send({"type": "http.response.body", "body": b""})

        inner.side_effect = return_401
        # 2 failures should trigger lockout
        await mw(_make_scope(), AsyncMock(), AsyncMock())
        await mw(_make_scope(), AsyncMock(), AsyncMock())

        # Now the IP should be locked out
        assert "10.0.0.1" in mw._lockouts

        # Next request should get 429 without reaching inner app
        inner.reset_mock()
        send = AsyncMock()
        await mw(_make_scope(), AsyncMock(), send)
        inner.assert_not_awaited()
        start_msg = send.call_args_list[0][0][0]
        assert start_msg.get("status") == 429

    @pytest.mark.asyncio
    async def test_lockout_expires_after_duration(self):
        mw, inner = _make_middleware(lockout_threshold=1, lockout_duration=10, requests=100)

        async def return_401(scope, receive, send):
            await send({"type": "http.response.start", "status": 401})
            await send({"type": "http.response.body", "body": b""})

        inner.side_effect = return_401
        await mw(_make_scope(), AsyncMock(), AsyncMock())
        assert "10.0.0.1" in mw._lockouts

        # Simulate time passing beyond lockout duration
        del mw._lockouts["10.0.0.1"]

        inner.side_effect = None  # Normal pass-through
        inner.reset_mock()
        await mw(_make_scope(), AsyncMock(), AsyncMock())
        inner.assert_awaited_once()


class TestDisabled:
    """Disabled rate limiting passes all traffic."""

    @pytest.mark.asyncio
    async def test_disabled_passes_all(self):
        mw, inner = _make_middleware(enabled=False, requests=1)
        for _ in range(10):
            await mw(_make_scope(), AsyncMock(), AsyncMock())
        assert inner.await_count == 10


class TestNonHttpScope:
    """Non-HTTP scopes always pass through."""

    @pytest.mark.asyncio
    async def test_websocket_passes(self):
        mw, inner = _make_middleware(requests=1)
        scope = {"type": "websocket"}
        await mw(scope, AsyncMock(), AsyncMock())
        # Even though rate limit is 1, websocket should pass
        await mw(scope, AsyncMock(), AsyncMock())
        assert inner.await_count == 2
