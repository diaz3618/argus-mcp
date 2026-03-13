"""Rate-limiter plugin — fixed-window limiting per tool or server.

Tracks invocation counts in a fixed time window and rejects requests
that exceed the configured limit.  Windows are keyed by
*(server_name, tool_name)* so limits are isolated per-tool per-backend.

Settings (via ``plugin.settings``):
    max_requests : int   — maximum requests per window (default 100)
    window_seconds : int — window duration in seconds (default 60)
"""

from __future__ import annotations

import logging
import time
from typing import Dict, Tuple

from argus_mcp.plugins.base import PluginBase, PluginContext
from argus_mcp.plugins.models import PluginConfig

logger = logging.getLogger(__name__)


class _WindowCounter:
    """Simple fixed-window counter."""

    __slots__ = ("count", "window_start")

    def __init__(self, now: float) -> None:
        self.count = 0
        self.window_start = now


class RateLimiterPlugin(PluginBase):
    """Fixed-window rate limiter on tool invocations."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._max_requests: int = int(config.settings.get("max_requests", 100))
        self._window_seconds: int = int(config.settings.get("window_seconds", 60))
        # keyed (server, tool) → counter
        self._windows: Dict[Tuple[str, str], _WindowCounter] = {}

    async def tool_pre_invoke(self, ctx: PluginContext) -> PluginContext:
        key = (ctx.server_name, ctx.capability_name)
        now = time.monotonic()

        counter = self._windows.get(key)
        if counter is None or (now - counter.window_start) >= self._window_seconds:
            counter = _WindowCounter(now)
            self._windows[key] = counter

        counter.count += 1

        if counter.count > self._max_requests:
            remaining = self._window_seconds - (now - counter.window_start)
            ctx.metadata["rate_limited"] = True
            ctx.metadata["retry_after_seconds"] = round(remaining, 1)
            msg = (
                f"Rate limit exceeded for {ctx.server_name}/{ctx.capability_name}: "
                f"{counter.count}/{self._max_requests} in {self._window_seconds}s window. "
                f"Retry after {remaining:.1f}s."
            )
            logger.warning(msg)
            raise ValueError(msg)

        ctx.metadata["rate_limit_remaining"] = self._max_requests - counter.count
        return ctx

    async def on_unload(self) -> None:
        self._windows.clear()
