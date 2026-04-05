"""Security configuration models (incoming auth + authorization + headers + payload limits)."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


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
    """Top-level security configuration aggregating headers and payload limits."""

    headers: SecurityHeadersConfig = Field(
        default_factory=SecurityHeadersConfig,
        description="Security response header configuration.",
    )
    payload_limits: PayloadLimitsConfig = Field(
        default_factory=PayloadLimitsConfig,
        description="Request payload size and depth limits.",
    )
