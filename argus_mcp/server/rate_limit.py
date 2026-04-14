"""Sliding-window rate limiting middleware with auth lockout.

Pure ASGI middleware (no ``BaseHTTPMiddleware``).  Enforces per-IP
sliding-window counters and temporarily locks out clients that exceed
a configurable number of authentication failures (401/403).
"""

import logging
import time
from typing import List, Optional, Tuple

from cachetools import TTLCache
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from argus_mcp.config.schema_rate_limits import RateLimitsConfig

logger = logging.getLogger(__name__)


class RateLimitMiddleware:
    """Per-IP sliding-window rate limiter with auth-failure lockout.

    Usage::

        middleware = RateLimitMiddleware(app, config=RateLimitsConfig())
    """

    def __init__(self, app: ASGIApp, config: Optional[RateLimitsConfig] = None) -> None:
        self.app = app
        self._config = config or RateLimitsConfig()
        # Per-IP request timestamps for sliding window (TTL auto-evicts stale IPs)
        self._request_log: TTLCache = TTLCache(
            maxsize=10000, ttl=self._config.default.window_seconds
        )
        # Per-IP auth-failure timestamps (TTL matches auth lockout window)
        self._auth_failure_log: TTLCache = TTLCache(
            maxsize=10000, ttl=self._config.auth_lockout_window_seconds
        )
        # Per-IP lockout expiry (TTL auto-evicts expired lockouts)
        self._lockouts: TTLCache = TTLCache(
            maxsize=10000, ttl=self._config.auth_lockout_duration_seconds
        )

        if self._config.enabled:
            logger.info(
                "Rate limiting ENABLED: %d req/%ds, auth lockout after %d failures/%ds",
                self._config.default.requests,
                self._config.default.window_seconds,
                self._config.auth_lockout_threshold,
                self._config.auth_lockout_window_seconds,
            )
        else:
            logger.info("Rate limiting DISABLED.")

    def _get_client_ip(self, scope: Scope) -> str:
        """Extract client IP from ASGI scope."""
        client: Optional[Tuple[str, int]] = scope.get("client")
        return client[0] if client else "unknown"

    def _is_locked_out(self, ip: str, now: float) -> bool:
        """Check if an IP is currently locked out.

        TTLCache auto-evicts expired lockouts, so presence implies active lockout.
        """
        return ip in self._lockouts

    def _prune_window(self, timestamps: List[float], window_start: float) -> List[float]:
        """Remove timestamps outside the sliding window."""
        return [ts for ts in timestamps if ts >= window_start]

    def _check_rate_limit(self, ip: str, now: float) -> bool:
        """Return True if the request is within the rate limit."""
        window = self._config.default.window_seconds
        window_start = now - window
        timestamps = self._request_log.get(ip, [])
        timestamps = self._prune_window(timestamps, window_start)
        if len(timestamps) >= self._config.default.requests:
            self._request_log[ip] = timestamps
            return False
        timestamps.append(now)
        self._request_log[ip] = timestamps
        return True

    def _record_auth_failure(self, ip: str, now: float) -> None:
        """Record an auth failure and apply lockout if threshold is exceeded."""
        window_start = now - self._config.auth_lockout_window_seconds
        timestamps = self._auth_failure_log.get(ip, [])
        timestamps = self._prune_window(timestamps, window_start)
        timestamps.append(now)
        self._auth_failure_log[ip] = timestamps

        if len(timestamps) >= self._config.auth_lockout_threshold:
            self._lockouts[ip] = now + self._config.auth_lockout_duration_seconds
            self._auth_failure_log.pop(ip, None)
            logger.warning(
                "Auth lockout applied to %s for %ds after %d failures",
                ip,
                self._config.auth_lockout_duration_seconds,
                self._config.auth_lockout_threshold,
            )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if not self._config.enabled:
            await self.app(scope, receive, send)
            return

        now = time.monotonic()
        ip = self._get_client_ip(scope)

        # Check lockout first
        if self._is_locked_out(ip, now):
            logger.warning(
                "Locked-out client %s attempted request to %s", ip, scope.get("path", "/")
            )
            response = JSONResponse(
                {
                    "error": "too_many_requests",
                    "message": "Too many authentication failures. Try again later.",
                },
                status_code=429,
                headers={"Retry-After": str(self._config.auth_lockout_duration_seconds)},
            )
            await response(scope, receive, send)
            return

        # Check rate limit
        if not self._check_rate_limit(ip, now):
            logger.warning(
                "Rate limit exceeded for %s on %s",
                ip,
                scope.get("path", "/"),
            )
            response = JSONResponse(
                {"error": "too_many_requests", "message": "Rate limit exceeded."},
                status_code=429,
                headers={"Retry-After": str(self._config.default.window_seconds)},
            )
            await response(scope, receive, send)
            return

        # Wrap send to intercept response status for auth-failure tracking
        captured_status: List[int] = []

        async def send_wrapper(message):
            if message.get("type") == "http.response.start":
                status = message.get("status", 200)
                captured_status.append(status)
            await send(message)

        await self.app(scope, receive, send_wrapper)

        # Check if the response was an auth failure
        if captured_status and captured_status[0] in (401, 403):
            self._record_auth_failure(ip, now)
