"""Pydantic response schemas for the Management API.

These schemas match the contract defined in ``docs/development_path/api-contract.json``.
Where possible they reuse models from ``argus_mcp.runtime.models``.
"""

from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

# ── /manage/v1/health ────────────────────────────────────────────────────


class HealthBackends(BaseModel):
    total: int = 0
    connected: int = 0
    healthy: int = 0


class HealthResponse(BaseModel):
    status: str = Field(description="healthy | degraded | unhealthy")
    uptime_seconds: Optional[float] = None
    version: str = ""
    backends: HealthBackends = Field(default_factory=HealthBackends)


# ── /manage/v1/status ───────────────────────────────────────────────────


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


# ── /manage/v1/backends ─────────────────────────────────────────────────


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


# ── /manage/v1/capabilities ─────────────────────────────────────────────


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


# ── /manage/v1/events ────────────────────────────────────────────────────


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


# ── Error responses ──────────────────────────────────────────────────────


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: Optional[Dict[str, Any]] = None


# ── /manage/v1/reload (POST) ────────────────────────────────────────────


class ReloadResponse(BaseModel):
    reloaded: bool = False
    backends_added: List[str] = Field(default_factory=list)
    backends_removed: List[str] = Field(default_factory=list)
    backends_changed: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


# ── /manage/v1/reconnect/{name} (POST) ──────────────────────────────────


class ReconnectResponse(BaseModel):
    name: str
    reconnected: bool = False
    error: Optional[str] = None


# ── /manage/v1/shutdown (POST) ──────────────────────────────────────────


class ShutdownRequest(BaseModel):
    """Request body for ``POST /manage/v1/shutdown``."""

    timeout_seconds: int = 30


class ShutdownResponse(BaseModel):
    shutting_down: bool = True


# ── /manage/v1/sessions ─────────────────────────────────────────────────


class SessionDetail(BaseModel):
    id: str
    transport_type: str = ""
    tool_count: int = 0
    capability_snapshot: Dict[str, Any] = Field(default_factory=dict)
    age_seconds: float = 0.0
    idle_seconds: float = 0.0
    ttl: float = 1800.0
    expired: bool = False


class SessionsResponse(BaseModel):
    active_sessions: int = 0
    sessions: List[SessionDetail] = Field(default_factory=list)
