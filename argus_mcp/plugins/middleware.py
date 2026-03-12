"""Plugin middleware — integrates plugin hooks into the MCP middleware chain."""

from __future__ import annotations

import logging
from typing import Any

from argus_mcp.bridge.middleware.chain import MCPHandler, RequestContext
from argus_mcp.plugins.base import PluginContext
from argus_mcp.plugins.manager import PluginManager

logger = logging.getLogger(__name__)

# Map MCP method names to hook names
_PRE_HOOKS = {
    "call_tool": "tool_pre_invoke",
    "read_resource": "resource_pre_fetch",
    "get_prompt": "prompt_pre_fetch",
}

_POST_HOOKS = {
    "call_tool": "tool_post_invoke",
    "read_resource": "resource_post_fetch",
    "get_prompt": "prompt_post_fetch",
}


class PluginMiddleware:
    """MCPMiddleware that runs plugin hooks before and after the chain.

    Inserted into the middleware chain between Recovery and Audit so that:
    - Pre-hooks run after error recovery is set up but before audit logging.
    - Post-hooks run after the backend responds (for tool calls only).

    Chain order with plugins:
    Auth (opt) → Recovery → **PluginMiddleware** → Telemetry (opt) → Audit → Routing
    """

    def __init__(self, manager: PluginManager) -> None:
        self._manager = manager

    async def __call__(self, ctx: RequestContext, next_handler: MCPHandler) -> Any:
        mcp_method = ctx.mcp_method

        # ── Pre-hook ─────────────────────────────────────────────
        pre_hook = _PRE_HOOKS.get(mcp_method)
        if pre_hook:
            plugin_ctx = _request_to_plugin_ctx(ctx)
            plugin_ctx = await self._manager.run_hook(
                pre_hook,
                plugin_ctx,
                capability_name=ctx.capability_name,
                server_name=ctx.server_name or "",
                mcp_method=mcp_method,
            )
            _apply_plugin_ctx(ctx, plugin_ctx)

        # ── Delegate to next handler ─────────────────────────────
        result = await next_handler(ctx)

        # ── Post-hook ────────────────────────────────────────────
        post_hook = _POST_HOOKS.get(mcp_method)
        if post_hook:
            plugin_ctx = _request_to_plugin_ctx(ctx, result=result)
            plugin_ctx = await self._manager.run_hook(
                post_hook,
                plugin_ctx,
                capability_name=ctx.capability_name,
                server_name=ctx.server_name or "",
                mcp_method=mcp_method,
            )
            _apply_plugin_ctx(ctx, plugin_ctx)
            result = plugin_ctx.result

        return result


def _request_to_plugin_ctx(
    ctx: RequestContext,
    *,
    result: Any = None,
) -> PluginContext:
    """Convert a middleware RequestContext to a PluginContext."""
    return PluginContext(
        capability_name=ctx.capability_name,
        mcp_method=ctx.mcp_method,
        arguments=ctx.arguments,
        server_name=ctx.server_name,
        metadata=ctx.metadata,
        result=result,
    )


def _apply_plugin_ctx(ctx: RequestContext, plugin_ctx: PluginContext) -> None:
    """Merge plugin-modified fields back into the RequestContext."""
    ctx.arguments = plugin_ctx.arguments
    ctx.metadata.update(plugin_ctx.metadata)
