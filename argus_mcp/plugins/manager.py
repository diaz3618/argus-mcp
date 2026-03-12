"""Plugin manager — executes hooks with timeout, error isolation, and metadata aggregation."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from argus_mcp.plugins.base import PluginContext
from argus_mcp.plugins.models import ExecutionMode, PluginCondition
from argus_mcp.plugins.registry import PluginRegistry

logger = logging.getLogger(__name__)


class PluginError(Exception):
    """Raised when a plugin hook fails in ``enforce`` mode."""

    def __init__(self, plugin_name: str, hook: str, cause: Exception) -> None:
        self.plugin_name = plugin_name
        self.hook = hook
        self.cause = cause
        super().__init__(f"Plugin '{plugin_name}' failed in {hook}: {cause}")


class PluginManager:
    """Orchestrate plugin hook execution with lifecycle guarantees.

    - **Priority ordering**: lower priority value = runs first.
    - **Timeout protection**: each hook call is bounded (default 30 s).
    - **Error isolation**: configurable per execution mode.
    - **Copy-on-write context**: each plugin gets a snapshot; accumulated
      results are merged only after successful execution.
    - **Metadata aggregation**: plugin metadata is merged into the
      request context after all hooks complete.
    """

    def __init__(self, registry: PluginRegistry) -> None:
        self._registry = registry

    # ── Public API ───────────────────────────────────────────────────

    async def run_hook(
        self,
        hook_name: str,
        ctx: PluginContext,
        *,
        capability_name: Optional[str] = None,
        server_name: Optional[str] = None,
        mcp_method: Optional[str] = None,
    ) -> PluginContext:
        """Execute all plugins for *hook_name* in priority order.

        Returns the accumulated context after all plugins have run.
        """
        plugins = self._registry.get_by_hook(hook_name)
        if not plugins:
            return ctx

        accumulated = ctx
        aggregated_metadata: Dict[str, Any] = {}

        for plugin in plugins:
            if not self._matches_conditions(
                plugin.config.conditions,
                capability_name=capability_name or ctx.capability_name,
                server_name=server_name or ctx.server_name,
                mcp_method=mcp_method or ctx.mcp_method,
            ):
                continue

            mode = plugin.config.execution_mode
            if mode == ExecutionMode.disabled:
                continue

            snapshot = accumulated.copy()

            try:
                hook_fn = getattr(plugin, hook_name)
                result_ctx = await asyncio.wait_for(
                    hook_fn(snapshot),
                    timeout=plugin.config.timeout,
                )
                # Merge successful result
                accumulated = result_ctx
                aggregated_metadata.update(result_ctx.metadata)
            except asyncio.TimeoutError:
                logger.warning(
                    "Plugin '%s' hook '%s' timed out (%.1fs).",
                    plugin.name,
                    hook_name,
                    plugin.config.timeout,
                )
                if mode == ExecutionMode.enforce:
                    raise PluginError(
                        plugin.name,
                        hook_name,
                        TimeoutError(f"timeout after {plugin.config.timeout}s"),
                    )
            except PluginError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Plugin '%s' hook '%s' raised %s: %s",
                    plugin.name,
                    hook_name,
                    type(exc).__name__,
                    exc,
                )
                if mode == ExecutionMode.enforce:
                    raise PluginError(plugin.name, hook_name, exc)
                # enforce_ignore_error / permissive: log and continue

        # Apply aggregated metadata
        accumulated.metadata.update(aggregated_metadata)
        return accumulated

    # ── Convenience wrappers ─────────────────────────────────────────

    async def run_tool_pre_invoke(
        self,
        ctx: PluginContext,
    ) -> PluginContext:
        return await self.run_hook("tool_pre_invoke", ctx)

    async def run_tool_post_invoke(
        self,
        ctx: PluginContext,
    ) -> PluginContext:
        return await self.run_hook("tool_post_invoke", ctx)

    async def run_prompt_pre_fetch(
        self,
        ctx: PluginContext,
    ) -> PluginContext:
        return await self.run_hook("prompt_pre_fetch", ctx)

    async def run_resource_pre_fetch(
        self,
        ctx: PluginContext,
    ) -> PluginContext:
        return await self.run_hook("resource_pre_fetch", ctx)

    # ── Internal helpers ─────────────────────────────────────────────

    @staticmethod
    def _matches_conditions(
        conditions: PluginCondition,
        *,
        capability_name: str,
        server_name: str,
        mcp_method: str,
    ) -> bool:
        """Check whether plugin conditions allow this invocation."""
        if conditions.servers and server_name not in conditions.servers:
            return False
        if conditions.tools and capability_name not in conditions.tools:
            return False
        if conditions.mcp_methods and mcp_method not in conditions.mcp_methods:
            return False
        return True
