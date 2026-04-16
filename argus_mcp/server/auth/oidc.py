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

import ipaddress
import logging
import socket
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

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

    def _validate_issuer_url(self) -> List[str]:
        """Validate the issuer URL against SSRF patterns and return resolved IPs.

        Blocks private, loopback, link-local, and reserved IP addresses
        to prevent server-side request forgery via OIDC discovery.

        Returns the list of validated public IP strings so that callers
        can **pin** the HTTP request to a resolved IP, preventing DNS
        rebinding (TOCTOU) attacks where a second resolution could yield
        a different address.  (CR-01)
        """
        parsed = urllib.parse.urlparse(self._issuer)
        hostname = parsed.hostname
        scheme = parsed.scheme

        if not hostname:
            raise OIDCDiscoveryError(f"OIDC issuer URL {self._issuer!r} has no hostname")

        if scheme not in ("http", "https"):
            raise OIDCDiscoveryError(
                f"OIDC issuer URL {self._issuer!r} must use http or https scheme"
            )

        try:
            addr_infos = socket.getaddrinfo(hostname, None)
        except socket.gaierror as exc:
            raise OIDCDiscoveryError(
                f"OIDC issuer URL {self._issuer!r} — DNS resolution failed: {exc}"
            ) from exc

        validated_ips: List[str] = []
        for _family, _type, _proto, _canonname, sockaddr in addr_infos:
            ip_str = str(sockaddr[0])
            try:
                addr = ipaddress.ip_address(ip_str)
            except ValueError:
                continue

            # HI-01: Normalise IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1)
            # before the private/loopback check.  In CPython 3.11+ the mapped
            # form may bypass ``is_loopback`` / ``is_private``.
            check_addr = addr
            if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
                check_addr = addr.ipv4_mapped

            if (
                check_addr.is_private
                or check_addr.is_loopback
                or check_addr.is_link_local
                or check_addr.is_reserved
            ):
                raise OIDCDiscoveryError(
                    f"OIDC issuer URL {self._issuer!r} resolves to "
                    f"private/loopback/reserved address {addr} — potential SSRF"
                )
            validated_ips.append(ip_str)

        if not validated_ips:
            raise OIDCDiscoveryError(
                f"OIDC issuer URL {self._issuer!r} — DNS returned no usable addresses"
            )
        return validated_ips

    @staticmethod
    def _build_pinned_request(url: str, pinned_ip: str) -> Tuple[str, Dict[str, str]]:
        """Return ``(request_url, extra_headers)`` with the hostname replaced by *pinned_ip*.

        For **http** URLs we swap the hostname so that ``httpx`` connects
        directly to the validated IP (no second DNS lookup) and inject a
        ``Host`` header with the original hostname.

        For **https** URLs we return the original URL unchanged because TLS
        certificate verification already binds the connection to the
        legitimate server — a DNS-rebinding attacker cannot present a
        valid certificate for the victim domain.  (CR-01)
        """
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme == "https":
            return url, {}

        # HTTP: replace hostname with pinned IP, preserve port/path/query.
        host_header = parsed.hostname or ""
        if parsed.port:
            host_header = f"{host_header}:{parsed.port}"
            netloc = f"{pinned_ip}:{parsed.port}"
        else:
            netloc = pinned_ip

        pinned = parsed._replace(netloc=netloc)
        return urllib.parse.urlunparse(pinned), {"Host": host_header}

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

        validated_ips = self._validate_issuer_url()

        # CR-01: Pin the HTTP request to the validated IP to prevent DNS
        # rebinding (TOCTOU) between validation and the actual request.
        request_url, extra_headers = self._build_pinned_request(url, validated_ips[0])

        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.get(request_url, follow_redirects=False, headers=extra_headers)
                resp.raise_for_status()
                data: Dict[str, Any] = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
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
