"""Backend server configuration models.

Defines Pydantic models for stdio, SSE, and streamable-http backend
MCP servers, along with shared sub-models (timeouts, filters, auth).
"""

from __future__ import annotations

from typing import Annotated, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator

# ── Shared per-backend configs ───────────────────────────────────────────


class TimeoutConfig(BaseModel):
    """Per-backend timeout configuration. Defaults are used when not specified."""

    init: Optional[float] = Field(
        default=None,
        ge=0,
        description="MCP session initialization timeout in seconds.",
    )
    cap_fetch: Optional[float] = Field(
        default=None,
        ge=0,
        description="Capability list fetch timeout in seconds.",
    )
    sse_startup: Optional[float] = Field(
        default=None,
        ge=0,
        description="Wait time for local SSE server startup in seconds.",
    )
    startup: Optional[float] = Field(
        default=None,
        ge=0,
        description=(
            "Overall per-backend connection timeout in seconds "
            "(covers subprocess spawn + MCP init). "
            "Useful for cold-start scenarios where uvx/npx downloads packages."
        ),
    )
    retries: Optional[int] = Field(
        default=None,
        ge=0,
        le=10,
        description="Number of automatic retries for failed backend connections.",
    )
    retry_delay: Optional[float] = Field(
        default=None,
        ge=0,
        le=120,
        description="Seconds to wait between retry attempts.",
    )


class CapabilityFilterConfig(BaseModel):
    """Per-capability-type allow/deny filter configuration."""

    allow: List[str] = Field(
        default_factory=list,
        description="Glob patterns for allowed capability names.",
    )
    deny: List[str] = Field(
        default_factory=list,
        description="Glob patterns for denied capability names.",
    )


class FiltersConfig(BaseModel):
    """Per-backend capability filters (tools, resources, prompts)."""

    tools: CapabilityFilterConfig = Field(default_factory=CapabilityFilterConfig)
    resources: CapabilityFilterConfig = Field(default_factory=CapabilityFilterConfig)
    prompts: CapabilityFilterConfig = Field(default_factory=CapabilityFilterConfig)


class ToolOverrideEntry(BaseModel):
    """Rename and/or override description for a single tool."""

    name: Optional[str] = Field(default=None, description="New name to expose to clients.")
    description: Optional[str] = Field(
        default=None, description="Override description for the tool."
    )


# ── Outgoing authentication ──────────────────────────────────────────────


class StaticAuthConfig(BaseModel):
    """Static header-based authentication."""

    type: Literal["static"]
    headers: Dict[str, str] = Field(
        ..., min_length=1, description="Headers to inject (values support ${ENV_VAR})."
    )


class OAuth2AuthConfig(BaseModel):
    """OAuth 2.0 Client Credentials authentication."""

    type: Literal["oauth2"]
    token_url: str = Field(..., min_length=1, description="Token endpoint URL.")
    client_id: str = Field(..., min_length=1)
    client_secret: str = Field(..., min_length=1, description="Supports ${ENV_VAR}.")
    scopes: List[str] = Field(default_factory=list)
    token_expiry_buffer_seconds: float = Field(
        default=300.0,
        ge=0,
        description=(
            "Seconds before token expiry to trigger proactive refresh. Default 300 (5 min)."
        ),
    )


class PKCEAuthConfig(BaseModel):
    """OAuth 2.0 Authorization Code + PKCE authentication.

    Triggers an interactive browser-based login flow on first use.
    Tokens are cached to disk so the flow only needs to run once
    (until the refresh token expires).
    """

    type: Literal["pkce"]
    authorization_endpoint: str = Field(..., min_length=1, description="OAuth authorization URL.")
    token_endpoint: str = Field(..., min_length=1, description="OAuth token exchange URL.")
    client_id: str = Field(..., min_length=1, description="OAuth client ID.")
    client_secret: str = Field(
        default="", description="Optional client secret. Supports ${ENV_VAR}."
    )
    scopes: List[str] = Field(default_factory=list)
    token_expiry_buffer_seconds: float = Field(
        default=300.0,
        ge=0,
        description=(
            "Seconds before token expiry to trigger proactive refresh. Default 300 (5 min)."
        ),
    )


AuthConfig = Annotated[
    Union[StaticAuthConfig, OAuth2AuthConfig, PKCEAuthConfig],
    Field(discriminator="type"),
]


# ── Container isolation ──────────────────────────────────────────────────


class ContainerConfig(BaseModel):
    """Per-backend container isolation configuration.

    Container isolation is **enabled by default** for all stdio backends
    with supported commands (``uvx``, ``npx``).  All local backends run
    inside containers unless explicitly opted out.

    To **disable** container isolation for a specific backend::

        backends:
          my-server:
            type: stdio
            command: uvx
            args: ["my-mcp-server"]
            container:
              enabled: false

    To **customise** container settings::

        backends:
          my-server:
            type: stdio
            command: uvx
            args: ["my-mcp-server"]
            container:
              network: none
              memory: 1g
              runtime: docker
    """

    enabled: bool = Field(
        default=True,
        description=(
            "Whether container isolation is active for this backend. "
            "Set to false to run as a bare subprocess instead."
        ),
    )
    runtime: Optional[Literal["docker", "podman", "kubernetes"]] = Field(
        default=None,
        description=(
            "Container runtime override for this backend. "
            "When unset, auto-detects (Docker preferred). "
            "Can also be set globally via ARGUS_RUNTIME env var."
        ),
    )
    network: Optional[str] = Field(
        default=None,
        description=(
            "Container network mode override. Default is 'bridge' "
            "(allows outbound). Set to 'none' for full network isolation, "
            "or specify a custom Docker network name."
        ),
    )
    memory: Optional[str] = Field(
        default=None,
        description="Memory limit override (e.g. '256m', '1g'). Default: 512m.",
    )
    cpus: Optional[str] = Field(
        default=None,
        description="CPU limit override (e.g. '0.5', '2'). Default: 1.",
    )
    volumes: List[str] = Field(
        default_factory=list,
        description=(
            "Volume mounts in Docker format: 'host:container[:ro]'. "
            "Use sparingly — each mount weakens isolation."
        ),
    )
    extra_args: List[str] = Field(
        default_factory=list,
        description="Additional raw arguments passed to 'docker run'.",
    )
    system_deps: List[str] = Field(
        default_factory=list,
        description=(
            "System packages to install in the container image "
            "(e.g. ['ripgrep', 'git']). For alpine-based images (npx), "
            "packages are installed via 'apk add'. For debian-based "
            "images (uvx), packages are installed via 'apt-get install'."
        ),
    )
    builder_image: Optional[str] = Field(
        default=None,
        description=(
            "Override the base Docker image for building the container. "
            "Defaults: uvx → 'python:3.13-slim', npx → 'node:22-alpine'. "
            "Must be a valid OCI image reference."
        ),
    )
    additional_packages: List[str] = Field(
        default_factory=list,
        description=(
            "Extra runtime packages to install in the final image stage "
            "(beyond system_deps). These are installed after system_deps."
        ),
    )
    transport: Optional[str] = Field(
        default=None,
        description=(
            "Explicit transport type override ('uvx', 'npx', 'go'). "
            "When set, bypasses auto-detection from the command name. "
            "Required for Go MCP servers whose binary name doesn't "
            "match a known command (e.g. 'mcp-k8s')."
        ),
    )
    go_package: Optional[str] = Field(
        default=None,
        description=(
            "Go module import path for the 'go' transport "
            "(e.g. 'github.com/strowk/mcp-k8s-go'). "
            "Required when transport is 'go'. The module is compiled "
            "inside a multi-stage build using 'go install'."
        ),
    )

    @field_validator("transport")
    @classmethod
    def _validate_transport(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip().lower()
            valid = {"uvx", "npx", "go"}
            if v not in valid:
                raise ValueError(f"Invalid transport '{v}'. Must be one of: {sorted(valid)}")
        return v

    @field_validator("network")
    @classmethod
    def _validate_network(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
        return v


# ── Backend server configs ───────────────────────────────────────────────


class StdioBackendConfig(BaseModel):
    """Configuration for a stdio-type backend MCP server."""

    type: Literal["stdio"]
    command: str = Field(..., min_length=1, description="Executable to run")
    args: List[str] = Field(default_factory=list)
    env: Optional[Dict[str, str]] = None
    container: ContainerConfig = Field(
        default_factory=ContainerConfig,
        description=(
            "Container isolation configuration. "
            "Container isolation is enabled by default for supported "
            "commands (uvx, npx). Set 'enabled: false' to disable, "
            "or customise network, memory, CPU limits, volumes, etc."
        ),
    )
    group: str = Field(default="default", description="Logical server group name.")
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    tool_overrides: Dict[str, ToolOverrideEntry] = Field(
        default_factory=dict,
        description="Per-tool rename and description overrides.",
    )
    timeouts: TimeoutConfig = Field(default_factory=TimeoutConfig)

    @field_validator("container", mode="before")
    @classmethod
    def _ensure_container_config(cls, v: object) -> object:
        """Coerce ``null`` / missing container section to defaults."""
        if v is None:
            return {}  # Pydantic will populate ContainerConfig defaults
        return v

    @field_validator("command")
    @classmethod
    def _strip_command(cls, v: str) -> str:
        return v.strip()


class SseBackendConfig(BaseModel):
    """Configuration for an SSE-type backend MCP server."""

    type: Literal["sse"]
    url: str = Field(..., min_length=1, description="SSE endpoint URL")
    command: Optional[str] = None
    args: List[str] = Field(default_factory=list)
    env: Optional[Dict[str, str]] = None
    headers: Optional[Dict[str, str]] = Field(
        default=None,
        description="Extra HTTP headers (e.g. Authorization). Supports ${ENV_VAR}.",
    )
    auth: Optional[AuthConfig] = Field(
        default=None,
        description="Outgoing authentication strategy for this backend.",
    )
    group: str = Field(default="default", description="Logical server group name.")
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    tool_overrides: Dict[str, ToolOverrideEntry] = Field(
        default_factory=dict,
        description="Per-tool rename and description overrides.",
    )
    timeouts: TimeoutConfig = Field(default_factory=TimeoutConfig)

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"URL '{v}' must start with http:// or https://")
        return v

    @field_validator("command")
    @classmethod
    def _strip_command(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip()
            if not v:
                raise ValueError("command must be a non-empty string if provided")
        return v


class StreamableHttpBackendConfig(BaseModel):
    """Configuration for a streamable-http-type backend MCP server."""

    type: Literal["streamable-http"]
    url: str = Field(..., min_length=1, description="Streamable HTTP endpoint URL")
    headers: Optional[Dict[str, str]] = Field(
        default=None,
        description="Extra HTTP headers (e.g. Authorization). Supports ${ENV_VAR}.",
    )
    auth: Optional[AuthConfig] = Field(
        default=None,
        description="Outgoing authentication strategy for this backend.",
    )
    group: str = Field(default="default", description="Logical server group name.")
    filters: FiltersConfig = Field(default_factory=FiltersConfig)
    tool_overrides: Dict[str, ToolOverrideEntry] = Field(
        default_factory=dict,
        description="Per-tool rename and description overrides.",
    )
    timeouts: TimeoutConfig = Field(default_factory=TimeoutConfig)

    @field_validator("url")
    @classmethod
    def _validate_url(cls, v: str) -> str:
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            raise ValueError(f"URL '{v}' must start with http:// or https://")
        return v


# Discriminated union: pick the right model based on "type" field
BackendConfig = Annotated[
    Union[StdioBackendConfig, SseBackendConfig, StreamableHttpBackendConfig],
    Field(discriminator="type"),
]
