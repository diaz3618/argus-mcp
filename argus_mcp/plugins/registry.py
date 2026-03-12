"""Plugin registry — discovers and stores plugin instances."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Type

from argus_mcp.plugins.base import PluginBase
from argus_mcp.plugins.models import PluginConfig

logger = logging.getLogger(__name__)

# Global mapping of plugin name → class, populated by register_plugin()
_PLUGIN_CLASSES: Dict[str, Type[PluginBase]] = {}


def register_plugin(name: str, cls: Type[PluginBase]) -> None:
    """Register a plugin class by name (used by built-in and external plugins)."""
    _PLUGIN_CLASSES[name] = cls
    logger.debug("Registered plugin class: %s → %s", name, cls.__qualname__)


class PluginRegistry:
    """Discovers, instantiates, and stores plugin instances.

    Usage::

        registry = PluginRegistry()
        registry.load_from_config([PluginConfig(name="secrets_detection")])
        pre_hooks = registry.get_by_hook("tool_pre_invoke")
    """

    def __init__(self) -> None:
        self._plugins: Dict[str, PluginBase] = {}
        self._load_order: List[str] = []

    # ── Loading ──────────────────────────────────────────────────────

    def load_from_config(self, entries: List[PluginConfig]) -> None:
        """Instantiate plugins from config entries.

        Only entries with ``enabled=True`` whose class has been
        registered via :func:`register_plugin` are loaded.
        """
        for entry in entries:
            if not entry.enabled:
                logger.info("Plugin '%s' is disabled — skipping.", entry.name)
                continue
            cls = _PLUGIN_CLASSES.get(entry.name)
            if cls is None:
                logger.warning(
                    "Plugin '%s' has no registered class — skipping. Available: %s",
                    entry.name,
                    sorted(_PLUGIN_CLASSES.keys()),
                )
                continue
            plugin = cls(entry)
            self._plugins[entry.name] = plugin
            self._load_order.append(entry.name)
            logger.info("Loaded plugin '%s' (priority=%d).", entry.name, entry.priority)

    # ── Querying ─────────────────────────────────────────────────────

    def get(self, name: str) -> Optional[PluginBase]:
        return self._plugins.get(name)

    def all_plugins(self) -> List[PluginBase]:
        """Return all loaded plugins in load order."""
        return [self._plugins[n] for n in self._load_order if n in self._plugins]

    def get_by_hook(self, hook_name: str) -> List[PluginBase]:
        """Return plugins that override the given hook, sorted by priority.

        A plugin "overrides" a hook if it defines its own version
        (i.e., the method is not the default no-op from PluginBase).
        """
        base_method = getattr(PluginBase, hook_name, None)
        if base_method is None:
            return []

        result: List[PluginBase] = []
        for plugin in self._plugins.values():
            method = getattr(type(plugin), hook_name, None)
            if method is not None and method is not base_method:
                result.append(plugin)
        return sorted(result, key=lambda p: p.config.priority)

    @property
    def count(self) -> int:
        return len(self._plugins)

    # ── Lifecycle ────────────────────────────────────────────────────

    async def load_all(self) -> None:
        """Call on_load() for every loaded plugin."""
        for plugin in self.all_plugins():
            try:
                await plugin.on_load()
            except Exception:  # noqa: BLE001
                logger.warning("Plugin '%s' on_load() failed.", plugin.name, exc_info=True)

    async def unload_all(self) -> None:
        """Call on_unload() for every loaded plugin (reverse order)."""
        for plugin in reversed(self.all_plugins()):
            try:
                await plugin.on_unload()
            except Exception:  # noqa: BLE001
                logger.warning("Plugin '%s' on_unload() failed.", plugin.name, exc_info=True)
