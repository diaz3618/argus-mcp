"""Rate limiting configuration models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RateLimitRouteConfig(BaseModel):
    """Per-route rate limit configuration."""

    requests: int = Field(
        default=100,
        ge=1,
        le=100000,
        description="Maximum requests allowed within the window.",
    )
    window_seconds: int = Field(
        default=60,
        ge=1,
        le=86400,
        description="Sliding window duration in seconds.",
    )


class RateLimitsConfig(BaseModel):
    """Top-level rate limiting configuration.

    Controls per-IP sliding-window rate limits with an authentication
    lockout mechanism for repeated 401/403 responses.
    """

    enabled: bool = Field(default=True, description="Enable rate limiting middleware.")
    default: RateLimitRouteConfig = Field(
        default_factory=RateLimitRouteConfig,
        description="Default rate limit applied to all routes.",
    )
    auth_lockout_threshold: int = Field(
        default=5,
        ge=1,
        le=1000,
        description="Number of auth failures (401/403) before temporary lockout.",
    )
    auth_lockout_window_seconds: int = Field(
        default=300,
        ge=10,
        le=86400,
        description="Sliding window in seconds for counting auth failures.",
    )
    auth_lockout_duration_seconds: int = Field(
        default=900,
        ge=10,
        le=86400,
        description="Duration in seconds to lock out an IP after exceeding auth failure threshold.",
    )
