"""Backend server configuration models.

Defines Pydantic models for stdio, SSE, and streamable-http backend
MCP servers, along with shared sub-models (timeouts, filters, auth).
"""

from __future__ import annotations

import ipaddress
import os
import re
from pathlib import Path
from typing import Annotated, Dict, List, Literal, Optional, Union
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator, model_validator


class MetadataProvenance(BaseModel):
    """Optional provenance tracking fields for config entities.

    These fields are populated automatically during import/export and
    management API mutations.  They are never required for basic
    configuration and default to ``None``.
    """

    created_by: Optional[str] = Field(
        default=None, description="Principal that created this entry."
    )
    updated_by: Optional[str] = Field(
        default=None, description="Principal that last modified this entry."
    )
    created_via: Optional[str] = Field(
        default=None,
        description="Channel through which entry was created (cli, tui, import, api).",
    )
    updated_via: Optional[str] = Field(
        default=None,
        description="Channel through which entry was last modified.",
    )
    import_batch_id: Optional[str] = Field(
        default=None, description="Import batch that created/updated this entry."
    )
    metadata_version: Optional[int] = Field(
        default=None,
        ge=1,
        description="Monotonic version counter incremented on each update.",
    )


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
    auth_retry_on_401: bool = Field(
        default=True,
        description="Automatically retry requests with a fresh token on HTTP 401.",
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
    auth_retry_on_401: bool = Field(
        default=True,
        description="Automatically retry requests with a fresh token on HTTP 401.",
    )


AuthConfig = Annotated[
    Union[StaticAuthConfig, OAuth2AuthConfig, PKCEAuthConfig],
    Field(discriminator="type"),
]

DANGEROUS_DOCKER_FLAGS: frozenset[str] = frozenset(
    {
        "--privileged",
        "--cap-add",
        "--security-opt",
        "--device",
        "--pid",
        "--ipc",
        "--userns",
        "--uts",
        "--network=host",
        "--net=host",
        "--add-host",
        "--volume",
        "-v",
        "--mount",
    }
)


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
    build_system_deps: List[str] = Field(
        default_factory=list,
        description=(
            "System packages needed only in the builder stage "
            "(e.g. ['git'] for VCS npm specifiers). These are "
            "installed before the package install command and are "
            "NOT carried over to the runtime stage."
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

    # source_url + build_steps + entrypoint + build_env

    source_url: Optional[str] = Field(
        default=None,
        description=(
            "Git repository URL to clone and build from source. "
            "Must use 'https' or 'git+ssh' scheme. "
            "Example: 'https://github.com/owner/repo.git'."
        ),
    )
    build_steps: List[str] = Field(
        default_factory=list,
        description=(
            "Shell commands to execute during the build stage "
            "after cloning source_url. Required when source_url is set. "
            "Example: ['pip install -e .', 'python setup.py build']."
        ),
    )
    entrypoint: Optional[List[str]] = Field(
        default=None,
        description=(
            "Custom container entrypoint as a list of strings. "
            "Required when source_url is set. Also usable standalone "
            "to override auto-detected entrypoints. "
            "Example: ['python', '-m', 'my_server']."
        ),
    )
    build_env: Dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Build-time environment variables. Keys must be uppercase "
            "with underscores. Values may reference secrets using "
            "'${SECRET_NAME}' syntax — resolved at build time only, "
            "never in the runtime layer."
        ),
    )
    source_ref: Optional[str] = Field(
        default=None,
        description=("Git ref to checkout after cloning source_url (branch, tag, or commit SHA)."),
    )

    # dockerfile escape hatch

    dockerfile: Optional[str] = Field(
        default=None,
        description=(
            "Path to a custom Dockerfile, relative to the config file. "
            "When set, bypasses all auto-generated templates. "
            "Absolute paths and '..' path components are rejected."
        ),
    )

    @field_validator("extra_args")
    @classmethod
    def _validate_extra_args(cls, v: List[str]) -> List[str]:
        for arg in v:
            flag = arg.split("=")[0].strip()
            if arg in DANGEROUS_DOCKER_FLAGS or flag in DANGEROUS_DOCKER_FLAGS:
                matched = arg if arg in DANGEROUS_DOCKER_FLAGS else flag
                raise ValueError(
                    f"Dangerous Docker flag '{matched}' not allowed in extra_args. "
                    "Use explicit ContainerConfig fields instead."
                )
        return v

    @field_validator("volumes")
    @classmethod
    def _validate_volumes(cls, v: List[str]) -> List[str]:
        allowed_raw = os.environ.get("ARGUS_VOLUME_ALLOWED_PREFIXES", "/tmp:/data:/workspace")
        allowed = [Path(p).resolve() for p in allowed_raw.split(":") if p]
        for vol in v:
            parts = vol.split(":")
            host_part = parts[0] if parts else ""
            if not host_part:
                continue
            host_path = Path(host_part).resolve()
            if not any(
                host_path == a or str(host_path).startswith(str(a) + os.sep) for a in allowed
            ):
                raise ValueError(
                    f"Volume host path '{host_path}' is not within allowed prefixes: {allowed_raw}"
                )
        return v

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

    @field_validator("source_url")
    @classmethod
    def _validate_source_url(cls, v: Optional[str]) -> Optional[str]:
        """Validate source_url: HTTPS or git+ssh only, no private IPs."""
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None

        parsed = urlparse(v)
        scheme = parsed.scheme.lower()
        allowed_schemes = {"https", "git+ssh"}
        if scheme not in allowed_schemes:
            raise ValueError(
                f"source_url scheme must be one of {sorted(allowed_schemes)}, "
                f"got '{scheme}' in '{v}'"
            )

        hostname = parsed.hostname or ""
        if hostname:
            # Reject private/loopback IP addresses (SSRF prevention)
            try:
                addr = ipaddress.ip_address(hostname)
                if addr.is_private or addr.is_loopback or addr.is_reserved:
                    raise ValueError(
                        f"source_url must not point to private/loopback addresses: '{hostname}'"
                    )
            except ValueError as exc:
                if "private" in str(exc) or "loopback" in str(exc):
                    raise
                # Not an IP literal — hostname is fine

            lower_host = hostname.lower()
            if lower_host in ("localhost", "localhost.localdomain"):
                raise ValueError(f"source_url must not point to localhost: '{hostname}'")
        return v

    @field_validator("build_steps")
    @classmethod
    def _validate_build_steps(cls, v: List[str]) -> List[str]:
        """Validate build_steps: reject shell-unsafe characters."""
        _shell_unsafe = re.compile(r"[`$()]")
        for step in v:
            if _shell_unsafe.search(step):
                raise ValueError(f"build_steps entry contains unsafe characters: {step!r}")
        return v

    @field_validator("entrypoint")
    @classmethod
    def _validate_entrypoint(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        """Validate entrypoint: reject shell-unsafe characters."""
        if v is None:
            return v
        _shell_unsafe = re.compile(r"[;&|`$(){}\[\]<>!#~\\\n\r]")
        for elem in v:
            if _shell_unsafe.search(elem):
                raise ValueError(f"entrypoint element contains unsafe characters: {elem!r}")
        return v

    @field_validator("build_env")
    @classmethod
    def _validate_build_env(cls, v: Dict[str, str]) -> Dict[str, str]:
        """Validate build_env keys and values."""
        _key_pattern = re.compile(r"^[A-Z][A-Z0-9_]*$")
        for key in v:
            if not _key_pattern.match(key):
                raise ValueError(
                    f"build_env key must be uppercase letters/digits/underscore "
                    f"starting with a letter: {key!r}"
                )
        return v

    @field_validator("dockerfile")
    @classmethod
    def _validate_dockerfile(cls, v: Optional[str]) -> Optional[str]:
        """Validate dockerfile path: no absolute paths, no '..' traversal."""
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        import pathlib

        p = pathlib.PurePosixPath(v)
        if p.is_absolute():
            raise ValueError(f"dockerfile must be a relative path, got absolute: '{v}'")
        if ".." in p.parts:
            raise ValueError(f"dockerfile must not contain '..' path components: '{v}'")
        return v

    @model_validator(mode="after")
    def _validate_source_url_deps(self) -> "ContainerConfig":
        """Ensure build_steps and entrypoint are set when source_url is."""
        if self.source_url:
            if not self.build_steps:
                raise ValueError("build_steps is required when source_url is set")
            if not self.entrypoint:
                raise ValueError("entrypoint is required when source_url is set")
        return self


class StdioBackendConfig(MetadataProvenance):
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


class SseBackendConfig(MetadataProvenance):
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


class StreamableHttpBackendConfig(MetadataProvenance):
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
