"""Routing middleware — routes requests to the correct backend session.

This is the innermost middleware and the only one that actually talks to
backend servers. It resolves capability names via the registry and calls
the backend via the client manager, populating the request context with
routing information on the way.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from argus_mcp.bridge.middleware.chain import RequestContext
from argus_mcp.errors import BackendServerError

logger = logging.getLogger(__name__)

_ALLOWED_MCP_METHODS = {"call_tool", "read_resource", "get_prompt"}


class RoutingMiddleware:
    """Resolve capability → backend and forward the request.

    This is the innermost middleware and the only layer that actually
    talks to backend servers.
    """

    def __init__(self, registry: Any, manager: Any) -> None:
        self._registry = registry
        self._manager = manager

    async def __call__(self, ctx: RequestContext, next_handler: Any = None) -> Any:
        """Route and forward. *next_handler* is ignored (terminal layer)."""
        if not self._registry or not self._manager:
            raise BackendServerError("Internal server error: core components not initialized.")

        route_info = self._registry.resolve_capability(ctx.capability_name)
        if not route_info:
            raise ValueError(f"Capability '{ctx.capability_name}' does not exist.")

        svr_name, orig_cap_name = route_info
        ctx.server_name = svr_name
        ctx.original_name = orig_cap_name

        session = self._manager.get_session(svr_name)
        if not session:
            raise RuntimeError(
                f"Unable to connect to backend server '{svr_name}' "
                f"providing '{ctx.capability_name}' (session missing or lost)."
            )

        if ctx.mcp_method not in _ALLOWED_MCP_METHODS:
            raise NotImplementedError(
                f"Internal server error: unsupported method '{ctx.mcp_method}'."
            )

        target_method = getattr(session, ctx.mcp_method)

        try:
            if ctx.mcp_method == "call_tool":
                result = await target_method(name=orig_cap_name, arguments=ctx.arguments or {})
            elif ctx.mcp_method == "read_resource":
                result = await target_method(uri=orig_cap_name)
            elif ctx.mcp_method == "get_prompt":
                result = await target_method(name=orig_cap_name, arguments=ctx.arguments)
            else:
                raise NotImplementedError(f"Cannot handle request type '{ctx.mcp_method}'.")

            logger.debug(
                "[%s] Routed %s/%s → %s/%s OK",
                ctx.request_id,
                ctx.mcp_method,
                ctx.capability_name,
                svr_name,
                orig_cap_name,
            )
            return result

        except asyncio.TimeoutError:
            logger.debug(
                "[%s] Timeout: %s → %s/%s",
                ctx.request_id,
                ctx.capability_name,
                svr_name,
                ctx.mcp_method,
            )
            raise
        except (ConnectionError, BrokenPipeError) as exc:
            logger.debug(
                "[%s] Connection lost: %s → %s: %s",
                ctx.request_id,
                ctx.capability_name,
                svr_name,
                type(exc).__name__,
            )
            raise
