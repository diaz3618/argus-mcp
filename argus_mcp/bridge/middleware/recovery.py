"""Recovery middleware — exception safety net.

Catches any exception raised by downstream middleware or the final
handler and returns a structured MCP JSON-RPC error response so that
the client always gets a well-formed reply.
"""

from __future__ import annotations

import logging
from typing import Any

from argus_mcp.bridge.middleware.chain import RequestContext

logger = logging.getLogger(__name__)


class RecoveryMiddleware:
    """Wrap the chain in a try/except to guarantee clean error responses."""

    async def __call__(self, ctx: RequestContext, next_handler: Any) -> Any:
        try:
            return await next_handler(ctx)
        except Exception as exc:  # noqa: BLE001
            ctx.error = exc
            logger.error(
                "[%s] Recovery caught exception in %s/%s: %s",
                ctx.request_id,
                ctx.mcp_method,
                ctx.capability_name,
                exc,
                exc_info=True,
            )
            # Return a structured error. Sanitize the message to avoid
            # leaking internal details (file paths, SQL, stack traces)
            # to untrusted clients.
            error_type = type(exc).__name__
            safe_message = f"Internal error processing {ctx.mcp_method}"
            logger.debug("Full error detail for %s: %s: %s", ctx.request_id, error_type, exc)

            # Try to return an MCP-typed error if possible
            try:
                from mcp.types import CallToolResult, TextContent

                return CallToolResult(
                    content=[TextContent(type="text", text=safe_message)],
                    isError=True,
                )
            except ImportError:
                # Fallback if mcp types aren't available
                return {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32603,
                        "message": safe_message,
                    },
                    "id": ctx.metadata.get("jsonrpc_id"),
                }
