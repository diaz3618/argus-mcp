"""JWT token validation with JWKS key retrieval.

Supports RS256, RS384, RS512, ES256, ES384, ES512 algorithms.
Keys are fetched from a JWKS URI and cached with a configurable TTL.
On validation failure with a cached key, the keys are re-fetched once
(handles key rotation).

Requires the ``PyJWT`` and ``cryptography`` packages::

    pip install PyJWT cryptography
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Supported signing algorithms — RSA and EC families.
SUPPORTED_ALGORITHMS: Set[str] = {
    "RS256",
    "RS384",
    "RS512",
    "ES256",
    "ES384",
    "ES512",
}

_DEFAULT_KEY_TTL = 3600.0  # 1 hour


@dataclass
class JWTConfig:
    """Configuration for JWT validation.

    Attributes
    ----------
    jwks_uri:
        URL to fetch JSON Web Key Set (populated via OIDC discovery or config).
    issuer:
        Expected ``iss`` claim value (optional, validated when set).
    audience:
        Expected ``aud`` claim value (optional, validated when set).
    algorithms:
        Allowed signing algorithms.  Defaults to RS256+ES256.
    key_ttl:
        Seconds to cache JWKS keys before re-fetching.
    """

    jwks_uri: str = ""
    issuer: str = ""
    audience: str = ""
    algorithms: List[str] = field(default_factory=lambda: ["RS256", "ES256"])
    key_ttl: float = _DEFAULT_KEY_TTL


@dataclass(frozen=True)
class TokenClaims:
    """Parsed claims from a validated JWT."""

    sub: str = ""
    iss: str = ""
    aud: str = ""
    email: str = ""
    name: str = ""
    roles: List[str] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


class JWTValidator:
    """Validate JWTs against a JWKS key set.

    Usage::

        validator = JWTValidator(JWTConfig(jwks_uri="https://..."))
        claims = await validator.validate(token_string)
    """

    def __init__(self, config: JWTConfig) -> None:
        self._config = config
        self._keys: Optional[Any] = None  # PyJWKClient instance
        self._keys_fetched_at: float = 0.0

    async def validate(self, token: str) -> TokenClaims:
        """Validate *token* and return parsed claims.

        Raises :class:`JWTValidationError` on any failure.
        """
        try:
            import jwt  # PyJWT
            from jwt import PyJWKClient
        except ImportError as exc:
            raise JWTValidationError(
                "PyJWT and cryptography packages are required for JWT validation. "
                "Install with: pip install PyJWT cryptography"
            ) from exc

        # Ensure we have keys
        if self._keys is None or self._keys_expired():
            self._keys = PyJWKClient(self._config.jwks_uri)
            self._keys_fetched_at = time.monotonic()

        try:
            claims = self._decode(token, jwt)
        except jwt.exceptions.InvalidSignatureError:
            # Key rotation: re-fetch keys and retry once
            logger.debug("JWT signature invalid — re-fetching JWKS keys")
            self._keys = PyJWKClient(self._config.jwks_uri)
            self._keys_fetched_at = time.monotonic()
            try:
                claims = self._decode(token, jwt)
            except Exception as exc:  # noqa: BLE001
                raise JWTValidationError(f"JWT validation failed after key refresh: {exc}") from exc
        except jwt.exceptions.ExpiredSignatureError as exc:
            raise JWTValidationError("Token has expired") from exc
        except jwt.exceptions.InvalidTokenError as exc:
            raise JWTValidationError(f"Invalid token: {exc}") from exc

        return TokenClaims(
            sub=claims.get("sub", ""),
            iss=claims.get("iss", ""),
            aud=_norm_aud(claims.get("aud", "")),
            email=claims.get("email", ""),
            name=claims.get("name", ""),
            roles=claims.get("roles") or claims.get("realm_access", {}).get("roles", []),
            raw=claims,
        )

    def _decode(self, token: str, jwt_mod: Any) -> Dict[str, Any]:
        """Decode and verify *token* using cached JWKS keys."""
        signing_key = self._keys.get_signing_key_from_jwt(token)

        options: Dict[str, Any] = {}
        kwargs: Dict[str, Any] = {
            "algorithms": self._config.algorithms,
            "options": options,
        }
        if self._config.issuer:
            kwargs["issuer"] = self._config.issuer
        if self._config.audience:
            kwargs["audience"] = self._config.audience
        else:
            options["verify_aud"] = False

        return jwt_mod.decode(
            token,
            signing_key.key,
            **kwargs,
        )

    def _keys_expired(self) -> bool:
        return (time.monotonic() - self._keys_fetched_at) > self._config.key_ttl


class JWTValidationError(Exception):
    """Raised when JWT validation fails."""


def _norm_aud(aud: Any) -> str:
    """Normalise the ``aud`` claim to a string."""
    if isinstance(aud, list):
        return aud[0] if aud else ""
    return str(aud) if aud else ""
