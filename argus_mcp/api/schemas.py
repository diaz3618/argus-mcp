"""Pydantic response schemas for the Management API.

These models define the API contract between the Argus MCP server and any
client (TUI, REPL, SDK).  Both sides import from this module so the
contract is always in sync.

Kept free of server-internal dependencies — only ``pydantic`` and stdlib.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

# Default session TTL (30 minutes).  Duplicated here to avoid importing
# from argus_mcp.constants which pulls in server-side deps.
SESSION_DEFAULT_TTL: float = 1800.0


class HealthBackends(BaseModel):
    total: int = 0
    connected: int = 0
    healthy: int = 0


class HealthResponse(BaseModel):
    status: str = Field(description="healthy | degraded | unhealthy")
    uptime_seconds: Optional[float] = None
    version: str = ""
    backends: HealthBackends = Field(default_factory=HealthBackends)


class ReadyResponse(BaseModel):
    ready: bool = False
    reason: str = ""


class StatusService(BaseModel):
    name: str
    version: str
    state: str
    uptime_seconds: Optional[float] = None
    started_at: Optional[str] = None  # ISO-8601


class StatusConfig(BaseModel):
    file_path: Optional[str] = None
    loaded_at: Optional[str] = None  # ISO-8601
    backend_count: int = 0


class StatusTransport(BaseModel):
    sse_url: str = ""
    streamable_http_url: Optional[str] = None
    host: str = ""
    port: int = 0


class StatusResponse(BaseModel):
    service: StatusService
    config: StatusConfig = Field(default_factory=StatusConfig)
    transport: StatusTransport = Field(default_factory=StatusTransport)
    feature_flags: Dict[str, bool] = Field(default_factory=dict)


class BackendCapabilities(BaseModel):
    tools: int = 0
    resources: int = 0
    prompts: int = 0


class BackendHealth(BaseModel):
    status: str = "unknown"  # healthy | unhealthy | unknown
    last_check: Optional[str] = None
    latency_ms: Optional[float] = None


class BackendDetail(BaseModel):
    name: str
    type: str
    group: str = "default"
    phase: str = "pending"
    state: str = "disconnected"  # connected | disconnected | connecting | error | unhealthy
    connected_at: Optional[str] = None
    error: Optional[str] = None
    capabilities: BackendCapabilities = Field(default_factory=BackendCapabilities)
    health: BackendHealth = Field(default_factory=BackendHealth)
    conditions: List[Dict[str, Any]] = Field(default_factory=list)
    labels: Dict[str, str] = Field(default_factory=dict)


class BackendsResponse(BaseModel):
    backends: List[BackendDetail] = Field(default_factory=list)


class ToolDetail(BaseModel):
    name: str
    original_name: str = ""
    description: str = ""
    backend: str = ""
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    filtered: bool = False
    renamed: bool = False


class ResourceDetail(BaseModel):
    uri: str = ""
    name: str = ""
    backend: str = ""
    mime_type: Optional[str] = None


class PromptDetail(BaseModel):
    name: str
    description: str = ""
    backend: str = ""
    arguments: List[Any] = Field(default_factory=list)


class CapabilitiesResponse(BaseModel):
    tools: List[ToolDetail] = Field(default_factory=list)
    resources: List[ResourceDetail] = Field(default_factory=list)
    prompts: List[PromptDetail] = Field(default_factory=list)
    route_map: Dict[str, Tuple[str, str]] = Field(default_factory=dict)
    optimizer_active: bool = False
    mcp_visible_tool_count: int = 0


class EventItem(BaseModel):
    id: str
    timestamp: str  # ISO-8601
    stage: str
    message: str
    severity: str = "info"  # debug | info | warning | error
    backend: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class EventsResponse(BaseModel):
    events: List[EventItem] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: Optional[Dict[str, Any]] = None


class ReloadResponse(BaseModel):
    reloaded: bool = False
    backends_added: List[str] = Field(default_factory=list)
    backends_removed: List[str] = Field(default_factory=list)
    backends_changed: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class ReconnectResponse(BaseModel):
    name: str
    reconnected: bool = False
    error: Optional[str] = None


class ReAuthResponse(BaseModel):
    name: str
    reauth_initiated: bool = False
    error: Optional[str] = None


class ShutdownRequest(BaseModel):
    """Request body for ``POST /manage/v1/shutdown``."""

    timeout_seconds: int = 30


class ShutdownResponse(BaseModel):
    shutting_down: bool = True


class SessionDetail(BaseModel):
    id: str
    transport_type: str = ""
    tool_count: int = 0
    capability_snapshot: Dict[str, Any] = Field(default_factory=dict)
    age_seconds: float = 0.0
    idle_seconds: float = 0.0
    ttl: float = SESSION_DEFAULT_TTL
    expired: bool = False


class SessionsResponse(BaseModel):
    active_sessions: int = 0
    sessions: List[SessionDetail] = Field(default_factory=list)


class BatchResponse(BaseModel):
    """Combined response for ``GET /manage/v1/batch``.

    Returns status, backends, capabilities, and recent events in a
    single round-trip to eliminate per-poll HTTP overhead.
    """

    status: StatusResponse
    backends: BackendsResponse = Field(default_factory=BackendsResponse)
    capabilities: CapabilitiesResponse = Field(default_factory=CapabilitiesResponse)
    events: EventsResponse = Field(default_factory=EventsResponse)


class RegistryServerEntry(BaseModel):
    name: str
    description: str = ""
    transport: str = "stdio"
    url: str = ""
    command: str = ""
    args: List[str] = Field(default_factory=list)
    version: str = ""
    categories: List[str] = Field(default_factory=list)


class RegistrySearchResponse(BaseModel):
    servers: List[RegistryServerEntry] = Field(default_factory=list)
    registry: str = ""
    total: int = 0


class SkillDetail(BaseModel):
    name: str
    version: str = ""
    description: str = ""
    status: str = "disabled"  # enabled | disabled
    tools: int = 0
    workflows: int = 0
    author: str = ""


class SkillsListResponse(BaseModel):
    skills: List[SkillDetail] = Field(default_factory=list)


class SkillActionResponse(BaseModel):
    name: str
    action: str  # enabled | disabled
    ok: bool = True
