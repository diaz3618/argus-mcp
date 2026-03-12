"""Retry-with-backoff plugin — transient failure handling as a plugin hook.

Wraps tool post-invoke results: when an error indicator is present in
the result metadata the plugin triggers an exponential-backoff retry
by re-raising so the framework (or outer retry layer) can resubmit.

Settings (via ``plugin.settings``):
    max_retries    : int   — maximum retry attempts (default 3)
    base_delay     : float — initial delay in seconds (default 1.0)
    backoff_factor : float — multiplier per retry (default 2.0)
    max_delay      : float — ceiling on computed delay (default 30.0)
"""

from __future__ import annotations

import asyncio
import logging
import random

from argus_mcp.plugins.base import PluginBase, PluginContext
from argus_mcp.plugins.models import PluginConfig

logger = logging.getLogger(__name__)


class RetryWithBackoffPlugin(PluginBase):
    """Adds exponential-backoff retry metadata for transient failures."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._max_retries: int = int(config.settings.get("max_retries", 3))
        self._base_delay: float = float(config.settings.get("base_delay", 1.0))
        self._backoff_factor: float = float(config.settings.get("backoff_factor", 2.0))
        self._max_delay: float = float(config.settings.get("max_delay", 30.0))

    async def tool_post_invoke(self, ctx: PluginContext) -> PluginContext:
        if not ctx.metadata.get("error"):
            # No error — nothing to retry.
            ctx.metadata.pop("retry_attempt", None)
            return ctx

        attempt = ctx.metadata.get("retry_attempt", 0)
        if attempt >= self._max_retries:
            ctx.metadata["retries_exhausted"] = True
            logger.warning(
                "Retries exhausted for %s/%s after %d attempts.",
                ctx.server_name,
                ctx.capability_name,
                attempt,
            )
            return ctx

        delay = min(
            self._base_delay * (self._backoff_factor**attempt),
            self._max_delay,
        )
        # Add jitter ±25 %
        jitter = delay * 0.25 * (2 * random.random() - 1)  # noqa: S311
        delay = max(0.0, delay + jitter)

        ctx.metadata["retry_attempt"] = attempt + 1
        ctx.metadata["retry_delay"] = round(delay, 3)
        ctx.metadata["retry_suggested"] = True

        logger.info(
            "Suggesting retry %d/%d for %s/%s in %.3fs.",
            attempt + 1,
            self._max_retries,
            ctx.server_name,
            ctx.capability_name,
            delay,
        )

        # Sleep to enforce the backoff delay
        await asyncio.sleep(delay)
        return ctx
