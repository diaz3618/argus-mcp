"""Response-cache-by-prompt plugin — avoid redundant MCP calls.

Caches tool results keyed on ``(server_name, capability_name, arguments_hash)``
with a configurable TTL.  Cached hits skip the actual backend call by setting
``ctx.result`` in the **pre-invoke** hook.

Settings (via ``plugin.settings``):
    ttl_seconds : int — time-to-live for cache entries (default 300)
    max_entries : int — maximum number of cached entries (default 256)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time

from argus_mcp.plugins.base import PluginBase, PluginContext
from argus_mcp.plugins.models import PluginConfig

logger = logging.getLogger(__name__)


class ResponseCachePlugin(PluginBase):
    """TTL-based response cache keyed by capability + arguments hash."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._ttl: int = int(config.settings.get("ttl_seconds", 300))
        self._max_entries: int = int(config.settings.get("max_entries", 256))
        # _cache: key -> (result, timestamp)
        self._cache: dict[str, tuple[object, float]] = {}

    # Internal helpers

    @staticmethod
    def _make_key(server: str, capability: str, arguments: dict) -> str:
        """Deterministic cache key from server + capability + sorted args."""
        raw = json.dumps(
            {"s": server, "c": capability, "a": arguments},
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    def _evict_expired(self) -> None:
        now = time.monotonic()
        expired = [k for k, (_, ts) in self._cache.items() if now - ts > self._ttl]
        for k in expired:
            del self._cache[k]

    def _evict_oldest(self) -> None:
        """Drop the oldest entry when at capacity."""
        if len(self._cache) >= self._max_entries:
            oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]

    # Hooks

    async def tool_pre_invoke(self, ctx: PluginContext) -> PluginContext:
        self._evict_expired()
        key = self._make_key(ctx.server_name, ctx.capability_name, ctx.arguments)
        entry = self._cache.get(key)
        if entry is not None:
            result, ts = entry
            if time.monotonic() - ts <= self._ttl:
                ctx.result = result
                ctx.metadata["cache_hit"] = True
                logger.debug("Cache hit for %s/%s", ctx.server_name, ctx.capability_name)
                return ctx
            # Stale — remove it.
            del self._cache[key]

        ctx.metadata["cache_hit"] = False
        ctx.metadata["_cache_key"] = key
        return ctx

    async def tool_post_invoke(self, ctx: PluginContext) -> PluginContext:
        if ctx.metadata.get("cache_hit"):
            return ctx  # Already served from cache.

        key = ctx.metadata.pop("_cache_key", None)
        if key is None:
            return ctx

        # Only cache successful results (no error marker).
        if ctx.metadata.get("error"):
            return ctx

        self._evict_oldest()
        self._cache[key] = (ctx.result, time.monotonic())
        ctx.metadata["cache_stored"] = True
        return ctx

    async def on_unload(self) -> None:
        self._cache.clear()
