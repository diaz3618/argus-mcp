"""Read-only async client for the MCP Registry API v0.1.

Communicates with a registry endpoint that implements the ``/v0/servers``
REST contract to list and search registered MCP servers.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from argus_mcp.registry.cache import RegistryCache
from argus_mcp.registry.models import ServerEntry, ServerPage

logger = logging.getLogger(__name__)


class RegistryClient:
    """Async HTTP client for the MCP Registry API.

    Parameters
    ----------
    base_url:
        Root URL of the registry (e.g. ``https://registry.example.com``).
    headers:
        Extra headers applied to every request (auth tokens, etc.).
    cache:
        Optional :class:`RegistryCache` for offline/fallback support.
    timeout:
        HTTP request timeout in seconds.
    """

    def __init__(
        self,
        base_url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        cache: Optional[RegistryCache] = None,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = headers or {}
        self._cache = cache
        self._timeout = timeout
        self._client: Any = None  # lazy httpx.AsyncClient

    async def _ensure_client(self) -> Any:
        if self._client is None:
            import httpx  # lazy import

            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers,
                timeout=self._timeout,
            )
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def list_servers(
        self,
        *,
        cursor: Optional[str] = None,
        limit: int = 50,
    ) -> ServerPage:
        """Fetch a page of servers from ``GET /v0/servers``.

        Falls back to cached data when the registry is unreachable.
        """
        params: Dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor

        try:
            client = await self._ensure_client()
            resp = await client.get("/v0/servers", params=params)
            resp.raise_for_status()
            page = ServerPage.from_dict(resp.json())
            if self._cache and not cursor:
                self._cache.put(self._base_url, page.servers)
            return page
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Registry request failed (%s), falling back to cache: %s",
                self._base_url,
                exc,
            )
            return self._fallback_page()

    async def get_server(self, name: str) -> Optional[ServerEntry]:
        """Fetch a single server by name from ``GET /v0/servers/{name}``."""
        try:
            client = await self._ensure_client()
            resp = await client.get(f"/v0/servers/{name}")
            resp.raise_for_status()
            return ServerEntry.from_dict(resp.json())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Registry get_server(%s) failed: %s", name, exc)
            return self._fallback_server(name)

    async def search(
        self,
        query: str,
        *,
        limit: int = 50,
    ) -> List[ServerEntry]:
        """Search for servers matching *query*.

        If the registry supports a search endpoint, use it.
        Otherwise, falls back to client-side filtering of list results.
        """
        try:
            client = await self._ensure_client()
            resp = await client.get(
                "/v0/servers",
                params={"q": query, "limit": limit},
            )
            resp.raise_for_status()
            page = ServerPage.from_dict(resp.json())
            return page.servers
        except Exception:  # noqa: BLE001
            # Fallback: filter cached entries
            cached = self._fallback_page().servers
            q = query.lower()
            return [s for s in cached if q in s.name.lower() or q in s.description.lower()]

    def _fallback_page(self) -> ServerPage:
        if self._cache:
            entries = self._cache.get(self._base_url)
            if entries is not None:
                return ServerPage(servers=entries)
        return ServerPage(servers=[])

    def _fallback_server(self, name: str) -> Optional[ServerEntry]:
        page = self._fallback_page()
        for s in page.servers:
            if s.name == name:
                return s
        return None
