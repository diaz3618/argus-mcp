"""Read-only async client for MCP server registries.

Supports multiple registry backends (Glama, Smithery, generic) with
automatic detection from the base URL.  Each backend has its own API
path, query-parameter names, and response-to-model mapping.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Literal, Optional

from argus_mcp.registry.cache import RegistryCache
from argus_mcp.registry.models import ServerEntry, ServerPage

logger = logging.getLogger(__name__)

RegistryType = Literal["auto", "glama", "smithery", "generic"]

# ---------------------------------------------------------------------------
# Per-registry profiles
# ---------------------------------------------------------------------------

_GLAMA_PATH = "/v1/servers"
_SMITHERY_PATH = "/servers"
_GENERIC_PATH = "/v0.1/servers"


def _detect_type(url: str) -> RegistryType:
    """Guess registry type from the base URL."""
    u = url.lower()
    if "glama.ai" in u:
        return "glama"
    if "smithery.ai" in u:
        return "smithery"
    return "generic"


def _list_params(rtype: RegistryType, limit: int, cursor: Optional[str]) -> Dict[str, Any]:
    """Build query-string parameters for a list request."""
    if rtype == "glama":
        params: Dict[str, Any] = {"first": limit}
        if cursor:
            params["after"] = cursor
        return params
    if rtype == "smithery":
        params = {"pageSize": limit}
        if cursor:
            params["page"] = cursor
        return params
    # generic / MCP Registry spec
    params = {"limit": limit}
    if cursor:
        params["cursor"] = cursor
    return params


def _search_params(rtype: RegistryType, query: str, limit: int) -> Dict[str, Any]:
    """Build query-string parameters for a search request."""
    if rtype == "glama":
        return {"query": query, "first": limit}
    if rtype == "smithery":
        return {"q": query, "pageSize": limit}
    return {"q": query, "limit": limit}


def _server_path(rtype: RegistryType) -> str:
    """Return the API path for the servers endpoint."""
    if rtype == "glama":
        return _GLAMA_PATH
    if rtype == "smithery":
        return _SMITHERY_PATH
    return _GENERIC_PATH


def _parse_page(rtype: RegistryType, data: Dict[str, Any]) -> ServerPage:
    """Parse the API JSON response into a :class:`ServerPage`."""
    raw_servers = data.get("servers") or data.get("items") or []

    entries: List[ServerEntry] = []
    for item in raw_servers:
        if not isinstance(item, dict):
            continue
        # Some APIs nest the server object under a "server" key
        server_data = item.get("server", item)
        entries.append(_entry_from_raw(rtype, server_data, item))

    # Extract pagination cursor for next page
    next_cursor: Optional[str] = None
    total: Optional[int] = None
    if rtype == "glama":
        page_info = data.get("pageInfo", {})
        if page_info.get("hasNextPage"):
            next_cursor = page_info.get("endCursor")
    elif rtype == "smithery":
        pagination = data.get("pagination", {})
        total = pagination.get("totalCount")
        current = pagination.get("currentPage", 1)
        total_pages = pagination.get("totalPages", 1)
        if current < total_pages:
            next_cursor = str(current + 1)
    else:
        next_cursor = data.get("next_cursor") or data.get("nextCursor")
        total = data.get("total")

    return ServerPage(servers=entries, next_cursor=next_cursor, total=total)


def _entry_from_raw(
    rtype: RegistryType,
    server: Dict[str, Any],
    envelope: Dict[str, Any],
) -> ServerEntry:
    """Normalise a single server JSON object to a :class:`ServerEntry`."""
    if rtype == "glama":
        return ServerEntry.from_dict(
            {
                "name": server.get("name", ""),
                "description": server.get("description", ""),
                "url": server.get("url", ""),
                "icon_url": server.get("iconUrl", ""),
                "version": "",
                "transport": _glama_transport(server),
                "tools": server.get("tools") or [],
                "categories": _glama_categories(server),
                "_source": "glama",
                "namespace": server.get("namespace", ""),
                "slug": server.get("slug", ""),
                "repository": server.get("repository"),
            }
        )
    if rtype == "smithery":
        return ServerEntry.from_dict(
            {
                "name": server.get("displayName") or server.get("qualifiedName", ""),
                "description": server.get("description", ""),
                "url": server.get("homepage", ""),
                "icon_url": server.get("iconUrl", ""),
                "version": "",
                "transport": "streamable-http" if server.get("remote") else "stdio",
                "tools": [],
                "categories": [],
                "_source": "smithery",
                "qualifiedName": server.get("qualifiedName", ""),
                "namespace": server.get("namespace", ""),
                "slug": server.get("slug", ""),
                "verified": server.get("verified", False),
                "useCount": server.get("useCount", 0),
            }
        )
    # generic — pass through
    return ServerEntry.from_dict(server)


def _glama_transport(server: Dict[str, Any]) -> str:
    attrs = server.get("attributes") or []
    if "hosting:remote-capable" in attrs:
        return "streamable-http"
    return "stdio"


def _glama_categories(server: Dict[str, Any]) -> List[str]:
    attrs = server.get("attributes") or []
    return [a for a in attrs if not a.startswith("hosting:")]


class RegistryClient:
    """Async HTTP client for MCP server registries.

    Supports Glama, Smithery, and generic (MCP Registry spec) backends.
    The backend type is auto-detected from the URL or set explicitly.

    Parameters
    ----------
    base_url:
        Root URL of the registry (e.g. ``https://glama.ai/api/mcp``).
    registry_type:
        ``"auto"`` (default) detects from URL, or force a specific type.
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
        registry_type: RegistryType = "auto",
        headers: Optional[Dict[str, str]] = None,
        cache: Optional[RegistryCache] = None,
        timeout: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._rtype: RegistryType = (
            _detect_type(self._base_url) if registry_type == "auto" else registry_type
        )
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
        """Fetch a page of servers from the registry.

        Falls back to cached data when the registry is unreachable.
        """
        path = _server_path(self._rtype)
        params = _list_params(self._rtype, limit, cursor)

        try:
            client = await self._ensure_client()
            resp = await client.get(path, params=params)
            resp.raise_for_status()
            page = _parse_page(self._rtype, resp.json())
            if self._cache and not cursor:
                self._cache.put(self._base_url, page.servers)
            logger.info(
                "Registry %s (%s) returned %d servers",
                self._base_url,
                self._rtype,
                len(page.servers),
            )
            return page
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Registry request failed (%s, type=%s, path=%s): %s",
                self._base_url,
                self._rtype,
                path,
                exc,
            )
            return self._fallback_page()

    async def list_all_servers(self, *, limit: int = 50, max_pages: int = 20) -> List[ServerEntry]:
        """Fetch all pages of servers from the registry.

        Follows pagination cursors up to *max_pages* pages.
        """
        all_entries: List[ServerEntry] = []
        cursor: Optional[str] = None
        for _ in range(max_pages):
            page = await self.list_servers(cursor=cursor, limit=limit)
            all_entries.extend(page.servers)
            if not page.next_cursor:
                break
            cursor = page.next_cursor
        if self._cache and all_entries:
            self._cache.put(self._base_url, all_entries)
        return all_entries

    async def get_server(self, name: str) -> Optional[ServerEntry]:
        """Fetch a single server by name."""
        path = _server_path(self._rtype)
        try:
            client = await self._ensure_client()
            resp = await client.get(f"{path}/{name}")
            resp.raise_for_status()
            return _entry_from_raw(self._rtype, resp.json(), resp.json())
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

        Falls back to client-side filtering of cached results.
        """
        path = _server_path(self._rtype)
        params = _search_params(self._rtype, query, limit)
        try:
            client = await self._ensure_client()
            resp = await client.get(path, params=params)
            resp.raise_for_status()
            page = _parse_page(self._rtype, resp.json())
            return page.servers
        except Exception:  # noqa: BLE001
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
