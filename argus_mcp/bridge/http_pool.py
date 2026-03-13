"""Singleton async HTTP client pool.

Provides a shared :class:`httpx.AsyncClient` with configurable connection
limits so that TCP/TLS handshakes are amortised across the process lifetime.

Usage::

    pool = HttpPool(max_connections=200, max_keepalive=100)
    await pool.start()
    client = pool.client          # → httpx.AsyncClient
    resp = await client.get(...)
    ...
    await pool.stop()

Auth-related code (discovery, PKCE, provider, OIDC) intentionally creates
its own short-lived ``httpx.AsyncClient`` per request because those flows
use security-critical settings (``follow_redirects=False``, SSRF guards)
that must not be shared.  The pool targets *backend connectivity* and
internal management API traffic.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MAX_CONNECTIONS: int = 200
DEFAULT_MAX_KEEPALIVE: int = 100
DEFAULT_TIMEOUT: float = 30.0


class HttpPool:
    """Process-wide ``httpx.AsyncClient`` wrapper with connection pooling.

    Parameters
    ----------
    max_connections:
        Hard cap on simultaneous connections across all hosts.
    max_keepalive:
        Maximum idle keep-alive connections.
    timeout:
        Default request timeout in seconds (individual call sites can
        still pass their own ``timeout=`` kwargs to override).
    """

    def __init__(
        self,
        *,
        max_connections: int = DEFAULT_MAX_CONNECTIONS,
        max_keepalive: int = DEFAULT_MAX_KEEPALIVE,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._max_connections = max_connections
        self._max_keepalive = max_keepalive
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Create the underlying ``httpx.AsyncClient`` if not already running."""
        async with self._lock:
            if self._client is not None and not self._client.is_closed:
                return
            limits = httpx.Limits(
                max_connections=self._max_connections,
                max_keepalive_connections=self._max_keepalive,
            )
            self._client = httpx.AsyncClient(
                limits=limits,
                timeout=self._timeout,
                follow_redirects=False,
            )
            logger.info(
                "HttpPool started (max_conn=%d, keepalive=%d, timeout=%.1fs)",
                self._max_connections,
                self._max_keepalive,
                self._timeout,
            )

    async def stop(self) -> None:
        """Close the client and release all connections."""
        async with self._lock:
            if self._client is not None:
                await self._client.aclose()
                logger.info("HttpPool stopped — all connections closed")
                self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        """Return the live ``httpx.AsyncClient``.

        Raises :class:`RuntimeError` if the pool has not been started.
        """
        if self._client is None or self._client.is_closed:
            raise RuntimeError("HttpPool is not running — call start() first")
        return self._client

    @property
    def is_running(self) -> bool:
        """``True`` when the underlying client is open."""
        return self._client is not None and not self._client.is_closed

    def stats(self) -> dict:
        """Return a snapshot of pool configuration and state."""
        return {
            "running": self.is_running,
            "max_connections": self._max_connections,
            "max_keepalive": self._max_keepalive,
            "timeout": self._timeout,
        }
