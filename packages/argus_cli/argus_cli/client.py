"""HTTP API client for the Argus MCP Management API.

Provides both sync (``ArgusClient``) and async (``AsyncArgusClient``)
clients for one-shot commands and REPL mode respectively.
"""

from __future__ import annotations

__all__ = ["ArgusClient", "ArgusClientError", "AsyncArgusClient"]

import json
import sys
import time
from collections.abc import AsyncGenerator
from typing import Any

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self

import httpx

from argus_cli.config import CliConfig

# ── Timeout configuration ──────────────────────────────────────────────

DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=30.0, write=10.0, pool=5.0)
SSE_TIMEOUT = httpx.Timeout(connect=5.0, read=None, write=10.0, pool=5.0)

# ── Retry configuration ────────────────────────────────────────────────

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 0.5  # seconds; doubles each attempt


class ArgusClientError(Exception):
    """Raised when the API returns an error response."""

    def __init__(self, status_code: int, error: str, message: str) -> None:
        self.status_code = status_code
        self.error = error
        self.message = message
        super().__init__(f"[{status_code}] {error}: {message}")


def _build_headers(config: CliConfig) -> dict[str, str]:
    """Build request headers including optional auth token."""
    headers: dict[str, str] = {"Accept": "application/json"}
    if config.token:
        headers["Authorization"] = f"Bearer {config.token}"
    return headers


def _build_group_params(group: str | None) -> dict[str, str]:
    """Build query params for the /groups endpoint."""
    return {"group": group} if group else {}


def _build_capabilities_params(
    *,
    type_filter: str | None = None,
    backend: str | None = None,
    search: str | None = None,
) -> dict[str, str]:
    """Build query params for the /capabilities endpoint."""
    params: dict[str, str] = {}
    if type_filter:
        params["type"] = type_filter
    if backend:
        params["backend"] = backend
    if search:
        params["search"] = search
    return params


def _build_events_params(
    *,
    limit: int = 100,
    since: str | None = None,
    severity: str | None = None,
) -> dict[str, str]:
    """Build query params for the /events endpoint."""
    params: dict[str, str] = {"limit": str(limit)}
    if since:
        params["since"] = since
    if severity:
        params["severity"] = severity
    return params


def _handle_response(response: httpx.Response) -> dict[str, Any]:
    """Parse response JSON and raise on error status codes."""
    if response.status_code >= 400:
        try:
            body = response.json()
            raise ArgusClientError(
                status_code=response.status_code,
                error=body.get("error", "unknown_error"),
                message=body.get("message", response.text),
            )
        except (json.JSONDecodeError, KeyError) as exc:
            raise ArgusClientError(
                status_code=response.status_code,
                error="http_error",
                message=response.text,
            ) from exc
    try:
        result: dict[str, Any] = response.json()
        return result
    except json.JSONDecodeError as exc:
        raise ArgusClientError(
            status_code=response.status_code,
            error="parse_error",
            message="Response is not valid JSON",
        ) from exc


# ── Sync client (one-shot commands) ────────────────────────────────────


class ArgusClient:
    """Synchronous httpx client for one-shot CLI commands."""

    def __init__(self, config: CliConfig) -> None:
        """Initialise the client with resolved CLI configuration.

        Args:
            config: Resolved CLI configuration containing the server URL,
                    auth token, and timeout settings.
        """
        self._config = config
        self._client = httpx.Client(
            base_url=config.base_url,
            headers=_build_headers(config),
            timeout=DEFAULT_TIMEOUT,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Send an HTTP request with transport error handling and retry."""
        last_exc: ArgusClientError | None = None
        for attempt in range(MAX_RETRIES):
            try:
                response = getattr(self._client, method)(path, **kwargs)
                return _handle_response(response)
            except httpx.ConnectError as exc:
                last_exc = ArgusClientError(
                    0,
                    "connection_error",
                    f"Cannot connect to {self._config.server_url}",
                )
                last_exc.__cause__ = exc
            except httpx.TimeoutException as exc:
                last_exc = ArgusClientError(
                    0,
                    "timeout_error",
                    "Request timed out",
                )
                last_exc.__cause__ = exc
            except httpx.TransportError as exc:
                last_exc = ArgusClientError(
                    0,
                    "transport_error",
                    f"Network error: {exc}",
                )
                last_exc.__cause__ = exc
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF_BASE * (2**attempt))
        raise last_exc  # type: ignore[misc]

    # ── GET endpoints ──────────────────────────────────────────────────

    def health(self) -> dict[str, Any]:
        return self._request("get", "/health")

    def status(self) -> dict[str, Any]:
        return self._request("get", "/status")

    def backends(self) -> dict[str, Any]:
        return self._request("get", "/backends")

    def groups(self, group: str | None = None) -> dict[str, Any]:
        return self._request("get", "/groups", params=_build_group_params(group))

    def capabilities(
        self,
        *,
        type_filter: str | None = None,
        backend: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        params = _build_capabilities_params(
            type_filter=type_filter,
            backend=backend,
            search=search,
        )
        return self._request("get", "/capabilities", params=params)

    def sessions(self) -> dict[str, Any]:
        return self._request("get", "/sessions")

    def events(
        self,
        *,
        limit: int = 100,
        since: str | None = None,
        severity: str | None = None,
    ) -> dict[str, Any]:
        params = _build_events_params(limit=limit, since=since, severity=severity)
        return self._request("get", "/events", params=params)

    # ── POST endpoints ─────────────────────────────────────────────────

    def reload(self) -> dict[str, Any]:
        return self._request("post", "/reload")

    def reconnect(self, name: str) -> dict[str, Any]:
        return self._request("post", f"/reconnect/{name}")

    def shutdown(self, timeout_seconds: int = 30) -> dict[str, Any]:
        return self._request("post", "/shutdown", json={"timeout_seconds": timeout_seconds})


# ── Async client (REPL mode) ──────────────────────────────────────────


class AsyncArgusClient:
    """Async httpx client for REPL mode."""

    def __init__(self, config: CliConfig) -> None:
        """Initialise the async client with resolved CLI configuration.

        Args:
            config: Resolved CLI configuration containing the server URL,
                    auth token, and timeout settings.
        """
        self._config = config
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            headers=_build_headers(config),
            timeout=DEFAULT_TIMEOUT,
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Send an async HTTP request with transport error handling and retry."""
        import asyncio

        last_exc: ArgusClientError | None = None
        for attempt in range(MAX_RETRIES):
            try:
                response = await getattr(self._client, method)(path, **kwargs)
                return _handle_response(response)
            except httpx.ConnectError as exc:
                last_exc = ArgusClientError(
                    0,
                    "connection_error",
                    f"Cannot connect to {self._config.server_url}",
                )
                last_exc.__cause__ = exc
            except httpx.TimeoutException as exc:
                last_exc = ArgusClientError(
                    0,
                    "timeout_error",
                    "Request timed out",
                )
                last_exc.__cause__ = exc
            except httpx.TransportError as exc:
                last_exc = ArgusClientError(
                    0,
                    "transport_error",
                    f"Network error: {exc}",
                )
                last_exc.__cause__ = exc
            if attempt < MAX_RETRIES - 1:
                await asyncio.sleep(RETRY_BACKOFF_BASE * (2**attempt))
        raise last_exc  # type: ignore[misc]

    # ── GET endpoints ──────────────────────────────────────────────────

    async def health(self) -> dict[str, Any]:
        return await self._request("get", "/health")

    async def status(self) -> dict[str, Any]:
        return await self._request("get", "/status")

    async def backends(self) -> dict[str, Any]:
        return await self._request("get", "/backends")

    async def groups(self, group: str | None = None) -> dict[str, Any]:
        return await self._request("get", "/groups", params=_build_group_params(group))

    async def capabilities(
        self,
        *,
        type_filter: str | None = None,
        backend: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        params = _build_capabilities_params(
            type_filter=type_filter,
            backend=backend,
            search=search,
        )
        return await self._request("get", "/capabilities", params=params)

    async def sessions(self) -> dict[str, Any]:
        return await self._request("get", "/sessions")

    async def events(
        self,
        *,
        limit: int = 100,
        since: str | None = None,
        severity: str | None = None,
    ) -> dict[str, Any]:
        params = _build_events_params(limit=limit, since=since, severity=severity)
        return await self._request("get", "/events", params=params)

    # ── POST endpoints ─────────────────────────────────────────────────

    async def reload(self) -> dict[str, Any]:
        return await self._request("post", "/reload")

    async def reconnect(self, name: str) -> dict[str, Any]:
        return await self._request("post", f"/reconnect/{name}")

    async def shutdown(self, timeout_seconds: int = 30) -> dict[str, Any]:
        return await self._request("post", "/shutdown", json={"timeout_seconds": timeout_seconds})

    # ── SSE streaming ──────────────────────────────────────────────────

    async def events_stream(self) -> AsyncGenerator[dict[str, Any], None]:
        """Yield SSE events from /events/stream as dicts.

        Yields:
            dict with keys: event, data, id (parsed from SSE format)
        """
        from httpx_sse import aconnect_sse

        async with aconnect_sse(
            self._client,
            "GET",
            "/events/stream",
            timeout=SSE_TIMEOUT,
        ) as event_source:
            async for sse in event_source.aiter_sse():
                try:
                    data = json.loads(sse.data)
                except (json.JSONDecodeError, TypeError):
                    data = sse.data
                yield {
                    "event": sse.event,
                    "data": data,
                    "id": sse.id,
                }
