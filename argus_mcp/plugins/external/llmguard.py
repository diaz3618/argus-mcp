"""LLMGuard plugin — prompt injection and toxicity detection.

Calls an LLMGuard HTTP service to scan prompt text for injection
attacks, toxic content, and other safety violations before and after
prompt fetches reach the backend MCP server.

Settings (in ``config.settings``):
    api_url:    LLMGuard API endpoint (default ``http://localhost:8800``)
    threshold:  Detection confidence threshold 0.0–1.0 (default ``0.5``)
    scanners:   List of scanner names to enable (default: all)
    block:      Whether to block on detection (default ``True``)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

from argus_mcp.plugins.base import PluginBase, PluginContext
from argus_mcp.plugins.models import PluginConfig

logger = logging.getLogger(__name__)


class LLMGuardPlugin(PluginBase):
    """AI safety guardrails via LLMGuard Docker service."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._api_url: str = config.settings.get(
            "api_url",
            os.environ.get("LLMGUARD_API_URL", "http://localhost:8800"),
        )
        self._threshold: float = float(config.settings.get("threshold", 0.5))
        self._scanners: Optional[List[str]] = config.settings.get("scanners")
        self._block: bool = config.settings.get("block", True)
        self._client: Any = None

    async def on_load(self) -> None:
        import httpx

        self._client = httpx.AsyncClient(
            base_url=self._api_url,
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=5.0),
        )

    async def on_unload(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def prompt_pre_fetch(self, ctx: PluginContext) -> PluginContext:
        text = self._extract_text(ctx.arguments)
        if text:
            await self._scan(ctx, text, phase="pre_fetch")
        return ctx

    async def prompt_post_fetch(self, ctx: PluginContext) -> PluginContext:
        if isinstance(ctx.result, str) and ctx.result:
            await self._scan(ctx, ctx.result, phase="post_fetch")
        return ctx

    async def _scan(
        self,
        ctx: PluginContext,
        text: str,
        *,
        phase: str,
    ) -> None:
        if not self._client:
            return

        payload: Dict[str, Any] = {"prompt": text}
        if self._scanners:
            payload["scanners"] = self._scanners

        try:
            resp = await self._client.post("/analyze/prompt", json=payload)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            logger.warning("LLMGuard service unavailable during %s scan.", phase)
            return

        results = data.get("results", [])
        for item in results:
            score = float(item.get("score", 0.0))
            scanner = item.get("scanner_name", "unknown")
            if score >= self._threshold:
                ctx.metadata[f"llmguard_{scanner}_{phase}"] = score
                if self._block:
                    msg = (
                        f"LLMGuard: {scanner} detected (score={score:.2f}, "
                        f"threshold={self._threshold:.2f}) during {phase}"
                    )
                    raise ValueError(msg)
                logger.warning(
                    "LLMGuard: %s flagged (score=%.2f) during %s — permissive mode.",
                    scanner,
                    score,
                    phase,
                )

    @staticmethod
    def _extract_text(arguments: Dict[str, Any]) -> str:
        for key in ("prompt", "text", "message", "content", "query"):
            val = arguments.get(key)
            if isinstance(val, str):
                return val
        return " ".join(str(v) for v in arguments.values() if isinstance(v, str))
