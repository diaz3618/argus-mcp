"""VirusTotal plugin — URL, domain, IP, and file reputation checking.

Queries the VirusTotal v3 API to check URLs and domains found in tool
results and resource URIs.  Maintains an in-memory TTL cache to avoid
redundant lookups.

Settings (in ``config.settings``):
    api_key:      VT API key (falls back to ``VT_API_KEY`` env var)
    threshold:    Min detections to consider malicious (default ``3``)
    cache_ttl:    Cache TTL in seconds (default ``300``)
    allow_list:   List of domains/URLs to skip scanning
    deny_list:    List of domains/URLs to always block
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Set

from argus_mcp.plugins.base import PluginBase, PluginContext
from argus_mcp.plugins.models import PluginConfig

logger = logging.getLogger(__name__)

_URL_PATTERN = re.compile(
    r"https?://[^\s\"'<>\]\)}{,]+",
    re.IGNORECASE,
)


class VirusTotalPlugin(PluginBase):
    """URL/file reputation checking via VirusTotal v3 API."""

    def __init__(self, config: PluginConfig) -> None:
        super().__init__(config)
        self._api_key: str = config.settings.get(
            "api_key",
            os.environ.get("VT_API_KEY", ""),
        )
        self._threshold: int = int(config.settings.get("threshold", 3))
        self._cache_ttl: int = int(config.settings.get("cache_ttl", 300))
        self._allow_list: Set[str] = set(config.settings.get("allow_list", []))
        self._deny_list: Set[str] = set(config.settings.get("deny_list", []))
        self._client: Any = None
        self._cache: Dict[str, tuple[float, int]] = {}

    async def on_load(self) -> None:
        if not self._api_key:
            logger.warning("VirusTotal plugin: no API key configured.")
            return
        import httpx

        self._client = httpx.AsyncClient(
            base_url="https://www.virustotal.com/api/v3",
            headers={"x-apikey": self._api_key},
            timeout=httpx.Timeout(connect=5.0, read=30.0, write=5.0, pool=5.0),
        )

    async def on_unload(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def resource_pre_fetch(self, ctx: PluginContext) -> PluginContext:
        uri = ctx.arguments.get("uri", "")
        if isinstance(uri, str) and uri.startswith("http"):
            await self._check_url(ctx, uri, "resource_pre_fetch")
        return ctx

    async def resource_post_fetch(self, ctx: PluginContext) -> PluginContext:
        if isinstance(ctx.result, str):
            urls = _URL_PATTERN.findall(ctx.result)
            for url in urls[:10]:
                await self._check_url(ctx, url, "resource_post_fetch")
        return ctx

    async def tool_post_invoke(self, ctx: PluginContext) -> PluginContext:
        if isinstance(ctx.result, str):
            urls = _URL_PATTERN.findall(ctx.result)
            for url in urls[:10]:
                await self._check_url(ctx, url, "tool_post_invoke")
        return ctx

    async def _check_url(
        self,
        ctx: PluginContext,
        url: str,
        phase: str,
    ) -> None:
        domain = self._extract_domain(url)
        if domain in self._allow_list or url in self._allow_list:
            return
        if domain in self._deny_list or url in self._deny_list:
            ctx.metadata[f"vt_blocked_{phase}"] = url
            raise ValueError(f"VirusTotal: URL on deny list: {domain}")

        detections = await self._lookup(url)
        if detections is None:
            return

        if detections >= self._threshold:
            ctx.metadata[f"vt_malicious_{phase}"] = {
                "url": url,
                "detections": detections,
            }
            raise ValueError(
                f"VirusTotal: {detections} detections for {domain} (threshold={self._threshold})"
            )

    async def _lookup(self, url: str) -> Optional[int]:
        cached = self._cache.get(url)
        if cached:
            ts, detections = cached
            if time.monotonic() - ts < self._cache_ttl:
                return detections

        if not self._client:
            return None

        try:
            import base64

            url_id = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
            resp = await self._client.get(f"/urls/{url_id}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            data = resp.json()
            stats = data.get("data", {}).get("attributes", {}).get("last_analysis_stats", {})
            detections = int(stats.get("malicious", 0))
            self._cache[url] = (time.monotonic(), detections)
            return detections
        except Exception:
            logger.warning("VirusTotal API request failed for URL scan.")
            return None

    @staticmethod
    def _extract_domain(url: str) -> str:
        try:
            from urllib.parse import urlparse

            return urlparse(url).netloc.lower()
        except Exception:
            return ""

    def _get_cached_urls(self) -> List[str]:
        now = time.monotonic()
        return [url for url, (ts, _) in self._cache.items() if now - ts < self._cache_ttl]
