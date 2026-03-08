"""OIDC auto-discovery.

Fetches the ``/.well-known/openid-configuration`` document from an
issuer URL and extracts the ``jwks_uri`` (and other endpoints) needed
for JWT validation.

Usage::

    discovery = OIDCDiscovery("https://accounts.google.com")
    config = await discovery.fetch()
    # config.jwks_uri → "https://www.googleapis.com/oauth2/v3/certs"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OIDCConfig:
    """Parsed OIDC discovery document (subset of relevant fields)."""

    issuer: str = ""
    jwks_uri: str = ""
    authorization_endpoint: str = ""
    token_endpoint: str = ""
    userinfo_endpoint: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)


class OIDCDiscovery:
    """Fetch and parse OIDC discovery documents.

    Parameters
    ----------
    issuer_url:
        The OIDC issuer URL (e.g. ``https://accounts.google.com``).
    timeout:
        HTTP request timeout in seconds.
    """

    def __init__(self, issuer_url: str, *, timeout: float = 10.0) -> None:
        self._issuer = issuer_url.rstrip("/")
        self._timeout = timeout
        self._cached: Optional[OIDCConfig] = None

    async def fetch(self) -> OIDCConfig:
        """Fetch the OIDC discovery document.

        Returns a cached result on subsequent calls (call :meth:`refresh`
        to force re-fetch).

        Raises :class:`OIDCDiscoveryError` on failure.
        """
        if self._cached is not None:
            return self._cached

        try:
            import httpx
        except ImportError as exc:
            raise OIDCDiscoveryError(
                "httpx is required for OIDC discovery. Install with: pip install httpx"
            ) from exc

        url = f"{self._issuer}/.well-known/openid-configuration"
        logger.debug("Fetching OIDC discovery document: %s", url)

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data: Dict[str, Any] = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise OIDCDiscoveryError(
                f"Failed to fetch OIDC discovery document from {url}: {exc}"
            ) from exc

        if "jwks_uri" not in data:
            raise OIDCDiscoveryError(
                f"OIDC discovery document at {url} missing required 'jwks_uri' field"
            )

        config = OIDCConfig(
            issuer=data.get("issuer", self._issuer),
            jwks_uri=data["jwks_uri"],
            authorization_endpoint=data.get("authorization_endpoint", ""),
            token_endpoint=data.get("token_endpoint", ""),
            userinfo_endpoint=data.get("userinfo_endpoint", ""),
            raw=data,
        )
        self._cached = config
        logger.info(
            "OIDC discovery complete: issuer=%s, jwks_uri=%s", config.issuer, config.jwks_uri
        )
        return config

    async def refresh(self) -> OIDCConfig:
        """Force re-fetch of the discovery document."""
        self._cached = None
        return await self.fetch()


class OIDCDiscoveryError(Exception):
    """Raised when OIDC discovery fails."""
