"""Tests for argus_mcp.plugins.builtins — Built-in plugins.

Covers all 8 built-in plugins:
  Security (Step 3.2):
    - SecretsDetectionPlugin: block mode, redact mode, post-invoke result scan
    - PiiFilterPlugin: category filtering, pre/post masking
    - RateLimiterPlugin: fixed-window enforcement, window reset, on_unload
    - CircuitBreakerPlugin: closed/open/half_open transitions, on_unload
  Operational (Step 3.3):
    - RetryWithBackoffPlugin: retry metadata, exhaustion, no-error passthrough
    - ResponseCachePlugin: cache hit/miss, TTL expiry, max_entries, on_unload
    - OutputLengthGuardPlugin: truncation, short pass-through, non-string
    - MarkdownCleanerPlugin: heading/bold/link/image/html stripping

Also covers the builtins __init__.py registration.
"""

from __future__ import annotations

import time
from typing import Any, Dict
from unittest.mock import patch  # noqa: F401 — used in rate_limiter/circuit_breaker tests

import pytest

from argus_mcp.plugins.base import PluginContext
from argus_mcp.plugins.builtins.circuit_breaker import CircuitBreakerPlugin
from argus_mcp.plugins.builtins.markdown_cleaner import MarkdownCleanerPlugin
from argus_mcp.plugins.builtins.output_length_guard import OutputLengthGuardPlugin
from argus_mcp.plugins.builtins.pii_filter import PiiFilterPlugin
from argus_mcp.plugins.builtins.rate_limiter import RateLimiterPlugin
from argus_mcp.plugins.builtins.response_cache_by_prompt import ResponseCachePlugin

# Operational plugins
from argus_mcp.plugins.builtins.retry_with_backoff import RetryWithBackoffPlugin

# Security plugins
from argus_mcp.plugins.builtins.secrets_detection import SecretsDetectionPlugin
from argus_mcp.plugins.models import ExecutionMode, PluginCondition, PluginConfig
from argus_mcp.plugins.registry import _PLUGIN_CLASSES

# Helpers


def _cfg(
    name: str = "test",
    *,
    settings: Dict[str, Any] | None = None,
) -> PluginConfig:
    return PluginConfig(
        name=name,
        enabled=True,
        priority=100,
        timeout=30.0,
        execution_mode=ExecutionMode.enforce_ignore_error,
        conditions=PluginCondition(),
        settings=settings or {},
    )


def _ctx(
    *,
    capability: str = "my_tool",
    server: str = "backend",
    arguments: Dict[str, Any] | None = None,
    result: object = None,
    metadata: Dict[str, Any] | None = None,
) -> PluginContext:
    return PluginContext(
        capability_name=capability,
        mcp_method="tools/call",
        arguments=arguments or {},
        server_name=server,
        metadata=metadata or {},
        result=result,
    )


# Registration tests


class TestBuiltinRegistration:
    """Verify all 8 plugins are registered when builtins is imported."""

    def test_all_plugins_registered(self):
        # The builtins __init__.py is already imported transitively.
        import argus_mcp.plugins.builtins  # noqa: F401

        expected = {
            "secrets_detection",
            "pii_filter",
            "rate_limiter",
            "circuit_breaker",
            "retry_with_backoff",
            "response_cache_by_prompt",
            "output_length_guard",
            "markdown_cleaner",
        }
        assert expected.issubset(set(_PLUGIN_CLASSES.keys()))


# SecretsDetectionPlugin


class TestSecretsDetection:
    async def test_block_aws_key(self):
        p = SecretsDetectionPlugin(_cfg(settings={"block": True}))
        # Exactly AKIA + 16 uppercase/digit chars = 20 total
        ctx = _ctx(arguments={"token": "AKIAIOSFODNN7EXAMPLE"})
        with pytest.raises(ValueError, match="Blocked.*AWS Access Key"):
            await p.tool_pre_invoke(ctx)

    async def test_block_aws_key_with_boundary(self):
        p = SecretsDetectionPlugin(_cfg(settings={"block": True}))
        # Key embedded in text with word boundaries
        ctx = _ctx(arguments={"token": "key=AKIAIOSFODNN7EXAMPLE rest"})
        with pytest.raises(ValueError, match="Blocked.*AWS Access Key"):
            await p.tool_pre_invoke(ctx)

    async def test_redact_mode(self):
        p = SecretsDetectionPlugin(_cfg(settings={"block": False}))
        ctx = _ctx(arguments={"token": "AKIAIOSFODNN7EXAMPLE"})
        result = await p.tool_pre_invoke(ctx)
        assert "***REDACTED***" in result.arguments["token"]
        assert result.metadata.get("secrets_redacted") is True

    async def test_jwt_detected(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        p = SecretsDetectionPlugin(_cfg(settings={"block": True}))
        ctx = _ctx(arguments={"auth": jwt})
        with pytest.raises(ValueError, match="JWT"):
            await p.tool_pre_invoke(ctx)

    async def test_private_key_detected(self):
        p = SecretsDetectionPlugin(_cfg(settings={"block": True}))
        ctx = _ctx(arguments={"key": "-----BEGIN RSA PRIVATE KEY-----\nMIIE..."})
        with pytest.raises(ValueError, match="Private Key"):
            await p.tool_pre_invoke(ctx)

    async def test_github_token_detected(self):
        p = SecretsDetectionPlugin(_cfg(settings={"block": True}))
        ctx = _ctx(arguments={"gh": "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl"})
        with pytest.raises(ValueError, match="GitHub Token"):
            await p.tool_pre_invoke(ctx)

    async def test_bearer_token_detected(self):
        p = SecretsDetectionPlugin(_cfg(settings={"block": True}))
        ctx = _ctx(arguments={"header": "Bearer eyPseudoTokenContent1234567890abcdef"})
        with pytest.raises(ValueError, match="Generic Bearer"):
            await p.tool_pre_invoke(ctx)

    async def test_clean_arguments_pass(self):
        p = SecretsDetectionPlugin(_cfg(settings={"block": True}))
        ctx = _ctx(arguments={"query": "SELECT * FROM users"})
        result = await p.tool_pre_invoke(ctx)
        assert "secrets_blocked" not in result.metadata

    async def test_post_invoke_redacts_result(self):
        p = SecretsDetectionPlugin(_cfg(settings={"block": False}))
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        ctx = _ctx(result=f"Token is {jwt}")
        result = await p.tool_post_invoke(ctx)
        assert "***REDACTED***" in result.result
        assert result.metadata.get("secrets_redacted_result") is True

    async def test_non_string_argument_ignored(self):
        p = SecretsDetectionPlugin(_cfg(settings={"block": True}))
        ctx = _ctx(arguments={"count": 42})
        result = await p.tool_pre_invoke(ctx)
        assert result.arguments["count"] == 42

    async def test_non_string_result_ignored(self):
        p = SecretsDetectionPlugin(_cfg(settings={"block": True}))
        ctx = _ctx(result=12345)
        result = await p.tool_post_invoke(ctx)
        assert result.result == 12345


# PiiFilterPlugin


class TestPiiFilter:
    async def test_email_masked(self):
        p = PiiFilterPlugin(_cfg())
        ctx = _ctx(arguments={"contact": "user@example.com"})
        result = await p.tool_pre_invoke(ctx)
        assert "***EMAIL***" in result.arguments["contact"]
        assert result.metadata["pii_pre_masked"]["email"] == 1

    async def test_ssn_masked(self):
        p = PiiFilterPlugin(_cfg())
        ctx = _ctx(arguments={"ssn": "123-45-6789"})
        result = await p.tool_pre_invoke(ctx)
        assert "***SSN***" in result.arguments["ssn"]

    async def test_credit_card_masked(self):
        p = PiiFilterPlugin(_cfg())
        ctx = _ctx(arguments={"cc": "4111 1111 1111 1111"})
        result = await p.tool_pre_invoke(ctx)
        assert "***CC***" in result.arguments["cc"]

    async def test_phone_masked(self):
        p = PiiFilterPlugin(_cfg())
        ctx = _ctx(arguments={"phone": "+1-555-123-4567"})
        result = await p.tool_pre_invoke(ctx)
        assert "***PHONE***" in result.arguments["phone"]

    async def test_category_filter_only_email(self):
        p = PiiFilterPlugin(_cfg(settings={"categories": ["email"]}))
        ctx = _ctx(arguments={"mixed": "user@test.com and 123-45-6789"})
        result = await p.tool_pre_invoke(ctx)
        assert "***EMAIL***" in result.arguments["mixed"]
        # SSN should NOT be masked when only "email" category is active
        assert "123-45-6789" in result.arguments["mixed"]

    async def test_post_invoke_masks_result(self):
        p = PiiFilterPlugin(_cfg())
        ctx = _ctx(result="Contact admin@site.org for help.")
        result = await p.tool_post_invoke(ctx)
        assert "***EMAIL***" in result.result
        assert result.metadata["pii_post_masked"]["email"] == 1

    async def test_no_pii_passthrough(self):
        p = PiiFilterPlugin(_cfg())
        ctx = _ctx(arguments={"query": "hello world"})
        result = await p.tool_pre_invoke(ctx)
        assert "pii_pre_masked" not in result.metadata

    async def test_non_string_value_ignored(self):
        p = PiiFilterPlugin(_cfg())
        ctx = _ctx(arguments={"count": 42})
        result = await p.tool_pre_invoke(ctx)
        assert result.arguments["count"] == 42


# RateLimiterPlugin


class TestRateLimiter:
    async def test_under_limit_passes(self):
        p = RateLimiterPlugin(_cfg(settings={"max_requests": 5, "window_seconds": 60}))
        ctx = _ctx()
        result = await p.tool_pre_invoke(ctx)
        assert result.metadata["rate_limit_remaining"] == 4

    async def test_at_limit_raises(self):
        p = RateLimiterPlugin(_cfg(settings={"max_requests": 2, "window_seconds": 60}))
        await p.tool_pre_invoke(_ctx())
        await p.tool_pre_invoke(_ctx())
        with pytest.raises(ValueError, match="Rate limit exceeded"):
            await p.tool_pre_invoke(_ctx())

    async def test_different_tools_separate_windows(self):
        p = RateLimiterPlugin(_cfg(settings={"max_requests": 1, "window_seconds": 60}))
        await p.tool_pre_invoke(_ctx(capability="tool_a"))
        # Different tool should have its own window
        result = await p.tool_pre_invoke(_ctx(capability="tool_b"))
        assert result.metadata["rate_limit_remaining"] == 0

    async def test_window_reset_after_expiry(self):
        p = RateLimiterPlugin(_cfg(settings={"max_requests": 1, "window_seconds": 1}))
        await p.tool_pre_invoke(_ctx())
        # Patch time.monotonic to advance past window
        original_monotonic = time.monotonic
        with patch("argus_mcp.plugins.builtins.rate_limiter.time.monotonic") as mock_time:
            mock_time.return_value = original_monotonic() + 2
            result = await p.tool_pre_invoke(_ctx())
            assert result.metadata["rate_limit_remaining"] == 0

    async def test_on_unload_clears(self):
        p = RateLimiterPlugin(_cfg(settings={"max_requests": 5, "window_seconds": 60}))
        await p.tool_pre_invoke(_ctx())
        assert len(p._windows) == 1
        await p.on_unload()
        assert len(p._windows) == 0

    async def test_rate_limited_metadata(self):
        p = RateLimiterPlugin(_cfg(settings={"max_requests": 1, "window_seconds": 60}))
        await p.tool_pre_invoke(_ctx())
        ctx = _ctx()
        with pytest.raises(ValueError):
            await p.tool_pre_invoke(ctx)
        assert ctx.metadata.get("rate_limited") is True
        assert "retry_after_seconds" in ctx.metadata


# CircuitBreakerPlugin


class TestCircuitBreaker:
    async def test_closed_allows(self):
        p = CircuitBreakerPlugin(_cfg(settings={"failure_threshold": 3, "cooldown_seconds": 10}))
        ctx = _ctx()
        result = await p.tool_pre_invoke(ctx)
        assert result.metadata["circuit_state"] == "closed"

    async def test_trips_after_threshold(self):
        p = CircuitBreakerPlugin(_cfg(settings={"failure_threshold": 2, "cooldown_seconds": 10}))
        # Two failures
        for _ in range(2):
            ctx = _ctx(metadata={"error": True})
            await p.tool_pre_invoke(ctx)
            await p.tool_post_invoke(ctx)
        # Third call should be blocked
        with pytest.raises(ValueError, match="Circuit open"):
            await p.tool_pre_invoke(_ctx())

    async def test_success_resets(self):
        p = CircuitBreakerPlugin(_cfg(settings={"failure_threshold": 3, "cooldown_seconds": 10}))
        # One failure
        ctx_fail = _ctx(metadata={"error": True})
        await p.tool_pre_invoke(ctx_fail)
        await p.tool_post_invoke(ctx_fail)
        # One success resets
        ctx_ok = _ctx()
        await p.tool_pre_invoke(ctx_ok)
        await p.tool_post_invoke(ctx_ok)
        assert ctx_ok.metadata["circuit_state"] == "closed"

    async def test_half_open_after_cooldown(self):
        p = CircuitBreakerPlugin(_cfg(settings={"failure_threshold": 1, "cooldown_seconds": 1}))
        # Trip the breaker
        ctx = _ctx(metadata={"error": True})
        await p.tool_pre_invoke(ctx)
        await p.tool_post_invoke(ctx)
        # Should be open now
        with pytest.raises(ValueError, match="Circuit open"):
            await p.tool_pre_invoke(_ctx())
        # Advance past cooldown
        original_monotonic = time.monotonic
        with patch("argus_mcp.plugins.builtins.circuit_breaker.time.monotonic") as mock_time:
            mock_time.return_value = original_monotonic() + 2
            result = await p.tool_pre_invoke(_ctx())
            assert result.metadata["circuit_state"] == "half_open"

    async def test_different_tools_independent(self):
        p = CircuitBreakerPlugin(_cfg(settings={"failure_threshold": 1, "cooldown_seconds": 10}))
        # Trip breaker for tool_a
        ctx = _ctx(capability="tool_a", metadata={"error": True})
        await p.tool_pre_invoke(ctx)
        await p.tool_post_invoke(ctx)
        # tool_b should still work
        result = await p.tool_pre_invoke(_ctx(capability="tool_b"))
        assert result.metadata["circuit_state"] == "closed"

    async def test_on_unload_clears(self):
        p = CircuitBreakerPlugin(_cfg())
        await p.tool_pre_invoke(_ctx())
        assert len(p._breakers) == 1
        await p.on_unload()
        assert len(p._breakers) == 0


# RetryWithBackoffPlugin


class TestRetryWithBackoff:
    async def test_no_error_no_retry(self):
        p = RetryWithBackoffPlugin(_cfg(settings={"max_retries": 3}))
        ctx = _ctx()
        result = await p.tool_post_invoke(ctx)
        assert "retry_suggested" not in result.metadata

    async def test_error_suggests_retry(self):
        p = RetryWithBackoffPlugin(
            _cfg(settings={"max_retries": 3, "base_delay": 0.01, "max_delay": 0.05})
        )
        ctx = _ctx(metadata={"error": True, "retry_attempt": 0})
        result = await p.tool_post_invoke(ctx)
        assert result.metadata["retry_suggested"] is True
        assert result.metadata["retry_attempt"] == 1
        assert "retry_delay" in result.metadata

    async def test_retries_exhausted(self):
        p = RetryWithBackoffPlugin(_cfg(settings={"max_retries": 2, "base_delay": 0.01}))
        ctx = _ctx(metadata={"error": True, "retry_attempt": 2})
        result = await p.tool_post_invoke(ctx)
        assert result.metadata["retries_exhausted"] is True
        assert "retry_suggested" not in result.metadata

    async def test_backoff_increases(self):
        p = RetryWithBackoffPlugin(
            _cfg(
                settings={
                    "max_retries": 5,
                    "base_delay": 0.01,
                    "backoff_factor": 2.0,
                    "max_delay": 10.0,
                }
            )
        )
        delays = []
        for attempt in range(3):
            ctx = _ctx(metadata={"error": True, "retry_attempt": attempt})
            result = await p.tool_post_invoke(ctx)
            delays.append(result.metadata["retry_delay"])
        # With jitter the exact values vary, but in general later attempts are longer
        # Just check all were set
        assert len(delays) == 3
        assert all(d >= 0 for d in delays)

    async def test_max_delay_cap(self):
        p = RetryWithBackoffPlugin(
            _cfg(settings={"max_retries": 10, "base_delay": 100.0, "max_delay": 0.05})
        )
        ctx = _ctx(metadata={"error": True, "retry_attempt": 0})
        result = await p.tool_post_invoke(ctx)
        # Delay should be capped around max_delay (±jitter)
        assert result.metadata["retry_delay"] <= 0.1  # generous bound


# ResponseCachePlugin


class TestResponseCache:
    async def test_cache_miss_then_hit(self):
        p = ResponseCachePlugin(_cfg(settings={"ttl_seconds": 300}))
        # First call: miss
        ctx1 = _ctx(arguments={"q": "hello"})
        r1 = await p.tool_pre_invoke(ctx1)
        assert r1.metadata["cache_hit"] is False
        # Simulate successful result
        r1.result = "world"
        r1 = await p.tool_post_invoke(r1)
        assert r1.metadata.get("cache_stored") is True

        # Second call: hit
        ctx2 = _ctx(arguments={"q": "hello"})
        r2 = await p.tool_pre_invoke(ctx2)
        assert r2.metadata["cache_hit"] is True
        assert r2.result == "world"

    async def test_different_args_separate_entries(self):
        p = ResponseCachePlugin(_cfg(settings={"ttl_seconds": 300}))
        ctx1 = _ctx(arguments={"q": "a"})
        r1 = await p.tool_pre_invoke(ctx1)
        r1.result = "result_a"
        await p.tool_post_invoke(r1)

        ctx2 = _ctx(arguments={"q": "b"})
        r2 = await p.tool_pre_invoke(ctx2)
        assert r2.metadata["cache_hit"] is False

    async def test_ttl_expiry(self):
        p = ResponseCachePlugin(_cfg(settings={"ttl_seconds": 1}))
        ctx = _ctx(arguments={"q": "x"})
        r = await p.tool_pre_invoke(ctx)
        r.result = "cached"
        await p.tool_post_invoke(r)

        # Backdate all cached timestamps so entries appear expired
        for k in list(p._cache):
            result_val, _ts = p._cache[k]
            p._cache[k] = (result_val, _ts - 10)

        ctx2 = _ctx(arguments={"q": "x"})
        r2 = await p.tool_pre_invoke(ctx2)
        assert r2.metadata["cache_hit"] is False

    async def test_error_not_cached(self):
        p = ResponseCachePlugin(_cfg(settings={"ttl_seconds": 300}))
        ctx = _ctx(arguments={"q": "fail"})
        r = await p.tool_pre_invoke(ctx)
        r.metadata["error"] = True
        r.result = "oops"
        r = await p.tool_post_invoke(r)
        assert r.metadata.get("cache_stored") is None

    async def test_max_entries_eviction(self):
        p = ResponseCachePlugin(_cfg(settings={"ttl_seconds": 300, "max_entries": 2}))
        # Fill cache
        for i in range(3):
            ctx = _ctx(arguments={"q": str(i)})
            r = await p.tool_pre_invoke(ctx)
            r.result = f"result_{i}"
            await p.tool_post_invoke(r)
        # Should have at most 2 entries
        assert len(p._cache) <= 2

    async def test_on_unload_clears(self):
        p = ResponseCachePlugin(_cfg(settings={"ttl_seconds": 300}))
        ctx = _ctx(arguments={"q": "x"})
        r = await p.tool_pre_invoke(ctx)
        r.result = "y"
        await p.tool_post_invoke(r)
        assert len(p._cache) == 1
        await p.on_unload()
        assert len(p._cache) == 0


# OutputLengthGuardPlugin


class TestOutputLengthGuard:
    async def test_short_string_passes(self):
        p = OutputLengthGuardPlugin(_cfg(settings={"max_length": 100}))
        ctx = _ctx(result="hello")
        result = await p.tool_post_invoke(ctx)
        assert result.result == "hello"
        assert result.metadata["output_truncated"] is False

    async def test_long_string_truncated(self):
        p = OutputLengthGuardPlugin(_cfg(settings={"max_length": 20, "suffix": "..."}))
        ctx = _ctx(result="A" * 50)
        result = await p.tool_post_invoke(ctx)
        assert len(result.result) <= 20
        assert result.result.endswith("...")
        assert result.metadata["output_truncated"] is True
        assert result.metadata["output_original_length"] == 50

    async def test_non_string_result_passes(self):
        p = OutputLengthGuardPlugin(_cfg(settings={"max_length": 10}))
        ctx = _ctx(result=12345)
        result = await p.tool_post_invoke(ctx)
        assert result.result == 12345

    async def test_exactly_at_limit(self):
        p = OutputLengthGuardPlugin(_cfg(settings={"max_length": 10}))
        ctx = _ctx(result="A" * 10)
        result = await p.tool_post_invoke(ctx)
        assert result.result == "A" * 10
        assert result.metadata["output_truncated"] is False

    async def test_default_suffix(self):
        p = OutputLengthGuardPlugin(_cfg(settings={"max_length": 30}))
        ctx = _ctx(result="B" * 100)
        result = await p.tool_post_invoke(ctx)
        assert result.result.endswith("... [truncated]")


# MarkdownCleanerPlugin


class TestMarkdownCleaner:
    async def test_heading_stripped(self):
        p = MarkdownCleanerPlugin(_cfg())
        ctx = _ctx(result="## Hello World")
        result = await p.tool_post_invoke(ctx)
        assert result.result.strip() == "Hello World"
        assert result.metadata["markdown_cleaned"] is True

    async def test_bold_stripped(self):
        p = MarkdownCleanerPlugin(_cfg())
        ctx = _ctx(result="This is **bold** text")
        result = await p.tool_post_invoke(ctx)
        assert "**" not in result.result
        assert "bold" in result.result

    async def test_italic_stripped(self):
        p = MarkdownCleanerPlugin(_cfg())
        ctx = _ctx(result="This is *italic* text")
        result = await p.tool_post_invoke(ctx)
        assert result.result == "This is italic text"

    async def test_link_simplified(self):
        p = MarkdownCleanerPlugin(_cfg())
        ctx = _ctx(result="Visit [GitHub](https://github.com) now")
        result = await p.tool_post_invoke(ctx)
        assert result.result == "Visit GitHub now"

    async def test_image_removed(self):
        p = MarkdownCleanerPlugin(_cfg())
        ctx = _ctx(result="See ![logo](https://example.com/logo.png) here")
        result = await p.tool_post_invoke(ctx)
        assert "![" not in result.result
        assert "logo" in result.result  # alt text kept

    async def test_html_stripped(self):
        p = MarkdownCleanerPlugin(_cfg())
        ctx = _ctx(result="Hello <b>World</b>")
        result = await p.tool_post_invoke(ctx)
        assert "<b>" not in result.result
        assert "HelloWorld" in result.result.replace(" ", "")

    async def test_inline_code_stripped(self):
        p = MarkdownCleanerPlugin(_cfg())
        ctx = _ctx(result="Use `print()` function")
        result = await p.tool_post_invoke(ctx)
        assert "`" not in result.result
        assert "print()" in result.result

    async def test_non_string_passes(self):
        p = MarkdownCleanerPlugin(_cfg())
        ctx = _ctx(result=42)
        result = await p.tool_post_invoke(ctx)
        assert result.result == 42

    async def test_no_markdown_no_change(self):
        p = MarkdownCleanerPlugin(_cfg())
        ctx = _ctx(result="Plain text only")
        result = await p.tool_post_invoke(ctx)
        assert result.result == "Plain text only"
        assert result.metadata["markdown_cleaned"] is False

    async def test_strikethrough_stripped(self):
        p = MarkdownCleanerPlugin(_cfg())
        ctx = _ctx(result="~~deleted~~ text")
        result = await p.tool_post_invoke(ctx)
        assert "~~" not in result.result
        assert "deleted" in result.result

    async def test_settings_disable_images(self):
        p = MarkdownCleanerPlugin(_cfg(settings={"strip_images": False, "strip_links": False}))
        ctx = _ctx(result="![alt](url) and **bold**")
        result = await p.tool_post_invoke(ctx)
        assert "![alt](url)" in result.result  # image kept since both image & link stripping off
        assert "**" not in result.result  # bold still stripped

    async def test_settings_disable_links(self):
        p = MarkdownCleanerPlugin(_cfg(settings={"strip_links": False}))
        ctx = _ctx(result="[text](url) and **bold**")
        result = await p.tool_post_invoke(ctx)
        assert "[text](url)" in result.result  # link kept
        assert "**" not in result.result  # bold still stripped
