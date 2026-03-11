"""Server and management configuration models."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class ManagementSettings(BaseModel):
    """Management API configuration."""

    enabled: bool = True
    token: Optional[str] = Field(
        default=None,
        description="Bearer token for /manage/ endpoints. Also ARGUS_MGMT_TOKEN env var.",
    )
    reconnect_timeout: Optional[float] = Field(
        default=None,
        ge=1,
        le=600,
        description="Overall timeout in seconds for backend reconnect operations (default: 60).",
    )


class ServerSettings(BaseModel):
    """Argus server settings (host, port, transport, management)."""

    host: str = "127.0.0.1"
    port: int = Field(default=9000, ge=1, le=65535)
    transport: Literal["sse", "streamable-http"] = "streamable-http"
    management: ManagementSettings = Field(default_factory=ManagementSettings)
    auth_background_refresh_enabled: bool = Field(
        default=True,
        description=(
            "Enable a background task that proactively refreshes OAuth tokens "
            "for all backends before they expire."
        ),
    )
    auth_background_refresh_interval_seconds: float = Field(
        default=60.0,
        ge=5,
        le=3600,
        description="Interval in seconds between background token refresh sweeps.",
    )

    @field_validator("transport", mode="before")
    @classmethod
    def _normalise_transport(cls, v: str) -> str:
        """Accept 'http' as a shorthand for 'streamable-http'."""
        if isinstance(v, str) and v.strip().lower() == "http":
            return "streamable-http"
        return v
