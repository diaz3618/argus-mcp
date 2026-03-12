"""Output-length-guard plugin — prevent terminal overflow for TUI.

Truncates overly long tool results to a configurable maximum character
count.  When truncation occurs, a sentinel suffix is appended so the
consumer knows the output was clipped.

Settings (via ``plugin.settings``):
    max_length : int — maximum character length of the result (default 50_000)
    suffix     : str — text appended when truncated (default "... [truncated]")
"""

from __future__ import annotations

import logging

from argus_mcp.plugins.base import PluginBase, PluginContext
from argus_mcp.plugins.models import PluginConfig

logger = logging.getLogger(__name__)


class OutputLengthGuardPlugin(PluginBase):
    """Truncates tool results exceeding a configurable character limit."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._max_length: int = int(config.settings.get("max_length", 50_000))
        self._suffix: str = str(config.settings.get("suffix", "... [truncated]"))

    async def tool_post_invoke(self, ctx: PluginContext) -> PluginContext:
        if not isinstance(ctx.result, str):
            return ctx

        if len(ctx.result) <= self._max_length:
            ctx.metadata["output_truncated"] = False
            return ctx

        original_length = len(ctx.result)
        # Truncate, leaving room for the suffix.
        cut_at = max(0, self._max_length - len(self._suffix))
        ctx.result = ctx.result[:cut_at] + self._suffix
        ctx.metadata["output_truncated"] = True
        ctx.metadata["output_original_length"] = original_length
        logger.info(
            "Truncated output for %s/%s from %d to %d chars.",
            ctx.server_name,
            ctx.capability_name,
            original_length,
            len(ctx.result),
        )
        return ctx
