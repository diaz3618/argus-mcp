"""Tests for Phase 21 AUTH-02, AUTH-03, AUTH-04 hardening.

AUTH-02: XFF parsing with trusted_proxies guard
AUTH-03: TTLCache replaces unbounded defaultdict in rate limiter
AUTH-04: Origin validation defaults to strict; wildcard logs warning
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import cachetools
import pytest

from argus_mcp.config.schema_security import SecurityConfig
from argus_mcp.server.origin import OriginValidationMiddleware
from argus_mcp.server.rate_limit import RateLimitMiddleware

# ── AUTH-03: TTLCache storage ────────────────────────────────────────


class TestTTLCacheStorage:
    def test_rate_limiter_uses_ttlcache(self):
        m = RateLimitMiddleware(app=None)
        assert isinstance(m._request_log, cachetools.TTLCache)
        assert isinstance(m._auth_failure_log, cachetools.TTLCache)
        assert isinstance(m._lockouts, cachetools.TTLCache)

    def test_ttlcache_maxsize(self):
        m = RateLimitMiddleware(app=None)
        assert m._request_log.maxsize == 10000
        assert m._lockouts.maxsize == 10000

    @pytest.mark.asyncio
    async def test_retry_after_on_rate_limit(self):
        """Verify Retry-After header is still present on rate limit response."""
        from argus_mcp.config.schema_rate_limits import RateLimitRouteConfig, RateLimitsConfig

        config = RateLimitsConfig(default=RateLimitRouteConfig(requests=1, window_seconds=60))

        async def dummy_app(scope, receive, send):
            pass

        m = RateLimitMiddleware(app=dummy_app, config=config)
        scope = {
            "type": "http",
            "path": "/mcp",
            "client": ("1.2.3.4", 12345),
            "headers": [],
        }

        # First request should pass
        sent_messages = []

        async def mock_send(msg):
            sent_messages.append(msg)

        await m(scope, AsyncMock(), mock_send)

        # Second request should be rate limited
        sent_messages.clear()
        await m(scope, AsyncMock(), mock_send)

        # Find the response start message
        start_msg = next(m for m in sent_messages if m.get("type") == "http.response.start")
        assert start_msg["status"] == 429
        headers_dict = {k: v for k, v in start_msg.get("headers", [])}
        assert b"retry-after" in headers_dict


# ── AUTH-02: XFF with trusted_proxies ────────────────────────────────


class TestXFFTrustedProxies:
    def test_no_trusted_proxies_ignores_xff(self):
        m = RateLimitMiddleware(app=None)
        scope = {
            "client": ("1.2.3.4", 12345),
            "headers": [(b"x-forwarded-for", b"9.9.9.9")],
        }
        assert m._get_client_ip(scope) == "1.2.3.4"

    def test_trusted_proxy_reads_xff(self):
        m = RateLimitMiddleware(app=None, trusted_proxies=["10.0.0.0/8"])
        scope = {
            "client": ("10.0.0.1", 12345),
            "headers": [(b"x-forwarded-for", b"203.0.113.50, 10.0.0.2")],
        }
        assert m._get_client_ip(scope) == "203.0.113.50"

    def test_trusted_proxy_no_xff_falls_back(self):
        m = RateLimitMiddleware(app=None, trusted_proxies=["10.0.0.0/8"])
        scope = {"client": ("10.0.0.1", 12345), "headers": []}
        assert m._get_client_ip(scope) == "10.0.0.1"

    def test_all_xff_trusted_returns_leftmost(self):
        """When all IPs in XFF chain are trusted, return direct IP."""
        m = RateLimitMiddleware(app=None, trusted_proxies=["10.0.0.0/8"])
        scope = {
            "client": ("10.0.0.1", 12345),
            "headers": [(b"x-forwarded-for", b"10.0.0.5, 10.0.0.3")],
        }
        # All XFF IPs are in trusted range — falls back to direct IP
        assert m._get_client_ip(scope) == "10.0.0.1"

    def test_untrusted_direct_ip_ignores_xff(self):
        """When direct IP is NOT a trusted proxy, XFF is ignored."""
        m = RateLimitMiddleware(app=None, trusted_proxies=["10.0.0.0/8"])
        scope = {
            "client": ("203.0.113.1", 12345),
            "headers": [(b"x-forwarded-for", b"evil.spoofed.ip")],
        }
        assert m._get_client_ip(scope) == "203.0.113.1"

    def test_no_client_returns_unknown(self):
        m = RateLimitMiddleware(app=None)
        scope = {"headers": []}
        assert m._get_client_ip(scope) == "unknown"

    def test_trusted_proxies_validation(self):
        """SecurityConfig validates trusted_proxies entries."""
        # Valid entries
        cfg = SecurityConfig(trusted_proxies=["10.0.0.0/8", "172.16.0.1"])
        assert cfg.trusted_proxies == ["10.0.0.0/8", "172.16.0.1"]

        # Invalid entry
        with pytest.raises(Exception, match="not a valid IP"):
            SecurityConfig(trusted_proxies=["not-an-ip"])


# ── AUTH-04: Origin strict default + wildcard ────────────────────────


class TestOriginStrictDefault:
    def test_origin_constructor_default_is_strict(self):
        m = OriginValidationMiddleware(app=None)
        assert m._require_origin == "strict"

    def test_schema_require_origin_default_is_strict(self):
        assert SecurityConfig().require_origin == "strict"

    @pytest.mark.asyncio
    async def test_strict_rejects_missing_origin_non_localhost(self):
        """Strict mode rejects request with no Origin header from non-localhost."""
        sent_messages = []

        async def dummy_app(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b""})

        m = OriginValidationMiddleware(app=dummy_app, require_origin="strict")
        scope = {
            "type": "http",
            "path": "/mcp",
            "client": ("203.0.113.1", 12345),
            "headers": [],  # No Origin header
        }

        async def mock_send(msg):
            sent_messages.append(msg)

        await m(scope, AsyncMock(), mock_send)
        start_msg = next(m for m in sent_messages if m.get("type") == "http.response.start")
        assert start_msg["status"] == 403

    @pytest.mark.asyncio
    async def test_permissive_allows_missing_origin(self):
        """Permissive mode allows requests without Origin header."""
        called = []

        async def dummy_app(scope, receive, send):
            called.append(True)

        m = OriginValidationMiddleware(app=dummy_app, require_origin="permissive")
        scope = {
            "type": "http",
            "path": "/mcp",
            "client": ("203.0.113.1", 12345),
            "headers": [],
        }
        await m(scope, AsyncMock(), AsyncMock())
        assert called, "App should have been called in permissive mode"

    def test_wildcard_logs_warning(self, monkeypatch, caplog):
        """When '*' in allowed_origins, verify warning is logged."""
        monkeypatch.setenv("ARGUS_ALLOWED_ORIGINS", "*")
        # Runtime logging config (logging_config.py) sets propagate=False on
        # ancestor loggers (argus_mcp, argus_mcp.server), preventing records
        # from reaching the root logger where caplog's handler lives.  Force
        # propagation for the duration of this test.
        for name in ("argus_mcp", "argus_mcp.server", "argus_mcp.server.origin"):
            monkeypatch.setattr(logging.getLogger(name), "propagate", True)
        with caplog.at_level(logging.WARNING):
            m = OriginValidationMiddleware(app=None)
        assert m._wildcard is True
        assert "wildcard" in caplog.text.lower()

    @pytest.mark.asyncio
    async def test_wildcard_allows_any_origin(self, monkeypatch):
        """Wildcard allows any origin through."""
        monkeypatch.setenv("ARGUS_ALLOWED_ORIGINS", "*")
        called = []

        async def dummy_app(scope, receive, send):
            called.append(True)

        m = OriginValidationMiddleware(app=dummy_app)
        scope = {
            "type": "http",
            "path": "/mcp",
            "client": ("203.0.113.1", 12345),
            "headers": [(b"origin", b"https://evil.example.com")],
        }
        await m(scope, AsyncMock(), AsyncMock())
        assert called, "App should have been called with wildcard"
