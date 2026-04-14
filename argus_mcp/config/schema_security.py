"""Security configuration models (incoming auth + authorization + headers + payload limits)."""

from __future__ import annotations

import warnings
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

HMAC_ALGORITHMS: frozenset[str] = frozenset({"HS256", "HS384", "HS512"})


class IncomingAuthConfig(BaseModel):
    """Incoming authentication config for the MCP data plane.

    Controls how connecting MCP clients are authenticated.
    """

    type: Literal["anonymous", "local", "jwt", "oidc"] = Field(
        default="anonymous",
        description="Auth type: anonymous (no auth), local (static token), jwt, or oidc.",
    )
    auth_mode: Literal["strict", "permissive"] = Field(
        default="strict",
        description=(
            "Auth enforcement mode. "
            "'strict': reject all unauthenticated requests (default). "
            "'permissive': allow unauthenticated access to public resources, "
            "but OAuth-protected resources still require auth. "
            "Invalid bearer tokens are ALWAYS rejected in both modes."
        ),
    )
    token: Optional[str] = Field(
        default=None,
        description="Static bearer token (for 'local' type). Supports ${ENV_VAR}.",
    )
    jwks_uri: Optional[str] = Field(
        default=None,
        description="JWKS URI for JWT key retrieval (for 'jwt' type).",
    )
    issuer: Optional[str] = Field(
        default=None,
        description="Expected JWT issuer (iss claim). For 'oidc' type, this is the discoverable issuer URL.",
    )
    audience: Optional[str] = Field(
        default=None,
        description="Expected JWT audience (aud claim).",
    )
    algorithms: List[str] = Field(
        default_factory=lambda: ["RS256", "ES256"],
        description="Allowed JWT signing algorithms.",
    )

    @field_validator("algorithms")
    @classmethod
    def validate_algorithms(cls, v: List[str]) -> List[str]:
        from argus_mcp.server.auth.jwt import SUPPORTED_ALGORITHMS

        all_known = SUPPORTED_ALGORITHMS | HMAC_ALGORITHMS
        for alg in v:
            if alg.lower() == "none":
                raise ValueError("Algorithm 'none' is forbidden")
            if alg not in all_known:
                raise ValueError(f"Algorithm '{alg}' not in supported set: {sorted(all_known)}")
            if alg in HMAC_ALGORITHMS:
                warnings.warn(
                    f"HMAC algorithm '{alg}' is not recommended for production JWT validation",
                    UserWarning,
                    stacklevel=2,
                )
        return v


class AuthorizationConfig(BaseModel):
    """Role-based authorization policy config."""

    enabled: bool = Field(default=False, description="Enable RBAC policy enforcement.")
    default_effect: Literal["allow", "deny"] = Field(
        default="deny",
        description="Default effect when no policy matches: 'allow' or 'deny'.",
    )
    policies: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="List of authorization policy rules.",
    )


class SecurityHeadersConfig(BaseModel):
    """Configuration for security response headers."""

    enabled: bool = Field(default=True, description="Enable security headers middleware.")
    hsts_max_age: int = Field(
        default=63072000,
        ge=0,
        le=63072000,
        description="Strict-Transport-Security max-age in seconds (default 2 years). Only sent over TLS.",
    )

    @field_validator("hsts_max_age")
    @classmethod
    def validate_hsts_max_age(cls, v: int) -> int:
        if 1 <= v <= 299:
            raise ValueError(
                f"hsts_max_age {v} is below minimum meaningful value (300). "
                "Use 0 to disable HSTS or ≥300 to enable."
            )
        return v


class PayloadLimitsConfig(BaseModel):
    """Configuration for request payload size and depth limits."""

    enabled: bool = Field(default=True, description="Enable payload limits middleware.")
    max_body_bytes: int = Field(
        default=1_048_576,
        ge=1024,
        le=104_857_600,
        description="Maximum request body size in bytes (default 1 MB).",
    )
    max_json_depth: int = Field(
        default=20,
        ge=1,
        le=100,
        description="Maximum JSON nesting depth allowed (default 20).",
    )


class SecurityConfig(BaseModel):
    """Top-level security configuration aggregating headers, payload limits, and hardening flags."""

    headers: SecurityHeadersConfig = Field(
        default_factory=SecurityHeadersConfig,
        description="Security response header configuration.",
    )
    payload_limits: PayloadLimitsConfig = Field(
        default_factory=PayloadLimitsConfig,
        description="Request payload size and depth limits.",
    )
    allow_weak_tokens: bool = Field(
        default=False,
        description=(
            "When True, accept management tokens shorter than 16 characters. "
            "Not recommended for production (SEC-06)."
        ),
    )
    require_origin: Literal["strict", "permissive"] = Field(
        default="permissive",
        description=(
            "Origin validation mode for MCP transport requests. "
            "'strict': reject requests without an Origin header (SEC-13). "
            "'permissive': allow missing Origin headers (for CLI/SDK clients)."
        ),
    )
    redact_status: bool = Field(
        default=False,
        description=(
            "When True, strip sensitive internal details (config paths, "
            "transport URLs, error messages) from /status and /backends "
            "management API responses (SEC-17)."
        ),
    )
