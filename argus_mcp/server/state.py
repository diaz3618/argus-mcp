"""Typed server state — replaces ad-hoc monkey-patching on the MCP server."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, List, Optional

if TYPE_CHECKING:
    from argus_mcp.audit import AuditLogger
    from argus_mcp.bridge.capability_registry import CapabilityRegistry
    from argus_mcp.bridge.client_manager import ClientManager
    from argus_mcp.bridge.middleware.chain import MiddlewareChain
    from argus_mcp.bridge.optimizer import ToolIndex
    from argus_mcp.bridge.version_checker import VersionChecker
    from argus_mcp.config.flags import FeatureFlags
    from argus_mcp.server.session import SessionManager
    from argus_mcp.skills.manager import SkillManager


@dataclass
class ServerState:
    """Aggregated state attached to the MCP server instance.

    Instead of setting 15+ individual attributes via ``setattr()``,
    all runtime state is bundled here and attached as a single
    ``_argus_state`` attribute.  Consumers use :func:`get_state`
    for typed access with a sensible default.
    """

    manager: Optional[ClientManager] = None
    registry: Optional[CapabilityRegistry] = None
    audit_logger: Optional[AuditLogger] = None
    middleware_chain: Optional[MiddlewareChain] = None
    session_manager: Optional[SessionManager] = None
    feature_flags: Optional[FeatureFlags] = None
    skill_manager: Optional[SkillManager] = None
    version_checker: Optional[VersionChecker] = None
    optimizer_index: Optional[ToolIndex] = None
    optimizer_enabled: bool = False
    optimizer_keep_list: List[str] = field(default_factory=list)
    telemetry_enabled: bool = False
    composite_tools: List[Any] = field(default_factory=list)


def get_state(mcp_server: Any) -> ServerState:
    """Return the :class:`ServerState` attached to *mcp_server*.

    Falls back to constructing a ``ServerState`` from individual
    attributes when ``_argus_state`` is missing (backward compat
    for tests that set attrs directly on mock objects).
    """
    state = getattr(mcp_server, "_argus_state", None)
    if isinstance(state, ServerState):
        return state
    # Backward compat: build from individual attrs
    return ServerState(
        manager=getattr(mcp_server, "manager", None),
        registry=getattr(mcp_server, "registry", None),
        audit_logger=getattr(mcp_server, "audit_logger", None),
        middleware_chain=getattr(mcp_server, "middleware_chain", None),
        session_manager=getattr(mcp_server, "session_manager", None),
        feature_flags=getattr(mcp_server, "feature_flags", None),
        skill_manager=getattr(mcp_server, "skill_manager", None),
        version_checker=getattr(mcp_server, "version_checker", None),
        optimizer_index=getattr(mcp_server, "optimizer_index", None),
        optimizer_enabled=getattr(mcp_server, "optimizer_enabled", False),
        optimizer_keep_list=getattr(mcp_server, "optimizer_keep_list", []),
        telemetry_enabled=getattr(mcp_server, "telemetry_enabled", False),
        composite_tools=getattr(mcp_server, "composite_tools", None) or [],
    )
