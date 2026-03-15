"""Pydantic models for Argus MCP runtime state.

These models serve dual purpose:
1. Internal state representation for ArgusService
2. API response schemas for the management API
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field


class ServiceState(str, Enum):
    """Lifecycle states for the Argus service.

    Valid transitions:
        PENDING  → STARTING
        STARTING → RUNNING | ERROR
        RUNNING  → STOPPING
        STOPPING → STOPPED | ERROR
        ERROR    → STARTING  (restart attempt)
    """

    PENDING = "pending"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


# Valid state transitions: current_state → set of allowed next states
_VALID_TRANSITIONS: Dict[ServiceState, frozenset[ServiceState]] = {
    ServiceState.PENDING: frozenset({ServiceState.STARTING}),
    ServiceState.STARTING: frozenset({ServiceState.RUNNING, ServiceState.ERROR}),
    ServiceState.RUNNING: frozenset({ServiceState.STOPPING}),
    ServiceState.STOPPING: frozenset({ServiceState.STOPPED, ServiceState.ERROR}),
    ServiceState.STOPPED: frozenset(),
    ServiceState.ERROR: frozenset({ServiceState.STARTING, ServiceState.STOPPING}),
}


def is_valid_transition(current: ServiceState, target: ServiceState) -> bool:
    """Check whether a state transition is allowed."""
    return target in _VALID_TRANSITIONS.get(current, frozenset())


class BackendInfo(BaseModel):
    """Information about a single backend MCP server connection."""

    name: str
    type: str = Field(description="Backend type: 'stdio' or 'sse'")
    connected: bool = False
    error: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "examples": [{"name": "my-server", "type": "stdio", "connected": True}]
        }
    }


class BackendPhase(str, Enum):
    """7-state lifecycle phases for individual backend servers.

    Transitions::

        PENDING → INITIALIZING → READY → DEGRADED → FAILED
                       ↑           ↗         ↘
                  RETRYING    SHUTTING_DOWN   READY
                       ↑
                     FAILED
    """

    PENDING = "pending"
    INITIALIZING = "initializing"
    RETRYING = "retrying"
    READY = "ready"
    DEGRADED = "degraded"
    FAILED = "failed"
    SHUTTING_DOWN = "shutting_down"


# Valid backend phase transitions
_BACKEND_TRANSITIONS: Dict[BackendPhase, frozenset[BackendPhase]] = {
    BackendPhase.PENDING: frozenset({BackendPhase.INITIALIZING}),
    BackendPhase.INITIALIZING: frozenset({BackendPhase.READY, BackendPhase.FAILED}),
    BackendPhase.RETRYING: frozenset({BackendPhase.INITIALIZING, BackendPhase.FAILED}),
    BackendPhase.READY: frozenset(
        {BackendPhase.DEGRADED, BackendPhase.FAILED, BackendPhase.SHUTTING_DOWN}
    ),
    BackendPhase.DEGRADED: frozenset(
        {BackendPhase.READY, BackendPhase.FAILED, BackendPhase.SHUTTING_DOWN}
    ),
    BackendPhase.FAILED: frozenset(
        {BackendPhase.INITIALIZING, BackendPhase.RETRYING, BackendPhase.SHUTTING_DOWN}
    ),
    BackendPhase.SHUTTING_DOWN: frozenset(),
}


def is_valid_backend_transition(current: BackendPhase, target: BackendPhase) -> bool:
    """Check whether a backend phase transition is allowed."""
    return target in _BACKEND_TRANSITIONS.get(current, frozenset())


class BackendCondition(BaseModel):
    """A timestamped condition entry for a backend server."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    type: str = Field(description="Condition type, e.g. 'Connected', 'HealthCheck', 'Error'")
    status: str = Field(description="OK | Warning | Error")
    message: str = ""


class BackendStatusRecord(BaseModel):
    """Rich lifecycle status for a single backend server.

    Extends :class:`BackendInfo` with phase, conditions, and metrics.
    """

    name: str
    phase: BackendPhase = BackendPhase.PENDING
    tool_count: int = 0
    resource_count: int = 0
    prompt_count: int = 0
    last_latency_ms: Optional[float] = None
    error: Optional[str] = None
    conditions: List[BackendCondition] = Field(default_factory=list)

    def transition(self, new_phase: BackendPhase, message: str = "") -> None:
        """Transition to *new_phase* and append a condition entry.

        Raises :class:`ValueError` if the transition is invalid.
        """
        if not is_valid_backend_transition(self.phase, new_phase):
            raise ValueError(f"Invalid backend transition: {self.phase.value} → {new_phase.value}")
        self.phase = new_phase
        ok_phases = {BackendPhase.READY}
        warn_phases = {BackendPhase.DEGRADED, BackendPhase.INITIALIZING, BackendPhase.SHUTTING_DOWN}
        if new_phase in ok_phases:
            status = "OK"
        elif new_phase in warn_phases:
            status = "Warning"
        else:
            status = "Error"
        self.conditions.append(
            BackendCondition(
                type=new_phase.value,
                status=status,
                message=message,
            )
        )
        if new_phase == BackendPhase.FAILED and message:
            self.error = message
        elif new_phase == BackendPhase.READY:
            self.error = None

    def add_condition(self, cond_type: str, status: str, message: str = "") -> None:
        """Append a freeform condition without changing phase."""
        self.conditions.append(BackendCondition(type=cond_type, status=status, message=message))

    @property
    def is_operational(self) -> bool:
        """True when the backend is READY or DEGRADED."""
        return self.phase in {BackendPhase.READY, BackendPhase.DEGRADED}

    @property
    def recent_conditions(self) -> List[BackendCondition]:
        """Return the 10 most recent conditions (newest first)."""
        return list(reversed(self.conditions[-10:]))


class CapabilityInfo(BaseModel):
    """Aggregated capability information across all backends."""

    tools_count: int = 0
    resources_count: int = 0
    prompts_count: int = 0
    tool_names: List[str] = Field(default_factory=list)
    resource_names: List[str] = Field(default_factory=list)
    prompt_names: List[str] = Field(default_factory=list)
    route_map: Dict[str, Tuple[str, str]] = Field(
        default_factory=dict,
        description="Capability name → (server_name, original_cap_name)",
    )


class ServiceStatus(BaseModel):
    """Overall service status snapshot — designed for JSON API responses."""

    state: ServiceState = ServiceState.PENDING
    server_name: str = ""
    server_version: str = ""
    started_at: Optional[datetime] = None
    uptime_seconds: Optional[float] = None
    backends_total: int = 0
    backends_connected: int = 0
    backends: List[BackendInfo] = Field(default_factory=list)
    capabilities: CapabilityInfo = Field(default_factory=CapabilityInfo)
    error_message: Optional[str] = None
    config_path: Optional[str] = None

    def compute_uptime(self) -> None:
        """Update uptime_seconds based on started_at."""
        if self.started_at is not None:
            delta = datetime.now(timezone.utc) - self.started_at
            self.uptime_seconds = delta.total_seconds()
