"""Abstract base class for all Argus MCP plugins."""

from __future__ import annotations

import abc
from typing import Any, Dict, Optional

from argus_mcp.plugins.models import PluginConfig


class PluginContext:
    """Copy-on-write context passed to plugin hooks.

    Plugins receive a *snapshot* of the request data.  Modifications to
    ``arguments`` or ``metadata`` are isolated per-plugin — downstream
    plugins and the core chain see the accumulated result only after all
    hooks for a phase complete successfully.
    """

    __slots__ = (
        "capability_name",
        "mcp_method",
        "arguments",
        "server_name",
        "metadata",
        "result",
    )

    def __init__(
        self,
        capability_name: str,
        mcp_method: str,
        arguments: Optional[Dict[str, Any]] = None,
        server_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        result: Any = None,
    ) -> None:
        self.capability_name = capability_name
        self.mcp_method = mcp_method
        self.arguments = dict(arguments) if arguments else {}
        self.server_name = server_name or ""
        self.metadata = dict(metadata) if metadata else {}
        self.result = result

    def copy(self) -> PluginContext:
        """Return a shallow copy for copy-on-write isolation."""
        return PluginContext(
            capability_name=self.capability_name,
            mcp_method=self.mcp_method,
            arguments=dict(self.arguments),
            server_name=self.server_name,
            metadata=dict(self.metadata),
            result=self.result,
        )


class PluginBase(abc.ABC):
    """Abstract base class that all plugins must subclass.

    Subclasses override one or more of the hook methods.  The default
    implementations are no-ops so plugins only need to implement the
    hooks they care about.
    """

    def __init__(self, config: PluginConfig) -> None:
        self.config = config

    @property
    def name(self) -> str:
        return self.config.name

    # ── Hook methods (override as needed) ───────────────────────────

    async def tool_pre_invoke(self, ctx: PluginContext) -> PluginContext:
        """Called before a tool invocation reaches the backend.

        Return the (possibly modified) context.  Raise to block the
        invocation when execution_mode is ``enforce``.
        """
        return ctx

    async def tool_post_invoke(self, ctx: PluginContext) -> PluginContext:
        """Called after a tool invocation returns from the backend.

        ``ctx.result`` contains the backend response.
        """
        return ctx

    async def prompt_pre_fetch(self, ctx: PluginContext) -> PluginContext:
        """Called before a prompt is fetched from the backend."""
        return ctx

    async def prompt_post_fetch(self, ctx: PluginContext) -> PluginContext:
        """Called after a prompt is fetched from the backend.

        ``ctx.result`` contains the backend response.
        """
        return ctx

    async def resource_pre_fetch(self, ctx: PluginContext) -> PluginContext:
        """Called before a resource is read from the backend."""
        return ctx

    async def resource_post_fetch(self, ctx: PluginContext) -> PluginContext:
        """Called after a resource is read from the backend.

        ``ctx.result`` contains the backend response.
        """
        return ctx

    async def on_load(self) -> None:
        """Called once when the plugin is loaded.  Optional setup."""

    async def on_unload(self) -> None:
        """Called when the plugin system shuts down.  Optional cleanup."""
