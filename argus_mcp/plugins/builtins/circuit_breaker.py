"""Circuit-breaker plugin — per-tool failure tracking with half-open probing.

Wraps tool invocations with a lightweight circuit-breaker state machine.
Each *(server, tool)* pair maintains independent CLOSED / OPEN /
HALF_OPEN state.

Settings (via ``plugin.settings``):
    failure_threshold : int   — consecutive failures to trip (default 5)
    cooldown_seconds  : float — seconds before OPEN → HALF_OPEN (default 30)
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Dict, Tuple

from argus_mcp.plugins.base import PluginBase, PluginContext
from argus_mcp.plugins.models import PluginConfig

logger = logging.getLogger(__name__)


class _State(str, Enum):
    closed = "closed"
    open = "open"
    half_open = "half_open"


class _PerToolBreaker:
    """Minimal circuit breaker for one (server, tool) pair."""

    __slots__ = (
        "state",
        "failures",
        "last_failure",
        "failure_threshold",
        "cooldown",
    )

    def __init__(self, failure_threshold: int, cooldown: float) -> None:
        self.state = _State.closed
        self.failures = 0
        self.last_failure = 0.0
        self.failure_threshold = failure_threshold
        self.cooldown = cooldown

    def allows(self) -> bool:
        if self.state == _State.open:
            if (time.monotonic() - self.last_failure) >= self.cooldown:
                self.state = _State.half_open
                return True
            return False
        return True

    def record_success(self) -> None:
        self.state = _State.closed
        self.failures = 0

    def record_failure(self) -> None:
        self.failures += 1
        self.last_failure = time.monotonic()
        if self.failures >= self.failure_threshold:
            self.state = _State.open


class CircuitBreakerPlugin(PluginBase):
    """Plugin-level circuit breaker with per-tool state tracking."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._threshold: int = int(config.settings.get("failure_threshold", 5))
        self._cooldown: float = float(config.settings.get("cooldown_seconds", 30.0))
        self._breakers: Dict[Tuple[str, str], _PerToolBreaker] = {}

    # ── Hooks ────────────────────────────────────────────────────────

    async def tool_pre_invoke(self, ctx: PluginContext) -> PluginContext:
        breaker = self._get(ctx)
        if not breaker.allows():
            ctx.metadata["circuit_open"] = True
            msg = (
                f"Circuit open for {ctx.server_name}/{ctx.capability_name} "
                f"({breaker.failures} failures, cooldown {breaker.cooldown}s)"
            )
            logger.warning(msg)
            raise ValueError(msg)
        ctx.metadata["circuit_state"] = breaker.state.value
        return ctx

    async def tool_post_invoke(self, ctx: PluginContext) -> PluginContext:
        breaker = self._get(ctx)
        # If result metadata indicates error, record failure; else success.
        if ctx.metadata.get("error"):
            breaker.record_failure()
            ctx.metadata["circuit_state"] = breaker.state.value
        else:
            breaker.record_success()
            ctx.metadata["circuit_state"] = breaker.state.value
        return ctx

    # ── Internals ────────────────────────────────────────────────────

    def _get(self, ctx: PluginContext) -> _PerToolBreaker:
        key = (ctx.server_name, ctx.capability_name)
        breaker = self._breakers.get(key)
        if breaker is None:
            breaker = _PerToolBreaker(self._threshold, self._cooldown)
            self._breakers[key] = breaker
        return breaker

    async def on_unload(self) -> None:
        self._breakers.clear()
