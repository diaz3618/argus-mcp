"""HTTP client for the Argus MCP management API.

Provides an async wrapper around the ``/manage/v1/`` endpoints that can
be shared by TUI, REPL, and any future client code.
"""

from __future__ import annotations

import json as _json
import logging
from collections.abc import AsyncIterator
from typing import Any, Optional, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from argus_mcp.api.schemas import (
    BackendsResponse,
    CapabilitiesResponse,
    EventsResponse,
    HealthResponse,
    ReadyResponse,
    ReAuthResponse,
    ReconnectResponse,
    ReloadResponse,
    SessionsResponse,
    ShutdownResponse,
    StatusResponse,
)

logger = logging.getLogger(__name__)

# Default timeout for regular API calls (seconds).
_DEFAULT_TIMEOUT = 10.0

# Timeout for mutating operations that may take longer.
_MUTATING_TIMEOUT = 30.0

_M = TypeVar("_M", bound=BaseModel)


class ApiClientError(Exception):
    """Raised when a management API request fails."""

    def __init__(self, message: str, *, status_code: int | None = None, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(message)


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

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            raise ApiClientError("ApiClient is not connected — call connect() first")
        return self._client

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Execute an HTTP request, translating errors to :class:`ApiClientError`."""
        client = self._ensure_client()
        try:
            resp = await getattr(client, method)(path, **kwargs)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as exc:
            raise ApiClientError(
                f"HTTP {exc.response.status_code}: {path}",
                status_code=exc.response.status_code,
                detail=exc.response.text[:500],
            ) from exc
        except httpx.HTTPError as exc:
            raise ApiClientError(f"Request failed ({path}): {exc}") from exc

    def _validate(self, model: Type[_M], data: Any, path: str) -> _M:
        """Deserialize *data* into *model*, wrapping validation errors."""
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            raise ApiClientError(f"Invalid response from {path}: {exc}") from exc

    # ── GET endpoints ──────────────────────────────────────────────────

    async def get_health(self) -> HealthResponse:
        """``GET /manage/v1/health``"""
        resp = await self._request("get", "health")
        return self._validate(HealthResponse, resp.json(), "health")

    async def get_status(self) -> StatusResponse:
        """``GET /manage/v1/status``"""
        resp = await self._request("get", "status")
        return self._validate(StatusResponse, resp.json(), "status")

    async def get_backends(self) -> BackendsResponse:
        """``GET /manage/v1/backends``"""
        resp = await self._request("get", "backends")
        return self._validate(BackendsResponse, resp.json(), "backends")

    async def get_capabilities(self) -> CapabilitiesResponse:
        """``GET /manage/v1/capabilities``"""
        resp = await self._request("get", "capabilities")
        return self._validate(CapabilitiesResponse, resp.json(), "capabilities")

    async def get_events(self, limit: int = 50) -> EventsResponse:
        """``GET /manage/v1/events``"""
        resp = await self._request("get", "events", params={"limit": limit})
        return self._validate(EventsResponse, resp.json(), "events")

    async def get_ready(self) -> ReadyResponse:
        """``GET /manage/v1/ready``"""
        resp = await self._request("get", "ready")
        return self._validate(ReadyResponse, resp.json(), "ready")

    async def get_sessions(self) -> SessionsResponse:
        """``GET /manage/v1/sessions``"""
        resp = await self._request("get", "sessions")
        return self._validate(SessionsResponse, resp.json(), "sessions")

    async def get_groups(self, group: Optional[str] = None) -> dict:
        """``GET /manage/v1/groups``"""
        params: dict[str, str] = {}
        if group is not None:
            params["group"] = group
        resp = await self._request("get", "groups", params=params)
        return resp.json()

    # ── SSE streaming ──────────────────────────────────────────────────

    async def stream_events(self) -> AsyncIterator[dict[str, Any]]:
        """``GET /manage/v1/events/stream`` — SSE event stream.

        Yields parsed event dicts as they arrive.  Heartbeat events
        (``event: heartbeat``) are silently skipped.
        """
        client = self._ensure_client()
        async with client.stream("GET", "events/stream", timeout=None) as resp:
            resp.raise_for_status()
            event_type: str = ""
            data_buf: list[str] = []
            async for raw_line in resp.aiter_lines():
                line = raw_line.rstrip("\n")
                if line.startswith("event:"):
                    event_type = line[len("event:") :].strip()
                elif line.startswith("data:"):
                    data_buf.append(line[len("data:") :].strip())
                elif line == "":
                    # Blank line = end of SSE message
                    if data_buf and event_type != "heartbeat":
                        try:
                            payload = _json.loads("\n".join(data_buf))
                            yield payload
                        except _json.JSONDecodeError:
                            logger.debug("Malformed SSE data: %s", data_buf)
                    event_type = ""
                    data_buf = []

    # ── POST endpoints ─────────────────────────────────────────────────

    async def post_reload(self) -> ReloadResponse:
        """``POST /manage/v1/reload``"""
        resp = await self._request("post", "reload", timeout=_MUTATING_TIMEOUT)
        return self._validate(ReloadResponse, resp.json(), "reload")

    async def post_reconnect(self, backend_name: str) -> ReconnectResponse:
        """``POST /manage/v1/reconnect/{name}``"""
        resp = await self._request("post", f"reconnect/{backend_name}", timeout=_MUTATING_TIMEOUT)
        return self._validate(ReconnectResponse, resp.json(), "reconnect")

    async def post_reauth(self, backend_name: str) -> ReAuthResponse:
        """``POST /manage/v1/reauth/{name}``"""
        resp = await self._request("post", f"reauth/{backend_name}", timeout=_MUTATING_TIMEOUT)
        return self._validate(ReAuthResponse, resp.json(), "reauth")

    async def post_shutdown(self, timeout_seconds: float = 5.0) -> ShutdownResponse:
        """``POST /manage/v1/shutdown``"""
        resp = await self._request(
            "post",
            "shutdown",
            json={"timeout_seconds": timeout_seconds},
            timeout=_MUTATING_TIMEOUT,
        )
        return self._validate(ShutdownResponse, resp.json(), "shutdown")
