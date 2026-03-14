"""Registry configuration models."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import Field, field_validator

from argus_mcp.config.schema_backends import MetadataProvenance


class RegistryEntryConfig(MetadataProvenance):
    """A single registry source for browsing and installing MCP servers.

    Registries are external catalogs of MCP servers.  Configure one or more
    in ``config.yaml`` under the ``registries`` key.  The TUI Registry screen
    reads this list at startup.

    No registries are included by default — users must add the registries
    they want to use.  See ``docs/registry/README.md`` for a list of known
    public registries and their URLs.
    """

    name: str = Field(
        ...,
        min_length=1,
        description="Friendly label (e.g. 'community', 'internal').",
    )
    url: str = Field(
        ...,
        min_length=1,
        description="Base URL of the registry API (e.g. 'https://glama.ai/api/mcp').",
    )
    type: Literal["auto", "glama", "smithery", "generic"] = Field(
        default="auto",
        description=(
            "Registry backend type.  'auto' detects from URL (glama.ai → glama, "
            "smithery.ai → smithery, else generic).  Set explicitly if auto-detect "
            "picks wrong type."
        ),
    )
    priority: int = Field(
        default=100,
        ge=0,
        description="Lower number = checked first when multiple registries are configured.",
    )
    auth: Literal["none", "api-key", "bearer"] = Field(
        default="none",
        description="Authentication type for this registry.",
    )
    api_key_env: Optional[str] = Field(
        default=None,
        description="Environment variable containing the API key (for 'api-key' auth).",
    )
    token_env: Optional[str] = Field(
        default=None,
        description="Environment variable containing the bearer token (for 'bearer' auth).",
    )

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"Registry URL '{v}' must start with http:// or https://")
        return v
