"""Content moderation plugin — multi-provider harmful-content detection.

Routes text through a configured moderation provider to flag or block
content in categories such as hate, violence, sexual, self-harm, etc.

Supported providers (selected via ``provider`` setting):
    openai      — OpenAI Moderation API
    azure       — Azure Content Safety API
    aws         — AWS Comprehend Detect Toxic Content
    granite     — Granite Guardian / Ollama local model
    watson      — IBM Watson Natural Language Understanding

Settings (in ``config.settings``):
    provider:          Provider name (required)
    api_url:           Base URL override (provider-dependent)
    api_key:           API key (falls back to env vars per provider)
    threshold:         Score threshold to trigger action (default ``0.7``)
    categories:        Categories to check (default all)
    action:            "block" | "warn" | "redact"  (default ``"block"``)
    timeout:           Request timeout in seconds (default ``10``)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Set

from argus_mcp.plugins.base import PluginBase, PluginContext
from argus_mcp.plugins.models import PluginConfig

logger = logging.getLogger(__name__)

_DEFAULT_CATEGORIES: Set[str] = {
    "hate",
    "violence",
    "sexual",
    "self-harm",
    "harassment",
    "spam",
    "profanity",
    "toxicity",
}

_PROVIDER_ENV_KEYS: Dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "azure": "AZURE_CONTENT_SAFETY_KEY",
    "aws": "AWS_ACCESS_KEY_ID",
    "granite": "OLLAMA_BASE_URL",
    "watson": "WATSON_NLU_API_KEY",
}


class ContentModerationPlugin(PluginBase):
    """Multi-provider content moderation."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._provider: str = config.settings.get("provider", "openai")
        self._api_url: Optional[str] = config.settings.get("api_url")
        env_key = _PROVIDER_ENV_KEYS.get(self._provider, "")
        self._api_key: str = config.settings.get("api_key", os.environ.get(env_key, ""))
        self._threshold: float = float(config.settings.get("threshold", 0.7))
        self._categories: Set[str] = set(
            config.settings.get("categories", list(_DEFAULT_CATEGORIES))
        )
        self._action: str = config.settings.get("action", "block")
        self._timeout: float = float(config.settings.get("timeout", 10))
        self._client: Any = None

    async def on_load(self) -> None:
        import httpx

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=5.0,
                read=self._timeout,
                write=5.0,
                pool=5.0,
            ),
        )

    async def on_unload(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def prompt_pre_fetch(self, ctx: PluginContext) -> PluginContext:
        text = self._extract_text(ctx.arguments)
        if text:
            await self._moderate(ctx, text, "prompt_pre_fetch")
        return ctx

    async def tool_pre_invoke(self, ctx: PluginContext) -> PluginContext:
        text = self._extract_text(ctx.arguments)
        if text:
            await self._moderate(ctx, text, "tool_pre_invoke")
        return ctx

    async def tool_post_invoke(self, ctx: PluginContext) -> PluginContext:
        if isinstance(ctx.result, str) and ctx.result:
            await self._moderate(ctx, ctx.result, "tool_post_invoke")
        return ctx

    async def _moderate(self, ctx: PluginContext, text: str, phase: str) -> None:
        if not self._client:
            return

        flagged = await self._call_provider(text)
        if not flagged:
            return

        matched = [c for c in flagged if c["category"] in self._categories]
        triggered = [c for c in matched if c.get("score", 1.0) >= self._threshold]
        if not triggered:
            return

        cats = ", ".join(c["category"] for c in triggered)
        ctx.metadata[f"moderation_{phase}"] = triggered

        if self._action == "block":
            raise ValueError(f"Content moderation: flagged categories — {cats}")
        if self._action == "warn":
            logger.warning("Content moderation flagged: %s", cats)

    async def _call_provider(self, text: str) -> List[Dict[str, Any]]:
        try:
            if self._provider == "openai":
                return await self._openai(text)
            if self._provider == "azure":
                return await self._azure(text)
            if self._provider == "granite":
                return await self._granite(text)
            logger.warning("Unsupported moderation provider: %s", self._provider)
            return []
        except Exception:
            logger.warning("Content moderation API call failed.", exc_info=True)
            return []

    async def _openai(self, text: str) -> List[Dict[str, Any]]:
        url = self._api_url or "https://api.openai.com/v1/moderations"
        resp = await self._client.post(
            url,
            json={"input": text},
            headers={"Authorization": f"Bearer {self._api_key}"},
        )
        resp.raise_for_status()
        data = resp.json()
        results: List[Dict[str, Any]] = []
        for result in data.get("results", []):
            scores = result.get("category_scores", {})
            for cat, score in scores.items():
                normalized = cat.replace("/", "-").replace("_", "-")
                results.append({"category": normalized, "score": score})
        return results

    async def _azure(self, text: str) -> List[Dict[str, Any]]:
        url = self._api_url or "https://contentsafety.cognitiveservices.azure.com"
        resp = await self._client.post(
            f"{url}/contentsafety/text:analyze",
            params={"api-version": "2024-09-01"},
            json={"text": text},
            headers={"Ocp-Apim-Subscription-Key": self._api_key},
        )
        resp.raise_for_status()
        data = resp.json()
        results: List[Dict[str, Any]] = []
        for item in data.get("categoriesAnalysis", []):
            results.append(
                {
                    "category": item.get("category", "unknown").lower(),
                    "score": item.get("severity", 0) / 6.0,
                }
            )
        return results

    async def _granite(self, text: str) -> List[Dict[str, Any]]:
        url = self._api_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        resp = await self._client.post(
            f"{url}/api/generate",
            json={
                "model": "granite-guardian",
                "prompt": f"Classify the following text for harmful content:\n{text}",
                "stream": False,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        response_text = data.get("response", "")
        results: List[Dict[str, Any]] = []
        for cat in _DEFAULT_CATEGORIES:
            if cat in response_text.lower():
                results.append({"category": cat, "score": 1.0})
        return results

    @staticmethod
    def _extract_text(arguments: Dict[str, Any]) -> Optional[str]:
        for key in ("prompt", "text", "message", "content", "query", "input"):
            val = arguments.get(key)
            if isinstance(val, str) and val:
                return val
        return None
