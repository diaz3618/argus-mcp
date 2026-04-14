"""Auth provider registry — orchestrates incoming authentication.

Supports multiple modes:
* ``jwt`` — validate JWT tokens via JWKS (optionally via OIDC discovery)
* ``oidc`` — OIDC auto-discovery + JWT validation
* ``local`` — static bearer token (management auth)
* ``anonymous`` — no authentication (development mode)

The active provider is selected from config.  The auth middleware
(``bridge.middleware.auth``) delegates to whatever provider is configured.
"""

from __future__ import annotations

import hmac
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from argus_mcp.server.auth.jwt import JWTConfig, JWTValidator

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UserIdentity:
    """Represents an authenticated (or anonymous) user.

    Attached to ``RequestContext.metadata["user"]`` by the auth middleware.
    """

    subject: str = "anonymous"
    email: str = ""
    name: str = ""
    roles: list[str] = field(default_factory=list)
    provider: str = "anonymous"
    claims: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_anonymous(self) -> bool:
        return self.provider == "anonymous"


class AnonymousProvider:
    """Always returns an anonymous identity.  For development only."""

    async def authenticate(self, token: Optional[str]) -> UserIdentity:
        return UserIdentity(provider="anonymous")


class LocalTokenProvider:
    """Validates against a static bearer token (from config/env)."""

    def __init__(self, expected_token: str) -> None:
        self._expected = expected_token

    async def authenticate(self, token: Optional[str]) -> UserIdentity:
        if not token:
            raise AuthenticationError("Missing bearer token")
        if not hmac.compare_digest(token, self._expected):
            raise AuthenticationError("Invalid bearer token")
        return UserIdentity(
            subject="local-user",
            provider="local",
        )


class JWTAuthProvider:
    """Validates JWTs via JWKS keys (optionally discovered via OIDC)."""

    def __init__(self, validator: JWTValidator) -> None:
        self._validator = validator

    async def authenticate(self, token: Optional[str]) -> UserIdentity:
        if not token:
            raise AuthenticationError("Missing bearer token")
        from argus_mcp.server.auth.jwt import JWTValidationError

        try:
            claims = await self._validator.validate(token)
        except JWTValidationError as exc:
            raise AuthenticationError(str(exc)) from exc

        return UserIdentity(
            subject=claims.sub,
            email=claims.email,
            name=claims.name,
            roles=list(claims.roles),
            provider="jwt",
            claims=claims.raw,
        )


class AuthProviderRegistry:
    """Usage::

    registry = AuthProviderRegistry.from_config(config_dict)
    user = await registry.authenticate(token_string)
    """

    def __init__(self, provider: Any) -> None:
        self._provider = provider

    async def authenticate(self, token: Optional[str]) -> UserIdentity:
        """Authenticate using the active provider."""
        return await self._provider.authenticate(token)

    @classmethod
    def from_config(cls, config: Optional[Dict[str, Any]] = None) -> AuthProviderRegistry:
        """Create a registry from a config dict.

        Config shape::

            {
                "type": "jwt" | "oidc" | "local" | "anonymous",
                "jwks_uri": "...",       # for jwt
                "issuer": "...",         # for jwt/oidc
                "audience": "...",       # for jwt/oidc
                "token": "..."           # for local
            }
        """
        if not config:
            raise ValueError(
                "Auth provider config is required — pass explicit type: 'anonymous' to disable auth"
            )

        auth_type = config.get("type", "anonymous")

        if auth_type == "anonymous":
            logger.warning("Incoming auth set to ANONYMOUS — no authentication enforced")
            return cls(AnonymousProvider())

        if auth_type == "local":
            token = config.get("token", "")
            if not token:
                raise ValueError("Local auth requires 'token' in config")
            return cls(LocalTokenProvider(token))

        if auth_type in ("jwt", "oidc"):
            jwks_uri = config.get("jwks_uri", "")
            issuer = config.get("issuer", "")

            # For OIDC: auto-discover jwks_uri from issuer if not provided
            if auth_type == "oidc" and not jwks_uri:
                if not issuer:
                    raise ValueError("OIDC auth requires 'issuer' in config for auto-discovery")
                logger.info("OIDC: will auto-discover JWKS URI from issuer %r", issuer)
                # Point to the well-known endpoint; JWTValidator fetches JWKS
                # at runtime from the discovered jwks_uri.
                jwks_uri = f"{issuer.rstrip('/')}/.well-known/openid-configuration"

            jwt_config = JWTConfig(
                jwks_uri=jwks_uri,
                issuer=issuer,
                audience=config.get("audience", ""),
                algorithms=config.get("algorithms", ["RS256", "ES256"]),
            )
            validator = JWTValidator(jwt_config)
            return cls(JWTAuthProvider(validator))

        raise ValueError(f"Unknown incoming auth type: {auth_type!r}")


class AuthenticationError(Exception):
    """Raised when authentication fails (maps to HTTP 401)."""
