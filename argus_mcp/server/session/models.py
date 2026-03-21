"""Session data models for per-client MCP sessions."""

from __future__ import annotations

from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Dict, Optional
from uuid import uuid4

from argus_mcp.constants import SESSION_DEFAULT_TTL


@dataclass
class MCPSession:
    """Represents a per-client MCP session with frozen routing.

    The routing table is snapshotted at session creation time and does
    not change for the lifetime of the session — even if backends are
    added, removed, or reconnected.  This gives clients a consistent
    view of available capabilities throughout a conversation.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    routing_table: Dict[str, str] = field(default_factory=dict)
    """Frozen tool_name → backend_name mapping captured at creation."""

    capability_snapshot: Dict[str, Any] = field(default_factory=dict)
    """Frozen counts: ``{"tools": N, "resources": N, "prompts": N}``."""

    created_at: float = field(default_factory=monotonic)
    """Monotonic timestamp of session creation."""

    last_active: float = field(default_factory=monotonic)
    """Monotonic timestamp of last client activity."""

    ttl: float = SESSION_DEFAULT_TTL
    """Session time-to-live in seconds (default: 30 minutes)."""

    transport_type: str = ""
    """``"sse"`` or ``"streamable_http"``."""

    @property
    def expired(self) -> bool:
        """``True`` if the session has been idle longer than its TTL."""
        return (monotonic() - self.last_active) > self.ttl

    @property
    def age_seconds(self) -> float:
        """Seconds since the session was created."""
        return monotonic() - self.created_at

    @property
    def idle_seconds(self) -> float:
        """Seconds since the session was last active."""
        return monotonic() - self.last_active

    def touch(self) -> None:
        """Update *last_active* to the current monotonic time."""
        self.last_active = monotonic()

    def resolve_backend(self, tool_name: str) -> Optional[str]:
        """Look up the backend for *tool_name* using the frozen routing table.

        Returns ``None`` if the tool is not in this session's snapshot.
        """
        return self.routing_table.get(tool_name)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the session for the management API."""
        return {
            "id": self.id,
            "transport_type": self.transport_type,
            "tool_count": len(self.routing_table),
            "capability_snapshot": self.capability_snapshot,
            "age_seconds": round(self.age_seconds, 1),
            "idle_seconds": round(self.idle_seconds, 1),
            "ttl": self.ttl,
            "expired": self.expired,
        }
