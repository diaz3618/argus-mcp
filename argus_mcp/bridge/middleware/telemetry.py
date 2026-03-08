"""Telemetry middleware for the MCP data plane.

Creates a trace span per MCP request and records metrics
(request count, duration, error rate).

Slot order in the chain: **Auth → AuthZ → TELEMETRY → Audit → Recovery → Routing**.

When OTel is not installed, this middleware is a lightweight pass-through.
"""

from __future__ import annotations

import logging
from typing import Any

from argus_mcp.bridge.middleware.chain import MCPHandler, RequestContext
from argus_mcp.telemetry.metrics import record_request
from argus_mcp.telemetry.tracing import start_span

logger = logging.getLogger(__name__)


class TelemetryMiddleware:
    """MCP middleware that records traces and metrics."""

    async def __call__(self, ctx: RequestContext, next_handler: MCPHandler) -> Any:
        """Wrap the request in a span and record metrics."""
        span_name = f"mcp.{ctx.mcp_method}.{ctx.capability_name}"

        with start_span(
            span_name,
            attributes={
                "mcp.method": ctx.mcp_method,
                "mcp.capability": ctx.capability_name,
                "mcp.request_id": ctx.request_id,
            },
        ) as span:
            success = True
            try:
                result = await next_handler(ctx)
                return result
            except Exception as exc:  # noqa: BLE001
                success = False
                span.record_exception(exc)
                raise
            finally:
                server = ctx.server_name or "unknown"
                span.set_attribute("mcp.backend", server)

                record_request(
                    tool_name=ctx.capability_name,
                    backend=server,
                    duration_ms=ctx.elapsed_ms,
                    success=success,
                )
