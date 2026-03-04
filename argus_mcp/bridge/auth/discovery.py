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
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)


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
    2. OIDC discovery on the authorization server URL.

    Returns ``None`` if discovery fails entirely (server does not
    require OAuth, or endpoints are unreachable).
    """
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
    """Fetch OIDC discovery document from the authorization server."""
    parsed = urlparse(auth_server_url)
    discovery_url = urljoin(
        f"{parsed.scheme}://{parsed.netloc}",
        "/.well-known/openid-configuration",
    )

    try:
        resp = await client.get(discovery_url)
        if resp.status_code != 200:
            # Try OAuth Authorization Server Metadata (RFC 8414)
            discovery_url = urljoin(
                f"{parsed.scheme}://{parsed.netloc}",
                "/.well-known/oauth-authorization-server",
            )
            resp = await client.get(discovery_url)
            if resp.status_code != 200:
                logger.debug(
                    "OIDC/OAuth discovery returned %d for %s.",
                    resp.status_code,
                    auth_server_url,
                )
                return None

        data = resp.json()
        meta = OAuthMetadata(
            issuer=data.get("issuer", ""),
            authorization_endpoint=data.get("authorization_endpoint", ""),
            token_endpoint=data.get("token_endpoint", ""),
            registration_endpoint=data.get("registration_endpoint", ""),
            scopes_supported=data.get("scopes_supported", []),
            response_types_supported=data.get("response_types_supported", []),
            code_challenge_methods_supported=data.get(
                "code_challenge_methods_supported", []
            ),
            raw=data,
        )
        logger.info(
            "OIDC discovery succeeded: issuer=%s, pkce=%s, registration=%s",
            meta.issuer,
            meta.supports_pkce,
            meta.supports_dynamic_registration,
        )
        return meta

    except Exception as exc:
        logger.debug(
            "OIDC discovery failed for %s: %s",
            auth_server_url,
            exc,
        )
        return None
