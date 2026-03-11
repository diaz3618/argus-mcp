"""HTTP client for the Argus MCP management API.

Provides an async wrapper around the ``/manage/v1/`` endpoints so that the
TUI can connect to a *running* Argus server over the network instead of
hosting one in-process.
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx

from argus_mcp.server.management.schemas import (
    BackendsResponse,
    CapabilitiesResponse,
    EventsResponse,
    HealthResponse,
    ReAuthResponse,
    ReconnectResponse,
    ReloadResponse,
    ShutdownResponse,
    StatusResponse,
)

logger = logging.getLogger(__name__)

# Default timeout for regular API calls (seconds).
_DEFAULT_TIMEOUT = 10.0

# Timeout for mutating operations that may take longer.
_MUTATING_TIMEOUT = 30.0


class ApiClientError(Exception):
    """Raised when the management API returns an unexpected status."""

    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"HTTP {status_code}: {detail}")


class ApiClient:
    """Async HTTP client for the Argus Management API.

    Parameters
    ----------
    base_url:
        Root URL of the Argus server, e.g. ``http://127.0.0.1:9000``.
    token:
        Optional bearer token for authenticated endpoints.
    """

    def __init__(self, base_url: str, token: Optional[str] = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_url = f"{self._base_url}/manage/v1/"
        self._token = token
        self._client: Optional[httpx.AsyncClient] = None

    # ── Lifecycle ────────────────────────────────────────────────

    async def connect(self) -> None:
        """Create the underlying ``httpx.AsyncClient``."""
        headers: dict[str, str] = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        self._client = httpx.AsyncClient(
            base_url=self._api_url,
            headers=headers,
            timeout=_DEFAULT_TIMEOUT,
        )
        logger.info("ApiClient connected to %s", self._api_url)

    async def close(self) -> None:
        """Shut down the HTTP client gracefully."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
            logger.info("ApiClient closed")

    @property
    def is_connected(self) -> bool:
        """Return *True* if the underlying client is open."""
        return self._client is not None and not self._client.is_closed

    # ── Private helpers ──────────────────────────────────────────

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            raise RuntimeError("ApiClient is not connected — call connect() first")
        return self._client

    # ── Read-only endpoints ──────────────────────────────────────

    async def get_health(self) -> HealthResponse:
        """``GET /manage/v1/health``"""
        client = self._ensure_client()
        resp = await client.get("health")
        resp.raise_for_status()
        return HealthResponse.model_validate(resp.json())

    async def get_status(self) -> StatusResponse:
        """``GET /manage/v1/status``"""
        client = self._ensure_client()
        resp = await client.get("status")
        resp.raise_for_status()
        return StatusResponse.model_validate(resp.json())

    async def get_backends(self) -> BackendsResponse:
        """``GET /manage/v1/backends``"""
        client = self._ensure_client()
        resp = await client.get("backends")
        resp.raise_for_status()
        return BackendsResponse.model_validate(resp.json())

    async def get_capabilities(self) -> CapabilitiesResponse:
        """``GET /manage/v1/capabilities``"""
        client = self._ensure_client()
        resp = await client.get("capabilities")
        resp.raise_for_status()
        return CapabilitiesResponse.model_validate(resp.json())

    async def get_events(self, limit: int = 50) -> EventsResponse:
        """``GET /manage/v1/events``

        Parameters
        ----------
        limit:
            Maximum number of recent events to retrieve.
        """
        client = self._ensure_client()
        resp = await client.get("events", params={"limit": limit})
        resp.raise_for_status()
        return EventsResponse.model_validate(resp.json())

    # ── Mutating endpoints ───────────────────────────────────────

    async def post_reload(self) -> ReloadResponse:
        """``POST /manage/v1/reload``"""
        client = self._ensure_client()
        resp = await client.post("reload", timeout=_MUTATING_TIMEOUT)
        resp.raise_for_status()
        return ReloadResponse.model_validate(resp.json())

    async def post_reconnect(self, backend_name: str) -> ReconnectResponse:
        """``POST /manage/v1/reconnect/{name}``"""
        client = self._ensure_client()
        resp = await client.post(
            f"reconnect/{backend_name}",
            timeout=_MUTATING_TIMEOUT,
        )
        resp.raise_for_status()
        return ReconnectResponse.model_validate(resp.json())

    async def post_reauth(self, backend_name: str) -> ReAuthResponse:
        """``POST /manage/v1/reauth/{name}``"""
        client = self._ensure_client()
        resp = await client.post(
            f"reauth/{backend_name}",
            timeout=_MUTATING_TIMEOUT,
        )
        resp.raise_for_status()
        return ReAuthResponse.model_validate(resp.json())

    async def post_shutdown(self, timeout_seconds: float = 5.0) -> ShutdownResponse:
        """``POST /manage/v1/shutdown``"""
        client = self._ensure_client()
        resp = await client.post(
            "shutdown",
            json={"timeout_seconds": timeout_seconds},
            timeout=_MUTATING_TIMEOUT,
        )
        resp.raise_for_status()
        return ShutdownResponse.model_validate(resp.json())
