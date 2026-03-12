"""Unified PDP (Policy Decision Point) plugin — multi-engine RBAC orchestrator.

Combines decisions from multiple policy engines (native RBAC, MAC labels,
OPA, Cedar) using a configurable combination mode.  Caches combined
decisions in memory for fast repeated lookups.

Combination modes (``combination_mode`` setting):
    all_must_allow  — every engine must allow (default, most restrictive)
    any_allow       — at least one engine must allow
    first_match     — use the decision from the first engine that responds

Settings (in ``config.settings``):
    engines:           List of engine configs, each with:
                         name:    Engine identifier (opa, cedar, native)
                         url:     Endpoint URL
                         path:    Policy path / resource
                         api_key: Optional API key
                         enabled: Whether this engine is active (default True)
    combination_mode:  "all_must_allow" | "any_allow" | "first_match"
    cache_ttl:         Cache TTL in seconds (default ``60``)
    default_decision:  Decision when no engines respond (default ``True``)
    timeout:           Per-engine request timeout in seconds (default ``5``)
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Tuple

from argus_mcp.plugins.base import PluginBase, PluginContext
from argus_mcp.plugins.models import PluginConfig

logger = logging.getLogger(__name__)


class UnifiedPDPPlugin(PluginBase):
    """Multi-engine RBAC / policy orchestrator."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._engines: List[Dict[str, Any]] = [
            e for e in config.settings.get("engines", []) if e.get("enabled", True)
        ]
        self._combination_mode: str = config.settings.get("combination_mode", "all_must_allow")
        self._cache_ttl: int = int(config.settings.get("cache_ttl", 60))
        self._default_decision: bool = config.settings.get("default_decision", True)
        self._timeout: float = float(config.settings.get("timeout", 5))
        self._client: Any = None
        self._cache: Dict[str, Tuple[float, bool]] = {}

    async def on_load(self) -> None:
        if not self._engines:
            logger.warning("Unified PDP: no engines configured.")
            return
        import httpx

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=3.0, read=self._timeout, write=3.0, pool=3.0),
        )

    async def on_unload(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        self._cache.clear()

    async def tool_pre_invoke(self, ctx: PluginContext) -> PluginContext:
        return await self._decide(ctx, "tool_pre_invoke")

    async def tool_post_invoke(self, ctx: PluginContext) -> PluginContext:
        return await self._decide(ctx, "tool_post_invoke")

    async def prompt_pre_fetch(self, ctx: PluginContext) -> PluginContext:
        return await self._decide(ctx, "prompt_pre_fetch")

    async def prompt_post_fetch(self, ctx: PluginContext) -> PluginContext:
        return await self._decide(ctx, "prompt_post_fetch")

    async def resource_pre_fetch(self, ctx: PluginContext) -> PluginContext:
        return await self._decide(ctx, "resource_pre_fetch")

    async def resource_post_fetch(self, ctx: PluginContext) -> PluginContext:
        return await self._decide(ctx, "resource_post_fetch")

    async def _decide(self, ctx: PluginContext, phase: str) -> PluginContext:
        cache_key = f"{ctx.server_name}:{ctx.capability_name}:{phase}"

        cached = self._cache.get(cache_key)
        if cached:
            ts, decision = cached
            if time.monotonic() - ts < self._cache_ttl:
                ctx.metadata[f"pdp_{phase}"] = "allow(cached)" if decision else "deny(cached)"
                if not decision:
                    raise ValueError(
                        f"Unified PDP denied (cached): {ctx.capability_name} ({phase})"
                    )
                return ctx

        decisions = await self._query_engines(ctx, phase)
        allowed = self._combine(decisions)
        self._cache[cache_key] = (time.monotonic(), allowed)

        ctx.metadata[f"pdp_{phase}"] = "allow" if allowed else "deny"
        ctx.metadata[f"pdp_{phase}_details"] = decisions

        if not allowed:
            deniers = [d["engine"] for d in decisions if not d.get("allow", True)]
            raise ValueError(
                f"Unified PDP denied: {ctx.capability_name} ({phase}) "
                f"— denied by: {', '.join(deniers)}"
            )
        return ctx

    async def _query_engines(self, ctx: PluginContext, phase: str) -> List[Dict[str, Any]]:
        if not self._client or not self._engines:
            return []

        tasks = [self._query_single(engine, ctx, phase) for engine in self._engines]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        decisions: List[Dict[str, Any]] = []
        for engine, result in zip(self._engines, results):
            name = engine.get("name", "unknown")
            if isinstance(result, Exception):
                logger.warning("PDP engine %s failed: %s", name, result)
                decisions.append(
                    {
                        "engine": name,
                        "allow": self._default_decision,
                        "error": str(result),
                    }
                )
            elif isinstance(result, dict):
                decisions.append(result)
        return decisions

    async def _query_single(
        self,
        engine: Dict[str, Any],
        ctx: PluginContext,
        phase: str,
    ) -> Dict[str, Any]:
        name = engine.get("name", "unknown")
        url = engine.get("url", "")
        path = engine.get("path", "")
        api_key = engine.get("api_key", "")

        headers: Dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "input": {
                "capability": ctx.capability_name,
                "method": ctx.mcp_method,
                "server": ctx.server_name,
                "phase": phase,
            }
        }

        endpoint = f"{url.rstrip('/')}/{path.lstrip('/')}" if path else url
        resp = await self._client.post(endpoint, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        decision = data.get("result", data.get("decision", data.get("allow")))
        if isinstance(decision, bool):
            allowed = decision
        elif isinstance(decision, str):
            allowed = decision.upper() == "ALLOW"
        elif isinstance(decision, dict):
            allowed = bool(decision.get("allow", self._default_decision))
        else:
            allowed = self._default_decision

        return {"engine": name, "allow": allowed}

    def _combine(self, decisions: List[Dict[str, Any]]) -> bool:
        if not decisions:
            return self._default_decision

        allows = [d.get("allow", self._default_decision) for d in decisions]

        if self._combination_mode == "all_must_allow":
            return all(allows)
        if self._combination_mode == "any_allow":
            return any(allows)
        if self._combination_mode == "first_match":
            return allows[0]
        return all(allows)
