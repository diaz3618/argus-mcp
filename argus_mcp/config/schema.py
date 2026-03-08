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

# ── Re-exports from sub-modules ─────────────────────────────────────────
from argus_mcp.config.schema_backends import (  # noqa: F401
    AuthConfig,
    BackendConfig,
    CapabilityFilterConfig,
    ContainerConfig,
    FiltersConfig,
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

__all__ = [
    # schema_backends
    "AuthConfig",
    "BackendConfig",
    "CapabilityFilterConfig",
    "ContainerConfig",
    "FiltersConfig",
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
    "TelemetrySettings",
    "SecretsConfig",
    "ArgusConfig",
]

# ── Models that remain in this file (small, tightly coupled to top-level) ──


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


# ── Top-level config ────────────────────────────────────────────────────


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
    feature_flags: Dict[str, bool] = Field(
        default_factory=dict,
        description="Feature flag overrides (flag_name → enabled).",
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
