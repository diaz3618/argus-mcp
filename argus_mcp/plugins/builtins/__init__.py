"""Built-in plugins for Argus MCP.

Security tier: secrets_detection, pii_filter, rate_limiter, circuit_breaker
Operational tier: retry_with_backoff, response_cache_by_prompt,
                  output_length_guard, markdown_cleaner
"""

from __future__ import annotations

from argus_mcp.plugins.registry import register_plugin

from .circuit_breaker import CircuitBreakerPlugin
from .markdown_cleaner import MarkdownCleanerPlugin
from .output_length_guard import OutputLengthGuardPlugin
from .pii_filter import PiiFilterPlugin
from .rate_limiter import RateLimiterPlugin
from .response_cache_by_prompt import ResponseCachePlugin
from .retry_with_backoff import RetryWithBackoffPlugin
from .secrets_detection import SecretsDetectionPlugin

# ---- Security plugins ----
register_plugin("secrets_detection", SecretsDetectionPlugin)
register_plugin("pii_filter", PiiFilterPlugin)
register_plugin("rate_limiter", RateLimiterPlugin)
register_plugin("circuit_breaker", CircuitBreakerPlugin)

# ---- Operational plugins ----
register_plugin("retry_with_backoff", RetryWithBackoffPlugin)
register_plugin("response_cache_by_prompt", ResponseCachePlugin)
register_plugin("output_length_guard", OutputLengthGuardPlugin)
register_plugin("markdown_cleaner", MarkdownCleanerPlugin)

__all__ = [
    "CircuitBreakerPlugin",
    "MarkdownCleanerPlugin",
    "OutputLengthGuardPlugin",
    "PiiFilterPlugin",
    "RateLimiterPlugin",
    "ResponseCachePlugin",
    "RetryWithBackoffPlugin",
    "SecretsDetectionPlugin",
]
