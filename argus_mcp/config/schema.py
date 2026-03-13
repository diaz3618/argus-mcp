"""Pydantic configuration models for Argus MCP.

Defines the validated config structure using the versioned v1 format.

The models are split across sub-modules for maintainability:

* ``schema_backends`` — backend configs (stdio, SSE, streamable-http)
* ``schema_server``   — server & management settings
* ``schema_client``   — TUI / client settings
* ``schema_registry`` — registry entry config
* ``schema_security`` — incoming auth & authorization

This file imports and re-exports everything so that the public API::

    from argus_mcp.config.schema import ArgusConfig, BackendConfig, ...

continues to work unchanged.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, Field, field_validator

from argus_mcp.config.schema_backends import (  # noqa: F401
    AuthConfig,
    BackendConfig,
    CapabilityFilterConfig,
    ContainerConfig,
    FiltersConfig,
    MetadataProvenance,
    OAuth2AuthConfig,
    PKCEAuthConfig,
    SseBackendConfig,
    StaticAuthConfig,
    StdioBackendConfig,
    StreamableHttpBackendConfig,
    TimeoutConfig,
    ToolOverrideEntry,
)
from argus_mcp.config.schema_client import ClientConfig  # noqa: F401
from argus_mcp.config.schema_registry import RegistryEntryConfig  # noqa: F401
from argus_mcp.config.schema_security import (  # noqa: F401
    AuthorizationConfig,
    IncomingAuthConfig,
)
from argus_mcp.config.schema_server import (  # noqa: F401
    ManagementSettings,
    ServerSettings,
)
from argus_mcp.plugins.models import PluginsConfig  # noqa: F401

__all__ = [
    # schema_backends
    "AuthConfig",
    "BackendConfig",
    "CapabilityFilterConfig",
    "ContainerConfig",
    "FiltersConfig",
    "MetadataProvenance",
    "OAuth2AuthConfig",
    "PKCEAuthConfig",
    "SseBackendConfig",
    "StaticAuthConfig",
    "StdioBackendConfig",
    "StreamableHttpBackendConfig",
    "TimeoutConfig",
    "ToolOverrideEntry",
    # schema_client
    "ClientConfig",
    # schema_registry
    "RegistryEntryConfig",
    # schema_security
    "AuthorizationConfig",
    "IncomingAuthConfig",
    # schema_server
    "ManagementSettings",
    "ServerSettings",
    # This file
    "ConflictResolutionConfig",
    "AuditConfig",
    "OptimizerConfig",
    "SessionPoolConfig",
    "HttpPoolConfig",
    "RetryConfig",
    "SseResilienceConfig",
    "TelemetrySettings",
    "SecretsConfig",
    "ArgusConfig",
    "PluginsConfig",
]


class ConflictResolutionConfig(BaseModel):
    """Configuration for capability name conflict resolution."""

    strategy: Literal["first-wins", "prefix", "priority", "error"] = Field(
        default="first-wins",
        description="Strategy for handling duplicate capability names across backends.",
    )
    separator: str = Field(
        default="_",
        description="Separator for prefix-based naming (e.g. 'server_tool').",
    )
    order: List[str] = Field(
        default_factory=list,
        description="Server priority list for 'priority' strategy (higher = first).",
    )


class AuditConfig(BaseModel):
    """Audit logging settings."""

    enabled: bool = Field(default=True, description="Enable audit event logging.")
    file: str = Field(
        default="logs/audit.jsonl",
        description="Path to the JSON-line audit log file.",
    )
    max_size_mb: int = Field(default=100, ge=1, description="Max file size in MB before rotation.")
    backup_count: int = Field(
        default=5, ge=0, description="Number of rotated backup files to keep."
    )


class OptimizerConfig(BaseModel):
    """Tool optimizer (find_tool / call_tool) settings."""

    enabled: bool = Field(
        default=False,
        description="Enable the optimizer — replaces full tool catalog with find_tool + call_tool.",
    )
    keep_tools: List[str] = Field(
        default_factory=list,
        description="Tool names to always expose alongside the meta-tools.",
    )


class TelemetrySettings(BaseModel):
    """OpenTelemetry integration settings.

    Controls whether the telemetry middleware is inserted into the
    middleware chain and whether OTel exporters are initialized.
    """

    enabled: bool = Field(
        default=False,
        description="Enable OpenTelemetry tracing and metrics collection.",
    )
    otlp_endpoint: str = Field(
        default="http://localhost:4317",
        description="OTLP collector endpoint (gRPC or HTTP).",
    )
    service_name: str = Field(
        default="argus-mcp",
        description="Service name reported to the OTel collector.",
    )


class RetryConfig(BaseModel):
    """HTTP retry manager settings.

    Controls automatic retry behaviour for retryable HTTP errors
    (429, 502, 503, 504, 408) with exponential backoff and jitter.
    """

    enabled: bool = Field(default=True, description="Enable automatic HTTP retry.")
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Maximum retry attempts per request.",
    )
    base_delay: float = Field(
        default=1.0,
        ge=0.1,
        le=30.0,
        description="Initial delay in seconds before the first retry.",
    )
    backoff_factor: float = Field(
        default=2.0,
        ge=1.0,
        le=10.0,
        description="Multiplier applied to the delay after each retry.",
    )
    max_delay: float = Field(
        default=60.0,
        ge=1.0,
        le=300.0,
        description="Upper bound on computed delay in seconds.",
    )
    jitter: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Fraction of delay used for random jitter.",
    )


class SseResilienceConfig(BaseModel):
    """SSE stream resilience settings.

    Configures cleanup deadlines, send timeouts, keepalive intervals,
    and spin-loop detection for SSE transport connections.
    """

    enabled: bool = Field(default=True, description="Enable SSE stream resilience guards.")
    send_timeout: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Max seconds to push a single SSE frame before timeout.",
    )
    cleanup_deadline: float = Field(
        default=15.0,
        ge=1.0,
        le=120.0,
        description="Max seconds for post-disconnect session cleanup.",
    )
    keepalive_interval: float = Field(
        default=30.0,
        ge=0.0,
        le=600.0,
        description="Seconds between keepalive pings (0 disables).",
    )
    spin_loop_window: float = Field(
        default=1.0,
        ge=0.1,
        le=30.0,
        description="Sliding window in seconds for spin-loop detection.",
    )
    spin_loop_threshold: int = Field(
        default=200,
        ge=10,
        le=10000,
        description="Max write calls within the spin window before warning.",
    )


class HttpPoolConfig(BaseModel):
    """HTTP connection pool settings.

    Controls the shared ``httpx.AsyncClient`` used for backend HTTP
    traffic, registry calls, and management API requests.
    """

    enabled: bool = Field(default=True, description="Enable shared HTTP connection pooling.")
    max_connections: int = Field(
        default=200,
        ge=1,
        le=2000,
        description="Maximum total simultaneous connections.",
    )
    max_keepalive: int = Field(
        default=100,
        ge=0,
        le=2000,
        description="Maximum idle keep-alive connections.",
    )
    timeout: float = Field(
        default=30.0,
        ge=1.0,
        le=300.0,
        description="Default request timeout in seconds.",
    )


class SessionPoolConfig(BaseModel):
    """MCP session pool settings.

    Controls pooling of ``ClientSession`` objects so that reconnections
    to the same backend endpoint can be avoided when the transport is
    still healthy.
    """

    enabled: bool = Field(default=True, description="Enable MCP session pooling.")
    per_key_max: int = Field(
        default=4,
        ge=1,
        le=64,
        description="Maximum pooled sessions per (url, identity, transport) key.",
    )
    ttl: float = Field(
        default=300.0,
        ge=10.0,
        le=3600.0,
        description="Time-to-live in seconds for idle pooled sessions.",
    )
    circuit_breaker_threshold: int = Field(
        default=3,
        ge=1,
        le=50,
        description="Consecutive failures before the pool circuit breaker opens for a key.",
    )


class SecretsConfig(BaseModel):
    """Encrypted secret management settings.

    When configured, ``secret:<name>`` references in config values are
    resolved via the chosen provider before Pydantic validation.
    """

    enabled: bool = Field(
        default=False,
        description="Enable automatic secret resolution in config values.",
    )
    provider: str = Field(
        default="env",
        description="Secret provider type: 'env', 'file', or 'keyring'.",
    )
    path: str = Field(
        default="",
        description="Path for the file-based secret provider (ignored for other providers).",
    )
    strict: bool = Field(
        default=False,
        description="Raise an error if a referenced secret cannot be resolved.",
    )


class ArgusConfig(BaseModel):
    """Top-level validated configuration for Argus MCP.

    Supports version ``"1"`` format::

        {
            "version": "1",
            "server": { ... },
            "backends": {
                "my-server": { "type": "stdio", ... }
            }
        }
    """

    version: str = "1"
    server: ServerSettings = Field(default_factory=ServerSettings)
    client: ClientConfig = Field(
        default_factory=ClientConfig,
        description="TUI / client-side settings.",
    )
    backends: Dict[str, BackendConfig] = Field(default_factory=dict)
    conflict_resolution: ConflictResolutionConfig = Field(default_factory=ConflictResolutionConfig)
    audit: AuditConfig = Field(default_factory=AuditConfig)
    optimizer: OptimizerConfig = Field(default_factory=OptimizerConfig)
    telemetry: TelemetrySettings = Field(
        default_factory=TelemetrySettings,
        description="OpenTelemetry tracing and metrics configuration.",
    )
    secrets: SecretsConfig = Field(
        default_factory=SecretsConfig,
        description="Encrypted secret management configuration.",
    )
    registries: List[RegistryEntryConfig] = Field(
        default_factory=list,
        description=(
            "Registry sources for browsing/installing MCP servers. "
            "Configure at least one to use the Registry feature."
        ),
    )
    incoming_auth: IncomingAuthConfig = Field(
        default_factory=IncomingAuthConfig,
        description="Incoming authentication for MCP data plane connections.",
    )
    authorization: AuthorizationConfig = Field(
        default_factory=AuthorizationConfig,
        description="Role-based authorization policy evaluation.",
    )
    session_pool: SessionPoolConfig = Field(
        default_factory=SessionPoolConfig,
        description="MCP session pool settings.",
    )
    http_pool: HttpPoolConfig = Field(
        default_factory=HttpPoolConfig,
        description="HTTP connection pool settings.",
    )
    retry: RetryConfig = Field(
        default_factory=RetryConfig,
        description="HTTP retry manager settings.",
    )
    sse_resilience: SseResilienceConfig = Field(
        default_factory=SseResilienceConfig,
        description="SSE stream resilience settings.",
    )
    feature_flags: Dict[str, bool] = Field(
        default_factory=dict,
        description=(
            "Feature flag overrides (flag_name → enabled).  "
            "Known flags: optimizer (high-risk, default off), "
            "hot_reload, outgoing_auth, session_management, yaml_config, "
            "container_isolation, build_on_startup (all low-risk, default on).  "
            "High-risk flags are disabled by default and require explicit opt-in."
        ),
    )
    plugins: PluginsConfig = Field(
        default_factory=PluginsConfig,
        description="Plugin framework configuration.",
    )

    @field_validator("backends")
    @classmethod
    def _validate_backend_names(cls, v: Dict[str, Any]) -> Dict[str, Any]:
        for name in v:
            stripped = name.strip()
            if not stripped:
                raise ValueError("Backend name must be a non-empty string")
            if stripped != name:
                raise ValueError(f"Backend name '{name}' has leading/trailing whitespace")
        return v
