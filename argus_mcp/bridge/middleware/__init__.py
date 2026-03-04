"""Middleware chain for composable MCP request processing.

The middleware pattern wraps request handling in layers that can inspect,
modify, or reject requests *before* they reach a backend, and inspect or
modify responses on the way back.

Public API
----------
- :class:`RequestContext` — Per-request metadata bag (timing, routing, etc.)
- :data:`MCPHandler` / :data:`MCPMiddleware` — Async callable protocols
- :func:`build_chain` — Compose a list of middleware into a single handler
- :class:`RecoveryMiddleware` — Exception safety net
- :class:`AuditMiddleware` — Basic audit logging
- :class:`RoutingMiddleware` — Routes requests to backend sessions
"""

from argus_mcp.bridge.middleware.audit import AuditMiddleware
from argus_mcp.bridge.middleware.chain import (
    MCPHandler,
    MCPMiddleware,
    RequestContext,
    build_chain,
)
from argus_mcp.bridge.middleware.recovery import RecoveryMiddleware
from argus_mcp.bridge.middleware.routing import RoutingMiddleware

__all__ = [
    "AuditMiddleware",
    "MCPHandler",
    "MCPMiddleware",
    "RecoveryMiddleware",
    "RequestContext",
    "RoutingMiddleware",
    "build_chain",
]
