"""OPA (Open Policy Agent) plugin — Rego policy enforcement.

Sends an authorization request to a running OPA server before and after
every hook.  The OPA server evaluates a Rego policy and returns an
allow/deny decision.

Settings (in ``config.settings``):
    opa_url:           OPA base URL (default ``http://localhost:8181``)
    policy_path:       Policy decision path (default ``v1/data/argus/allow``)
    default_decision:  Decision when OPA is unreachable (default ``True`` = allow)
    timeout:           Request timeout in seconds (default ``5``)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict

from argus_mcp.plugins.base import PluginBase, PluginContext
from argus_mcp.plugins.models import PluginConfig

logger = logging.getLogger(__name__)


class OPAPolicyPlugin(PluginBase):
    """Rego policy enforcement via Open Policy Agent."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._opa_url: str = config.settings.get(
            "opa_url",
            os.environ.get("OPA_URL", "http://localhost:8181"),
        )
        self._policy_path: str = config.settings.get("policy_path", "v1/data/argus/allow")
        self._default_decision: bool = config.settings.get("default_decision", True)
        self._timeout: float = float(config.settings.get("timeout", 5))
        self._client: Any = None

    async def on_load(self) -> None:
        import httpx

        self._client = httpx.AsyncClient(
            base_url=self._opa_url.rstrip("/"),
            timeout=httpx.Timeout(connect=3.0, read=self._timeout, write=3.0, pool=3.0),
        )

    async def on_unload(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def tool_pre_invoke(self, ctx: PluginContext) -> PluginContext:
        return await self._evaluate(ctx, "tool_pre_invoke")

    async def tool_post_invoke(self, ctx: PluginContext) -> PluginContext:
        return await self._evaluate(ctx, "tool_post_invoke")

    async def prompt_pre_fetch(self, ctx: PluginContext) -> PluginContext:
        return await self._evaluate(ctx, "prompt_pre_fetch")

    async def prompt_post_fetch(self, ctx: PluginContext) -> PluginContext:
        return await self._evaluate(ctx, "prompt_post_fetch")

    async def resource_pre_fetch(self, ctx: PluginContext) -> PluginContext:
        return await self._evaluate(ctx, "resource_pre_fetch")

    async def resource_post_fetch(self, ctx: PluginContext) -> PluginContext:
        return await self._evaluate(ctx, "resource_post_fetch")

    async def _evaluate(self, ctx: PluginContext, phase: str) -> PluginContext:
        payload = self._build_input(ctx, phase)
        allowed = await self._query_opa(payload)

        ctx.metadata[f"opa_{phase}"] = "allow" if allowed else "deny"
        if not allowed:
            raise ValueError(
                f"OPA policy denied: {ctx.capability_name} ({phase}, server={ctx.server_name})"
            )
        return ctx

    def _build_input(self, ctx: PluginContext, phase: str) -> Dict[str, Any]:
        return {
            "input": {
                "capability": ctx.capability_name,
                "method": ctx.mcp_method,
                "server": ctx.server_name,
                "phase": phase,
                "arguments": _sanitize(ctx.arguments),
            }
        }

    async def _query_opa(self, payload: Dict[str, Any]) -> bool:
        if not self._client:
            return self._default_decision
        try:
            resp = await self._client.post(
                f"/{self._policy_path}",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            result = data.get("result")
            if isinstance(result, bool):
                return result
            if isinstance(result, dict):
                return bool(result.get("allow", self._default_decision))
            return self._default_decision
        except Exception:
            logger.warning("OPA query failed, using default decision.", exc_info=True)
            return self._default_decision


def _sanitize(obj: Any, *, depth: int = 0, max_depth: int = 5) -> Any:
    if depth >= max_depth:
        return "<truncated>"
    if isinstance(obj, dict):
        return {k: _sanitize(v, depth=depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize(v, depth=depth + 1) for v in obj]
    if isinstance(obj, (str, int, float, bool, type(None))):
        return obj
    return str(obj)
