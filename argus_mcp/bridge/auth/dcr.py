"""Dynamic Client Registration (RFC 7591) for outgoing OAuth flows.

Allows the gateway to auto-register as an OAuth client with
Authorization Servers that advertise a ``registration_endpoint`` in
their metadata (RFC 8414 / OIDC discovery).

Key behaviours:

* **In-memory cache** with configurable TTL — avoids redundant
  registrations for the same AS.
* **Grant type negotiation** — requests only the grant types supported
  by both the AS and the gateway (``authorization_code``,
  ``client_credentials``, ``refresh_token``).
* **Issuer allowlist** — optional deny-by-default policy that
  restricts which issuers the gateway will register with.
* **SSRF protection** — reuses ``_validate_discovery_url`` /
  ``_safe_get`` patterns from :mod:`~argus_mcp.bridge.auth.discovery`.

Typical usage::

    from argus_mcp.bridge.auth.dcr import DCRClient
    dcr = DCRClient(issuer_allowlist=["https://auth.example.com"])
    reg = await dcr.register(oauth_metadata)
    # reg.client_id, reg.client_secret, ...
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Sequence

from argus_mcp.bridge.auth.discovery import (
    OAuthMetadata,
    _validate_discovery_url,
)

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_TTL: float = 3600.0

# {registration_endpoint: {"registration": ClientRegistration, "cached_at": float}}
_registration_cache: Dict[str, Dict[str, Any]] = {}

_GATEWAY_GRANT_TYPES: FrozenSet[str] = frozenset(
    {
        "authorization_code",
        "client_credentials",
        "refresh_token",
    }
)


@dataclass(frozen=True)
class ClientRegistration:
    """Result of a successful RFC 7591 registration."""

    client_id: str
    client_secret: str = ""
    client_id_issued_at: int = 0
    client_secret_expires_at: int = 0
    grant_types: List[str] = field(default_factory=list)
    redirect_uris: List[str] = field(default_factory=list)
    token_endpoint_auth_method: str = "client_secret_post"
    registration_endpoint: str = ""
    raw: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        """``True`` if the client_secret has a set expiry in the past."""
        if self.client_secret_expires_at == 0:
            return False  # No expiry set
        return time.time() > self.client_secret_expires_at


class DCRClient:
    """Dynamic Client Registration client per RFC 7591.

    Parameters
    ----------
    issuer_allowlist:
        Optional list of allowed issuer URLs. When non-empty, only
        Authorization Servers whose ``issuer`` field matches an entry
        in this list will be contacted. Empty list disables the check.
    cache_ttl:
        TTL in seconds for cached registrations. Defaults to 3 600 s.
    client_name:
        ``client_name`` sent in the registration request.
    redirect_uris:
        Default ``redirect_uris`` included in registration requests.
        Required when requesting ``authorization_code`` grants.
    """

    def __init__(
        self,
        *,
        issuer_allowlist: Optional[Sequence[str]] = None,
        cache_ttl: float = _DEFAULT_CACHE_TTL,
        client_name: str = "argus-mcp-gateway",
        redirect_uris: Optional[List[str]] = None,
    ) -> None:
        self._allowlist: FrozenSet[str] = frozenset(issuer_allowlist or [])
        self._cache_ttl = max(0.0, cache_ttl)
        self._client_name = client_name
        self._redirect_uris = redirect_uris or []

    async def register(
        self,
        metadata: OAuthMetadata,
        *,
        timeout: float = 10.0,
    ) -> Optional[ClientRegistration]:
        """Register a client with the AS described by *metadata*.

        Returns a :class:`ClientRegistration` on success, ``None`` if
        registration is not supported or the AS rejected the request.

        Raises :class:`ValueError` if the issuer is not in the
        allowlist (when an allowlist is configured).
        """
        if not metadata.supports_dynamic_registration:
            logger.debug(
                "AS '%s' does not advertise a registration endpoint.",
                metadata.issuer,
            )
            return None

        reg_endpoint = metadata.registration_endpoint

        # Validate the registration endpoint against SSRF
        _validate_discovery_url(reg_endpoint)

        # Issuer allowlist check
        if self._allowlist and metadata.issuer not in self._allowlist:
            raise ValueError(f"Issuer '{metadata.issuer}' is not in the allowed issuers list.")

        # Check cache
        cached = _registration_cache.get(reg_endpoint)
        if cached:
            age = time.monotonic() - cached["cached_at"]
            reg: ClientRegistration = cached["registration"]
            if age < self._cache_ttl and not reg.is_expired:
                logger.debug(
                    "Using cached DCR for %s (age=%.0fs).",
                    reg_endpoint,
                    age,
                )
                return reg
            # Expired — remove stale entry
            _registration_cache.pop(reg_endpoint, None)

        # Negotiate grant types
        grant_types = self._negotiate_grant_types(metadata)
        if not grant_types:
            logger.warning(
                "No overlapping grant types with AS '%s'. AS supports: %s, gateway supports: %s",
                metadata.issuer,
                metadata.raw.get("grant_types_supported", []),
                sorted(_GATEWAY_GRANT_TYPES),
            )
            # Still attempt registration with our preferred types — some
            # AS implementations will accept the request and restrict
            # the grant types in the response.
            grant_types = sorted(_GATEWAY_GRANT_TYPES)

        # Build registration request body per RFC 7591 §2.
        body = self._build_registration_body(grant_types)

        return await self._do_register(reg_endpoint, body, timeout=timeout)

    def clear_cache(self) -> None:
        """Remove all cached registrations."""
        _registration_cache.clear()

    def _negotiate_grant_types(
        self,
        metadata: OAuthMetadata,
    ) -> List[str]:
        """Return the intersection of AS-supported and gateway grant types."""
        as_grants = set(metadata.raw.get("grant_types_supported", []))
        if not as_grants:
            # AS does not advertise supported grants — return all ours
            return sorted(_GATEWAY_GRANT_TYPES)
        return sorted(_GATEWAY_GRANT_TYPES & as_grants)

    def _build_registration_body(
        self,
        grant_types: List[str],
    ) -> Dict[str, Any]:
        """Build the JSON body for the registration POST."""
        body: Dict[str, Any] = {
            "client_name": self._client_name,
            "grant_types": grant_types,
            "token_endpoint_auth_method": "client_secret_post",
        }
        if self._redirect_uris:
            body["redirect_uris"] = self._redirect_uris
        if "authorization_code" in grant_types:
            body["response_types"] = ["code"]
            body["code_challenge_methods_supported"] = ["S256"]
        return body

    async def _do_register(
        self,
        reg_endpoint: str,
        body: Dict[str, Any],
        *,
        timeout: float = 10.0,
    ) -> Optional[ClientRegistration]:
        """Execute the registration POST and parse the response."""
        import httpx  # noqa: PLC0415

        try:
            _validate_discovery_url(reg_endpoint)
        except ValueError:
            logger.warning(
                "Registration endpoint failed SSRF validation: %s",
                reg_endpoint,
            )
            return None

        try:
            # Use a short-lived client (not the pool) for security-critical
            # auth flows — same pattern as discovery.py.
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=False,
                max_redirects=0,
            ) as client:
                resp = await client.post(
                    reg_endpoint,
                    json=body,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
        except (OSError, ConnectionError) as exc:
            logger.warning(
                "DCR request to %s failed: %s",
                reg_endpoint,
                exc,
            )
            return None

        if resp.status_code not in (200, 201):
            logger.warning(
                "DCR rejected by %s: HTTP %d — %s",
                reg_endpoint,
                resp.status_code,
                resp.text[:500],
            )
            return None

        try:
            data = resp.json()
        except (ValueError, TypeError):
            logger.warning(
                "DCR response from %s is not valid JSON.",
                reg_endpoint,
            )
            return None

        client_id = data.get("client_id", "")
        if not client_id:
            logger.warning(
                "DCR response from %s missing client_id.",
                reg_endpoint,
            )
            return None

        reg = ClientRegistration(
            client_id=client_id,
            client_secret=data.get("client_secret", ""),
            client_id_issued_at=data.get("client_id_issued_at", 0),
            client_secret_expires_at=data.get("client_secret_expires_at", 0),
            grant_types=data.get("grant_types", []),
            redirect_uris=data.get("redirect_uris", []),
            token_endpoint_auth_method=data.get("token_endpoint_auth_method", "client_secret_post"),
            registration_endpoint=reg_endpoint,
            raw=data,
        )

        # Cache the registration
        _registration_cache[reg_endpoint] = {
            "registration": reg,
            "cached_at": time.monotonic(),
        }

        logger.info(
            "DCR succeeded with %s: client_id=%s, grant_types=%s",
            reg_endpoint,
            reg.client_id,
            reg.grant_types,
        )
        return reg
