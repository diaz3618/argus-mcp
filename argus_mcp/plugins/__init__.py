"""Plugin framework for Argus MCP.

Provides a hook-based plugin system with execution modes, priority
ordering, timeout protection, error isolation, and metadata aggregation.

Public API
----------
- :class:`PluginBase` — Abstract base class for all plugins
- :class:`PluginConfig` — Pydantic model for plugin configuration
- :class:`PluginRegistry` — Discovers and registers plugins
- :class:`PluginManager` — Executes plugin hooks with lifecycle management
- :class:`PluginMiddleware` — Middleware adapter for the MCP chain
"""

from argus_mcp.plugins.base import PluginBase
from argus_mcp.plugins.manager import PluginManager
from argus_mcp.plugins.middleware import PluginMiddleware
from argus_mcp.plugins.models import ExecutionMode, PluginCondition, PluginConfig
from argus_mcp.plugins.registry import PluginRegistry

__all__ = [
    "ExecutionMode",
    "PluginBase",
    "PluginCondition",
    "PluginConfig",
    "PluginManager",
    "PluginMiddleware",
    "PluginRegistry",
]
