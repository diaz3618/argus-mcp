"""OAuth metadata discovery for remote MCP servers.

Implements two complementary discovery mechanisms:

1. **RFC 9728** — ``GET /.well-known/oauth-protected-resource`` on the
   MCP server itself.  Returns a ``resource`` document with pointers to
   the authorization server.

2. **OIDC Discovery** — ``GET /.well-known/openid-configuration`` on the
   authorization server found in step 1 (or provided explicitly).

The flow also handles **WWW-Authenticate** header inspection on a 401
response to extract ``realm`` / authorization server hints.

Typical call sequence::

    meta = await discover_oauth_metadata("https://mcp.example.com/mcp")
    if meta:
        # meta.authorization_endpoint, meta.token_endpoint, etc.
        ...

All network I/O uses httpx (lazy-imported to keep it optional).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)


# ── Metadata cache ───────────

# In-memory cache for AS metadata keyed by MCP server URL.
# Format: {url: {"metadata": OAuthMetadata, "cached_at": float}}
# Default TTL: 3600s.
_METADATA_CACHE_TTL: float = 3600.0
_metadata_cache: Dict[str, Dict[str, Any]] = {}


# ── Data classes ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OAuthMetadata:
    """Resolved OAuth endpoint metadata."""

    issuer: str = ""
    authorization_endpoint: str = ""
    token_endpoint: str = ""
    registration_endpoint: str = ""
    scopes_supported: List[str] = field(default_factory=list)
    response_types_supported: List[str] = field(default_factory=list)
    code_challenge_methods_supported: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def supports_pkce(self) -> bool:
        """``True`` if the server advertises S256 PKCE support."""
        return "S256" in self.code_challenge_methods_supported

    @property
    def supports_dynamic_registration(self) -> bool:
        """``True`` if a registration endpoint is present."""
        return bool(self.registration_endpoint)


# ── Public API ───────────────────────────────────────────────────────────


async def discover_oauth_metadata(
    mcp_server_url: str,
    *,
    timeout: float = 10.0,
) -> Optional[OAuthMetadata]:
    """Discover OAuth metadata for an MCP server.

    Tries in order:

    1. RFC 9728 protected-resource metadata on the MCP server.
    2. RFC 8414 / OIDC discovery on the authorization server URL.

    Results are cached for ``_METADATA_CACHE_TTL`` seconds to avoid
    redundant network calls on retries.

    Returns ``None`` if discovery fails entirely (server does not
    require OAuth, or endpoints are unreachable).
    """
    # Check cache first
    cached = _metadata_cache.get(mcp_server_url)
    if cached:
        age = time.monotonic() - cached["cached_at"]
        if age < _METADATA_CACHE_TTL:
            logger.debug(
                "Using cached OAuth metadata for %s (age=%.0fs).",
                mcp_server_url,
                age,
            )
            return cached["metadata"]
        # Expired — remove stale entry
        _metadata_cache.pop(mcp_server_url, None)

    import httpx  # noqa: PLC0415

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        # Step 1 — RFC 9728 resource metadata
        auth_server_url = await _discover_resource_metadata(client, mcp_server_url)

        if not auth_server_url:
            # Fallback: try a probe request and inspect WWW-Authenticate
            auth_server_url = await _probe_www_authenticate(client, mcp_server_url)

        if not auth_server_url:
            logger.debug(
                "No authorization server discovered for %s.",
                mcp_server_url,
            )
            return None

        # Step 2 — OIDC discovery on the authorization server
        meta = await _discover_oidc(client, auth_server_url)

        # Cache the result (including None for negative caching)
        if meta is not None:
            _metadata_cache[mcp_server_url] = {
                "metadata": meta,
                "cached_at": time.monotonic(),
            }

        return meta


async def discover_from_401(
    response_headers: Dict[str, str],
    *,
    timeout: float = 10.0,
) -> Optional[OAuthMetadata]:
    """Discover OAuth metadata from a 401 response's headers.

    Useful when an initial connection attempt fails and the caller
    already has the HTTP headers.
    """
    auth_server = _parse_www_authenticate(response_headers.get("www-authenticate", ""))
    if not auth_server:
        return None

    import httpx  # noqa: PLC0415

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        return await _discover_oidc(client, auth_server)


# ── Internal helpers ─────────────────────────────────────────────────────


async def _discover_resource_metadata(
    client: Any,
    mcp_url: str,
) -> Optional[str]:
    """Attempt RFC 9728 ``/.well-known/oauth-protected-resource``.

    Returns the ``authorization_server`` URL if found, else ``None``.
    """
    parsed = urlparse(mcp_url)
    well_known_url = urljoin(
        f"{parsed.scheme}://{parsed.netloc}",
        "/.well-known/oauth-protected-resource",
    )
    try:
        resp = await client.get(well_known_url)
        if resp.status_code == 200:
            data = resp.json()
            auth_server = data.get("authorization_servers", [None])
            if isinstance(auth_server, list) and auth_server:
                url = auth_server[0]
                logger.info(
                    "RFC 9728 discovery → authorization server: %s",
                    url,
                )
                return url
            # Fallback: single-value field
            url = data.get("authorization_server")
            if url:
                logger.info(
                    "RFC 9728 discovery → authorization server: %s",
                    url,
                )
                return url
    except Exception as exc:
        logger.debug(
            "RFC 9728 discovery failed for %s: %s",
            mcp_url,
            exc,
        )
    return None


async def _probe_www_authenticate(
    client: Any,
    mcp_url: str,
) -> Optional[str]:
    """Send a ``GET`` to the MCP URL and inspect a 401 response."""
    try:
        resp = await client.get(mcp_url)
        if resp.status_code == 401:
            www_auth = resp.headers.get("www-authenticate", "")
            return _parse_www_authenticate(www_auth)
    except Exception as exc:
        logger.debug(
            "401 probe failed for %s: %s",
            mcp_url,
            exc,
        )
    return None


def _parse_www_authenticate(header_value: str) -> Optional[str]:
    """Extract the authorization server URL from a WWW-Authenticate header.

    Supports ``Bearer realm="https://..."`` and
    ``Bearer authorization_uri="https://..."``.
    """
    if not header_value:
        return None

    import re  # noqa: PLC0415

    # Try authorization_uri first (more explicit)
    match = re.search(r'authorization_uri="([^"]+)"', header_value)
    if match:
        return match.group(1)

    # Try realm (common fallback)
    match = re.search(r'realm="([^"]+)"', header_value)
    if match:
        realm = match.group(1)
        # Only use realm if it looks like a URL
        if realm.startswith(("http://", "https://")):
            return realm

    return None


async def _discover_oidc(
    client: Any,
    auth_server_url: str,
) -> Optional[OAuthMetadata]:
    """Fetch OAuth/OIDC discovery documents from the authorization server.

    Tries **RFC 8414** first (``/.well-known/oauth-authorization-server``)
    because it is the more complete source for OAuth-specific fields
    (``registration_endpoint``, ``code_challenge_methods_supported``,
    ``scopes_supported``).  When RFC 8414 succeeds but is missing key
    fields, the OIDC document is fetched as well and used to fill gaps.
    """
    parsed = urlparse(auth_server_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    rfc8414_url = urljoin(base, "/.well-known/oauth-authorization-server")
    oidc_url = urljoin(base, "/.well-known/openid-configuration")

    rfc8414_data: Optional[Dict[str, Any]] = None
    oidc_data: Optional[Dict[str, Any]] = None

    # ── Pass 1: RFC 8414 (preferred) ────────────────────────────────
    try:
        resp = await client.get(rfc8414_url)
        if resp.status_code == 200:
            rfc8414_data = resp.json()
            logger.debug(
                "RFC 8414 metadata fetched for %s (issuer=%s).",
                auth_server_url,
                rfc8414_data.get("issuer", "?"),
            )
    except Exception as exc:
        logger.debug(
            "RFC 8414 discovery failed for %s: %s",
            auth_server_url,
            exc,
        )

    # ── Pass 2: OIDC (fallback / supplement) ────────────────────────
    try:
        resp = await client.get(oidc_url)
        if resp.status_code == 200:
            oidc_data = resp.json()
            logger.debug(
                "OIDC metadata fetched for %s (issuer=%s).",
                auth_server_url,
                oidc_data.get("issuer", "?"),
            )
    except Exception as exc:
        logger.debug(
            "OIDC discovery failed for %s: %s",
            auth_server_url,
            exc,
        )

    if not rfc8414_data and not oidc_data:
        logger.debug(
            "Neither RFC 8414 nor OIDC discovery succeeded for %s.",
            auth_server_url,
        )
        return None

    # Merge: RFC 8414 takes precedence, OIDC fills gaps.
    # OAuth-specific metadata while still leveraging OIDC for fields
    # like userinfo_endpoint that only OIDC publishes.
    merged: Dict[str, Any] = {}
    if oidc_data:
        merged.update(oidc_data)
    if rfc8414_data:
        # Only overwrite with non-empty values from RFC 8414
        for key, value in rfc8414_data.items():
            if value or key not in merged:
                merged[key] = value

    meta = OAuthMetadata(
        issuer=merged.get("issuer", ""),
        authorization_endpoint=merged.get("authorization_endpoint", ""),
        token_endpoint=merged.get("token_endpoint", ""),
        registration_endpoint=merged.get("registration_endpoint", ""),
        scopes_supported=merged.get("scopes_supported", []),
        response_types_supported=merged.get("response_types_supported", []),
        code_challenge_methods_supported=merged.get("code_challenge_methods_supported", []),
        raw=merged,
    )
    logger.info(
        "OAuth discovery succeeded: issuer=%s, pkce=%s, registration=%s, source=%s",
        meta.issuer,
        meta.supports_pkce,
        meta.supports_dynamic_registration,
        "rfc8414+oidc" if rfc8414_data and oidc_data else "rfc8414" if rfc8414_data else "oidc",
    )
    return meta
