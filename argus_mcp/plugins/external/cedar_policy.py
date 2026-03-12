"""Cedar policy plugin — Cedar authorization policy enforcement.

Sends authorization requests to an AWS Verified Permissions or
Cedar-compatible policy evaluation endpoint.

Settings (in ``config.settings``):
    cedar_url:         Cedar evaluation endpoint URL
                       (default ``http://localhost:8180/v1/is-authorized``)
    policy_store_id:   AWS Verified Permissions policy store ID (optional)
    api_key:           API key or AWS credentials reference (optional,
                       falls back to ``CEDAR_API_KEY`` env var)
    default_decision:  Decision when Cedar is unreachable (default ``True``)
    timeout:           Request timeout in seconds (default ``5``)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from argus_mcp.plugins.base import PluginBase, PluginContext
from argus_mcp.plugins.models import PluginConfig

logger = logging.getLogger(__name__)


class CedarPolicyPlugin(PluginBase):
    """Cedar authorization policy enforcement."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._cedar_url: str = config.settings.get(
            "cedar_url",
            os.environ.get("CEDAR_URL", "http://localhost:8180/v1/is-authorized"),
        )
        self._policy_store_id: Optional[str] = config.settings.get("policy_store_id")
        self._api_key: str = config.settings.get("api_key", os.environ.get("CEDAR_API_KEY", ""))
        self._default_decision: bool = config.settings.get("default_decision", True)
        self._timeout: float = float(config.settings.get("timeout", 5))
        self._client: Any = None

    async def on_load(self) -> None:
        import httpx

        headers: Dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=3.0, read=self._timeout, write=3.0, pool=3.0),
            headers=headers,
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
        allowed = await self._query_cedar(ctx, phase)
        ctx.metadata[f"cedar_{phase}"] = "allow" if allowed else "deny"
        if not allowed:
            raise ValueError(
                f"Cedar policy denied: {ctx.capability_name} ({phase}, server={ctx.server_name})"
            )
        return ctx

    async def _query_cedar(self, ctx: PluginContext, phase: str) -> bool:
        if not self._client:
            return self._default_decision

        payload = self._build_request(ctx, phase)
        try:
            resp = await self._client.post(self._cedar_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            decision = data.get("decision", data.get("isAuthorized"))
            if isinstance(decision, str):
                return decision.upper() == "ALLOW"
            if isinstance(decision, bool):
                return decision
            return self._default_decision
        except Exception:
            logger.warning("Cedar query failed, using default decision.", exc_info=True)
            return self._default_decision

    def _build_request(self, ctx: PluginContext, phase: str) -> Dict[str, Any]:
        request: Dict[str, Any] = {
            "principal": {
                "entityType": "Argus::Client",
                "entityId": ctx.server_name or "anonymous",
            },
            "action": {
                "actionType": "Argus::Action",
                "actionId": phase,
            },
            "resource": {
                "entityType": "Argus::Capability",
                "entityId": ctx.capability_name or "unknown",
            },
            "context": {
                "method": ctx.mcp_method,
                "server": ctx.server_name,
            },
        }
        if self._policy_store_id:
            request["policyStoreId"] = self._policy_store_id
        return request
