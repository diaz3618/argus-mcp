"""Tests for external plugins with mock APIs.

Covers all 7 external plugins:
- LLMGuardPlugin
- VirusTotalPlugin
- CedarPolicyPlugin
- ClamAVPlugin
- OPAPolicyPlugin
- ContentModerationPlugin
- UnifiedPDPPlugin
"""

from __future__ import annotations

from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from argus_mcp.plugins.base import PluginContext
from argus_mcp.plugins.models import PluginConfig


def _make_config(name: str, settings: Dict[str, Any] | None = None) -> PluginConfig:
    return PluginConfig(name=name, settings=settings or {})


def _make_ctx(**kwargs: Any) -> PluginContext:
    defaults = {
        "capability_name": "test_tool",
        "mcp_method": "tools/call",
        "arguments": {},
        "server_name": "test_server",
    }
    defaults.update(kwargs)
    return PluginContext(**defaults)


def _mock_response(json_data: Any, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json=json_data,
        request=httpx.Request("POST", "http://mock"),
    )


# LLMGuard ───────────────────────────────────────────────────


class TestLLMGuardPlugin:
    @pytest.fixture
    def plugin(self):
        from argus_mcp.plugins.external.llmguard import LLMGuardPlugin

        return LLMGuardPlugin(
            _make_config(
                "llmguard", {"api_url": "http://llmguard:8000", "threshold": 0.5, "block": True}
            )
        )

    @pytest.mark.asyncio
    async def test_lifecycle(self, plugin):
        await plugin.on_load()
        assert plugin._client is not None
        await plugin.on_unload()
        assert plugin._client is None

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_safe(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(
            return_value=_mock_response({"is_harmful": False, "score": 0.1, "scanners": {}})
        )
        ctx = _make_ctx(arguments={"prompt": "hello world"})
        result = await plugin.prompt_pre_fetch(ctx)
        assert result is ctx
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_blocked(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(
            return_value=_mock_response(
                {
                    "results": [{"score": 0.9, "scanner_name": "Toxicity"}],
                }
            )
        )
        ctx = _make_ctx(arguments={"prompt": "harmful content"})
        with pytest.raises(ValueError, match="LLMGuard"):
            await plugin.prompt_pre_fetch(ctx)
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_prompt_post_fetch(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(
            return_value=_mock_response({"is_harmful": False, "score": 0.05, "scanners": {}})
        )
        ctx = _make_ctx(result="safe response")
        result = await plugin.prompt_post_fetch(ctx)
        assert result is ctx
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_no_text_skip(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        ctx = _make_ctx(arguments={"other_key": 123})
        result = await plugin.prompt_pre_fetch(ctx)
        assert result is ctx
        plugin._client.post.assert_not_called()
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_no_client_skip(self, plugin):
        ctx = _make_ctx(arguments={"prompt": "test"})
        result = await plugin.prompt_pre_fetch(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_below_threshold(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(
            return_value=_mock_response({"is_harmful": True, "score": 0.3, "scanners": {}})
        )
        ctx = _make_ctx(arguments={"prompt": "borderline"})
        result = await plugin.prompt_pre_fetch(ctx)
        assert result is ctx
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_block_false_logs_instead(self):
        from argus_mcp.plugins.external.llmguard import LLMGuardPlugin

        p = LLMGuardPlugin(
            _make_config("llmguard", {"api_url": "http://x", "threshold": 0.5, "block": False})
        )
        await p.on_load()
        p._client = AsyncMock()
        p._client.post = AsyncMock(
            return_value=_mock_response(
                {"is_harmful": True, "score": 0.9, "scanners": {"Toxicity": 0.9}}
            )
        )
        ctx = _make_ctx(arguments={"prompt": "harmful"})
        result = await p.prompt_pre_fetch(ctx)
        assert result is ctx
        await p.on_unload()

    @pytest.mark.asyncio
    async def test_extract_text_keys(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(
            return_value=_mock_response({"is_harmful": False, "score": 0.0, "scanners": {}})
        )
        for key in ("text", "message", "content", "query"):
            ctx = _make_ctx(arguments={key: "hello"})
            await plugin.prompt_pre_fetch(ctx)
        assert plugin._client.post.call_count == 4
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_api_error_handled(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(side_effect=httpx.ConnectError("down"))
        ctx = _make_ctx(arguments={"prompt": "test"})
        result = await plugin.prompt_pre_fetch(ctx)
        assert result is ctx
        await plugin.on_unload()


# VirusTotal ──────────────────────────────────────────────────


class TestVirusTotalPlugin:
    @pytest.fixture
    def plugin(self):
        from argus_mcp.plugins.external.virustotal import VirusTotalPlugin

        return VirusTotalPlugin(_make_config("virustotal", {"api_key": "test-key", "threshold": 3}))

    @pytest.mark.asyncio
    async def test_lifecycle(self, plugin):
        await plugin.on_load()
        assert plugin._client is not None
        await plugin.on_unload()
        assert plugin._client is None

    @pytest.mark.asyncio
    async def test_resource_pre_fetch_safe_url(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.get = AsyncMock(
            return_value=_mock_response(
                {"data": {"attributes": {"last_analysis_stats": {"malicious": 0, "suspicious": 1}}}}
            )
        )
        ctx = _make_ctx(arguments={"uri": "https://example.com/file.txt"})
        result = await plugin.resource_pre_fetch(ctx)
        assert result is ctx
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_resource_pre_fetch_malicious(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.get = AsyncMock(
            return_value=_mock_response(
                {"data": {"attributes": {"last_analysis_stats": {"malicious": 5, "suspicious": 2}}}}
            )
        )
        ctx = _make_ctx(arguments={"uri": "https://malware.example.com"})
        with pytest.raises(ValueError, match="VirusTotal"):
            await plugin.resource_pre_fetch(ctx)
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_no_urls_skips(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        ctx = _make_ctx(arguments={"data": "no urls here"})
        result = await plugin.resource_pre_fetch(ctx)
        assert result is ctx
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_tool_post_invoke_scan(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.get = AsyncMock(
            return_value=_mock_response(
                {"data": {"attributes": {"last_analysis_stats": {"malicious": 0, "suspicious": 0}}}}
            )
        )
        ctx = _make_ctx(result="Visit https://safe.example.com for details")
        result = await plugin.tool_post_invoke(ctx)
        assert result is ctx
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_resource_post_fetch(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.get = AsyncMock(
            return_value=_mock_response(
                {"data": {"attributes": {"last_analysis_stats": {"malicious": 0, "suspicious": 0}}}}
            )
        )
        ctx = _make_ctx(result="Content from https://safe.example.com")
        result = await plugin.resource_post_fetch(ctx)
        assert result is ctx
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_cache_hit(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.get = AsyncMock(
            return_value=_mock_response(
                {"data": {"attributes": {"last_analysis_stats": {"malicious": 0, "suspicious": 0}}}}
            )
        )
        ctx = _make_ctx(arguments={"uri": "https://cached.example.com"})
        await plugin.resource_pre_fetch(ctx)
        await plugin.resource_pre_fetch(_make_ctx(arguments={"uri": "https://cached.example.com"}))
        assert plugin._client.get.call_count == 1
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_deny_list(self):
        from argus_mcp.plugins.external.virustotal import VirusTotalPlugin

        p = VirusTotalPlugin(
            _make_config(
                "vt",
                {
                    "api_key": "k",
                    "deny_list": ["evil.com"],
                },
            )
        )
        await p.on_load()
        p._client = AsyncMock()
        ctx = _make_ctx(arguments={"uri": "https://evil.com/malware"})
        with pytest.raises(ValueError, match="deny"):
            await p.resource_pre_fetch(ctx)
        await p.on_unload()

    @pytest.mark.asyncio
    async def test_allow_list(self):
        from argus_mcp.plugins.external.virustotal import VirusTotalPlugin

        p = VirusTotalPlugin(
            _make_config(
                "vt",
                {
                    "api_key": "k",
                    "allow_list": ["safe.example.com"],
                },
            )
        )
        await p.on_load()
        p._client = AsyncMock()
        ctx = _make_ctx(arguments={"uri": "https://safe.example.com/file"})
        result = await p.resource_pre_fetch(ctx)
        assert result is ctx
        p._client.get.assert_not_called()
        await p.on_unload()

    @pytest.mark.asyncio
    async def test_api_error_handled(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.get = AsyncMock(side_effect=httpx.ConnectError("down"))
        ctx = _make_ctx(arguments={"uri": "https://example.com"})
        result = await plugin.resource_pre_fetch(ctx)
        assert result is ctx
        await plugin.on_unload()


# Cedar Policy ────────────────────────────────────────────────


class TestCedarPolicyPlugin:
    @pytest.fixture
    def plugin(self):
        from argus_mcp.plugins.external.cedar_policy import CedarPolicyPlugin

        return CedarPolicyPlugin(
            _make_config(
                "cedar",
                {
                    "cedar_url": "http://cedar:8000",
                    "policy_store_id": "ps-test",
                    "api_key": "cedar-key",
                },
            )
        )

    @pytest.mark.asyncio
    async def test_lifecycle(self, plugin):
        await plugin.on_load()
        assert plugin._client is not None
        await plugin.on_unload()
        assert plugin._client is None

    @pytest.mark.asyncio
    async def test_allow(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(return_value=_mock_response({"decision": "ALLOW"}))
        ctx = _make_ctx()
        result = await plugin.tool_pre_invoke(ctx)
        assert result is ctx
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_deny(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(return_value=_mock_response({"decision": "DENY"}))
        ctx = _make_ctx()
        with pytest.raises(ValueError, match="Cedar"):
            await plugin.tool_pre_invoke(ctx)
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_all_hooks(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(return_value=_mock_response({"decision": "ALLOW"}))
        ctx = _make_ctx()
        for hook in (
            plugin.tool_pre_invoke,
            plugin.tool_post_invoke,
            plugin.prompt_pre_fetch,
            plugin.prompt_post_fetch,
            plugin.resource_pre_fetch,
            plugin.resource_post_fetch,
        ):
            result = await hook(ctx)
            assert result is ctx
        assert plugin._client.post.call_count == 6
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_bool_response(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(return_value=_mock_response({"decision": True}))
        ctx = _make_ctx()
        result = await plugin.tool_pre_invoke(ctx)
        assert result is ctx
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_no_client_default_allow(self, plugin):
        ctx = _make_ctx()
        result = await plugin.tool_pre_invoke(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_api_error_default_decision(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(side_effect=httpx.ConnectError("down"))
        ctx = _make_ctx()
        result = await plugin.tool_pre_invoke(ctx)
        assert result is ctx
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_deny_default_false(self):
        from argus_mcp.plugins.external.cedar_policy import CedarPolicyPlugin

        p = CedarPolicyPlugin(
            _make_config(
                "c",
                {
                    "cedar_url": "http://x",
                    "default_decision": False,
                },
            )
        )
        await p.on_load()
        p._client = AsyncMock()
        p._client.post = AsyncMock(side_effect=httpx.ConnectError("down"))
        ctx = _make_ctx()
        with pytest.raises(ValueError, match="Cedar"):
            await p.tool_pre_invoke(ctx)
        await p.on_unload()


# ClamAV ─────────────────────────────────────────────────────


class TestClamAVPlugin:
    @pytest.fixture
    def plugin(self):
        from argus_mcp.plugins.external.clamav import ClamAVPlugin

        return ClamAVPlugin(_make_config("clamav", {"host": "localhost", "port": 3310}))

    @pytest.mark.asyncio
    async def test_on_load_unload(self, plugin):
        await plugin.on_load()
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_resource_pre_fetch_clean(self, plugin):
        data = b"safe file content"
        ctx = _make_ctx(arguments={"content": data})

        async def mock_open_connection(*a, **kw):
            reader = AsyncMock()
            writer = MagicMock()
            writer.write = MagicMock()
            writer.drain = AsyncMock()
            writer.close = MagicMock()
            writer.wait_closed = AsyncMock()
            reader.read = AsyncMock(return_value=b"stream: OK\0")
            return reader, writer

        with patch("asyncio.open_connection", side_effect=mock_open_connection):
            result = await plugin.resource_pre_fetch(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_resource_pre_fetch_virus_found(self, plugin):
        data = b"EICAR test file"
        ctx = _make_ctx(arguments={"content": data})

        async def mock_open_connection(*a, **kw):
            reader = AsyncMock()
            writer = MagicMock()
            writer.write = MagicMock()
            writer.drain = AsyncMock()
            writer.close = MagicMock()
            writer.wait_closed = AsyncMock()
            reader.read = AsyncMock(return_value=b"stream: Eicar-Signature FOUND\0")
            return reader, writer

        with patch("asyncio.open_connection", side_effect=mock_open_connection):
            with pytest.raises(ValueError, match="ClamAV"):
                await plugin.resource_pre_fetch(ctx)

    @pytest.mark.asyncio
    async def test_tool_post_invoke(self, plugin):
        ctx = _make_ctx(result=b"some output data")

        async def mock_open_connection(*a, **kw):
            reader = AsyncMock()
            writer = MagicMock()
            writer.write = MagicMock()
            writer.drain = AsyncMock()
            writer.close = MagicMock()
            writer.wait_closed = AsyncMock()
            reader.read = AsyncMock(return_value=b"stream: OK\0")
            return reader, writer

        with patch("asyncio.open_connection", side_effect=mock_open_connection):
            result = await plugin.tool_post_invoke(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_no_data_skip(self, plugin):
        ctx = _make_ctx(arguments={"text": "not bytes"})
        result = await plugin.resource_pre_fetch(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_connection_error_handled(self, plugin):
        ctx = _make_ctx(arguments={"content": b"test"})

        with patch("asyncio.open_connection", side_effect=OSError("refused")):
            result = await plugin.resource_pre_fetch(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_block_false_logs(self):
        from argus_mcp.plugins.external.clamav import ClamAVPlugin

        p = ClamAVPlugin(_make_config("clamav", {"host": "localhost", "block": False}))

        async def mock_open_connection(*a, **kw):
            reader = AsyncMock()
            writer = MagicMock()
            writer.write = MagicMock()
            writer.drain = AsyncMock()
            writer.close = MagicMock()
            writer.wait_closed = AsyncMock()
            reader.read = AsyncMock(return_value=b"stream: Virus FOUND\0")
            return reader, writer

        ctx = _make_ctx(arguments={"content": b"bad data"})
        with patch("asyncio.open_connection", side_effect=mock_open_connection):
            result = await p.resource_pre_fetch(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_max_scan_bytes(self):
        from argus_mcp.plugins.external.clamav import ClamAVPlugin

        p = ClamAVPlugin(
            _make_config(
                "clamav",
                {
                    "host": "localhost",
                    "max_scan_bytes": 10,
                },
            )
        )
        big_data = b"x" * 100
        ctx = _make_ctx(arguments={"content": big_data})

        async def mock_open_connection(*a, **kw):
            reader = AsyncMock()
            writer = MagicMock()
            writer.write = MagicMock()
            writer.drain = AsyncMock()
            writer.close = MagicMock()
            writer.wait_closed = AsyncMock()
            reader.read = AsyncMock(return_value=b"stream: OK\0")
            return reader, writer

        with patch("asyncio.open_connection", side_effect=mock_open_connection):
            result = await p.resource_pre_fetch(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_unix_socket(self):
        from argus_mcp.plugins.external.clamav import ClamAVPlugin

        p = ClamAVPlugin(_make_config("clamav", {"unix_socket": "/tmp/clamd.sock"}))

        async def mock_open_unix(*a, **kw):
            reader = AsyncMock()
            writer = MagicMock()
            writer.write = MagicMock()
            writer.drain = AsyncMock()
            writer.close = MagicMock()
            writer.wait_closed = AsyncMock()
            reader.read = AsyncMock(return_value=b"stream: OK\0")
            return reader, writer

        ctx = _make_ctx(arguments={"content": b"test"})
        with patch("asyncio.open_unix_connection", side_effect=mock_open_unix):
            result = await p.resource_pre_fetch(ctx)
        assert result is ctx


# OPA Policy ──────────────────────────────────────────────────


class TestOPAPolicyPlugin:
    @pytest.fixture
    def plugin(self):
        from argus_mcp.plugins.external.opa_policy import OPAPolicyPlugin

        return OPAPolicyPlugin(_make_config("opa", {"opa_url": "http://opa:8181"}))

    @pytest.mark.asyncio
    async def test_lifecycle(self, plugin):
        await plugin.on_load()
        assert plugin._client is not None
        await plugin.on_unload()
        assert plugin._client is None

    @pytest.mark.asyncio
    async def test_allow(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(return_value=_mock_response({"result": True}))
        ctx = _make_ctx()
        result = await plugin.tool_pre_invoke(ctx)
        assert result is ctx
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_deny(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(return_value=_mock_response({"result": False}))
        ctx = _make_ctx()
        with pytest.raises(ValueError, match="OPA"):
            await plugin.tool_pre_invoke(ctx)
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_all_hooks(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(return_value=_mock_response({"result": True}))
        ctx = _make_ctx()
        for hook in (
            plugin.tool_pre_invoke,
            plugin.tool_post_invoke,
            plugin.prompt_pre_fetch,
            plugin.prompt_post_fetch,
            plugin.resource_pre_fetch,
            plugin.resource_post_invoke
            if hasattr(plugin, "resource_post_invoke")
            else plugin.resource_post_fetch,
        ):
            result = await hook(ctx)
            assert result is ctx
        assert plugin._client.post.call_count == 6
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_no_client_default(self, plugin):
        ctx = _make_ctx()
        result = await plugin.tool_pre_invoke(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_api_error_handled(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(side_effect=httpx.ConnectError("down"))
        ctx = _make_ctx()
        result = await plugin.tool_pre_invoke(ctx)
        assert result is ctx
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_sanitize_deep_nesting(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(return_value=_mock_response({"result": True}))
        deep = {"a": {"b": {"c": {"d": {"e": {"f": "very deep"}}}}}}
        ctx = _make_ctx(arguments=deep)
        result = await plugin.tool_pre_invoke(ctx)
        assert result is ctx
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_default_decision_false(self):
        from argus_mcp.plugins.external.opa_policy import OPAPolicyPlugin

        p = OPAPolicyPlugin(
            _make_config(
                "opa",
                {
                    "opa_url": "http://x",
                    "default_decision": False,
                },
            )
        )
        await p.on_load()
        p._client = AsyncMock()
        p._client.post = AsyncMock(side_effect=httpx.ConnectError("down"))
        ctx = _make_ctx()
        with pytest.raises(ValueError, match="OPA"):
            await p.tool_pre_invoke(ctx)
        await p.on_unload()


# Content Moderation ─────────────────────────────────────────


class TestContentModerationPlugin:
    @pytest.fixture
    def plugin(self):
        from argus_mcp.plugins.external.content_moderation import ContentModerationPlugin

        return ContentModerationPlugin(
            _make_config(
                "moderation",
                {
                    "provider": "openai",
                    "api_key": "test-key",
                    "threshold": 0.7,
                    "action": "block",
                },
            )
        )

    @pytest.mark.asyncio
    async def test_lifecycle(self, plugin):
        await plugin.on_load()
        assert plugin._client is not None
        await plugin.on_unload()
        assert plugin._client is None

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_safe(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(
            return_value=_mock_response(
                {"results": [{"category_scores": {"hate": 0.01, "violence": 0.01}}]}
            )
        )
        ctx = _make_ctx(arguments={"prompt": "hello world"})
        result = await plugin.prompt_pre_fetch(ctx)
        assert result is ctx
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_prompt_pre_fetch_blocked(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(
            return_value=_mock_response(
                {"results": [{"category_scores": {"hate": 0.95, "violence": 0.1}}]}
            )
        )
        ctx = _make_ctx(arguments={"prompt": "hateful content"})
        with pytest.raises(ValueError, match="Content moderation"):
            await plugin.prompt_pre_fetch(ctx)
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_tool_pre_invoke(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(
            return_value=_mock_response({"results": [{"category_scores": {"hate": 0.01}}]})
        )
        ctx = _make_ctx(arguments={"text": "safe input"})
        result = await plugin.tool_pre_invoke(ctx)
        assert result is ctx
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_tool_post_invoke(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(
            return_value=_mock_response({"results": [{"category_scores": {"hate": 0.01}}]})
        )
        ctx = _make_ctx(result="safe output text")
        result = await plugin.tool_post_invoke(ctx)
        assert result is ctx
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_tool_post_invoke_not_string_skip(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        ctx = _make_ctx(result={"dict": "result"})
        result = await plugin.tool_post_invoke(ctx)
        assert result is ctx
        plugin._client.post.assert_not_called()
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_warn_action(self):
        from argus_mcp.plugins.external.content_moderation import ContentModerationPlugin

        p = ContentModerationPlugin(
            _make_config(
                "m",
                {
                    "provider": "openai",
                    "api_key": "k",
                    "threshold": 0.5,
                    "action": "warn",
                },
            )
        )
        await p.on_load()
        p._client = AsyncMock()
        p._client.post = AsyncMock(
            return_value=_mock_response({"results": [{"category_scores": {"hate": 0.9}}]})
        )
        ctx = _make_ctx(arguments={"prompt": "flagged"})
        result = await p.prompt_pre_fetch(ctx)
        assert result is ctx
        await p.on_unload()

    @pytest.mark.asyncio
    async def test_no_text_skip(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        ctx = _make_ctx(arguments={"number": 42})
        result = await plugin.prompt_pre_fetch(ctx)
        assert result is ctx
        plugin._client.post.assert_not_called()
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_azure_provider(self):
        from argus_mcp.plugins.external.content_moderation import ContentModerationPlugin

        p = ContentModerationPlugin(
            _make_config(
                "m",
                {
                    "provider": "azure",
                    "api_url": "http://azure.local",
                    "api_key": "az-key",
                    "threshold": 0.5,
                },
            )
        )
        await p.on_load()
        p._client = AsyncMock()
        p._client.post = AsyncMock(
            return_value=_mock_response(
                {
                    "categoriesAnalysis": [
                        {"category": "Hate", "severity": 0},
                        {"category": "Violence", "severity": 1},
                    ]
                }
            )
        )
        ctx = _make_ctx(arguments={"prompt": "test"})
        result = await p.prompt_pre_fetch(ctx)
        assert result is ctx
        await p.on_unload()

    @pytest.mark.asyncio
    async def test_granite_provider(self):
        from argus_mcp.plugins.external.content_moderation import ContentModerationPlugin

        p = ContentModerationPlugin(
            _make_config(
                "m",
                {
                    "provider": "granite",
                    "api_url": "http://ollama.local:11434",
                    "threshold": 0.5,
                },
            )
        )
        await p.on_load()
        p._client = AsyncMock()
        p._client.post = AsyncMock(
            return_value=_mock_response(
                {
                    "response": "no harmful content detected",
                }
            )
        )
        ctx = _make_ctx(arguments={"prompt": "test"})
        result = await p.prompt_pre_fetch(ctx)
        assert result is ctx
        await p.on_unload()

    @pytest.mark.asyncio
    async def test_granite_provider_detected(self):
        from argus_mcp.plugins.external.content_moderation import ContentModerationPlugin

        p = ContentModerationPlugin(
            _make_config(
                "m",
                {
                    "provider": "granite",
                    "api_url": "http://ollama.local:11434",
                    "threshold": 0.5,
                },
            )
        )
        await p.on_load()
        p._client = AsyncMock()
        p._client.post = AsyncMock(
            return_value=_mock_response(
                {
                    "response": "this text contains hate and violence",
                }
            )
        )
        ctx = _make_ctx(arguments={"prompt": "flagged"})
        with pytest.raises(ValueError, match="Content moderation"):
            await p.prompt_pre_fetch(ctx)
        await p.on_unload()

    @pytest.mark.asyncio
    async def test_unsupported_provider(self):
        from argus_mcp.plugins.external.content_moderation import ContentModerationPlugin

        p = ContentModerationPlugin(
            _make_config(
                "m",
                {
                    "provider": "unknown_provider",
                },
            )
        )
        await p.on_load()
        p._client = AsyncMock()
        p._client.post = AsyncMock()
        ctx = _make_ctx(arguments={"prompt": "test"})
        result = await p.prompt_pre_fetch(ctx)
        assert result is ctx
        p._client.post.assert_not_called()
        await p.on_unload()

    @pytest.mark.asyncio
    async def test_api_error_handled(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(side_effect=httpx.ConnectError("down"))
        ctx = _make_ctx(arguments={"prompt": "test"})
        result = await plugin.prompt_pre_fetch(ctx)
        assert result is ctx
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_no_client_skip(self, plugin):
        ctx = _make_ctx(arguments={"prompt": "test"})
        result = await plugin.prompt_pre_fetch(ctx)
        assert result is ctx

    @pytest.mark.asyncio
    async def test_below_threshold_not_triggered(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(
            return_value=_mock_response({"results": [{"category_scores": {"hate": 0.5}}]})
        )
        ctx = _make_ctx(arguments={"prompt": "borderline"})
        result = await plugin.prompt_pre_fetch(ctx)
        assert result is ctx
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_category_filter(self):
        from argus_mcp.plugins.external.content_moderation import ContentModerationPlugin

        p = ContentModerationPlugin(
            _make_config(
                "m",
                {
                    "provider": "openai",
                    "api_key": "k",
                    "threshold": 0.5,
                    "categories": ["violence"],
                },
            )
        )
        await p.on_load()
        p._client = AsyncMock()
        p._client.post = AsyncMock(
            return_value=_mock_response({"results": [{"category_scores": {"hate": 0.99}}]})
        )
        ctx = _make_ctx(arguments={"prompt": "test"})
        result = await p.prompt_pre_fetch(ctx)
        assert result is ctx
        await p.on_unload()

    @pytest.mark.asyncio
    async def test_extract_text_keys(self, plugin):
        assert plugin._extract_text({"prompt": "a"}) == "a"
        assert plugin._extract_text({"text": "b"}) == "b"
        assert plugin._extract_text({"message": "c"}) == "c"
        assert plugin._extract_text({"content": "d"}) == "d"
        assert plugin._extract_text({"query": "e"}) == "e"
        assert plugin._extract_text({"input": "f"}) == "f"
        assert plugin._extract_text({"nope": 1}) is None


# Unified PDP ─────────────────────────────────────────────────


class TestUnifiedPDPPlugin:
    @pytest.fixture
    def plugin(self):
        from argus_mcp.plugins.external.unified_pdp import UnifiedPDPPlugin

        return UnifiedPDPPlugin(
            _make_config(
                "pdp",
                {
                    "engines": [
                        {"name": "opa", "url": "http://opa:8181", "path": "v1/data/allow"},
                        {"name": "cedar", "url": "http://cedar:8000", "path": "authorize"},
                    ],
                    "combination_mode": "all_must_allow",
                    "cache_ttl": 60,
                },
            )
        )

    @pytest.mark.asyncio
    async def test_lifecycle(self, plugin):
        await plugin.on_load()
        assert plugin._client is not None
        await plugin.on_unload()
        assert plugin._client is None
        assert len(plugin._cache) == 0

    @pytest.mark.asyncio
    async def test_all_allow(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(return_value=_mock_response({"result": True}))
        ctx = _make_ctx()
        result = await plugin.tool_pre_invoke(ctx)
        assert result is ctx
        assert "pdp_tool_pre_invoke" in ctx.metadata
        assert ctx.metadata["pdp_tool_pre_invoke"] == "allow"
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_deny_one_engine(self, plugin):
        await plugin.on_load()
        call_count = 0

        async def alternating_response(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_response({"result": True})
            return _mock_response({"result": False})

        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(side_effect=alternating_response)
        ctx = _make_ctx()
        with pytest.raises(ValueError, match="Unified PDP denied"):
            await plugin.tool_pre_invoke(ctx)
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_any_allow_mode(self):
        from argus_mcp.plugins.external.unified_pdp import UnifiedPDPPlugin

        p = UnifiedPDPPlugin(
            _make_config(
                "pdp",
                {
                    "engines": [
                        {"name": "a", "url": "http://a"},
                        {"name": "b", "url": "http://b"},
                    ],
                    "combination_mode": "any_allow",
                },
            )
        )
        await p.on_load()
        call_count = 0

        async def responses(*a, **kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _mock_response({"result": True})
            return _mock_response({"result": False})

        p._client = AsyncMock()
        p._client.post = AsyncMock(side_effect=responses)
        ctx = _make_ctx()
        result = await p.tool_pre_invoke(ctx)
        assert result is ctx
        await p.on_unload()

    @pytest.mark.asyncio
    async def test_first_match_mode(self):
        from argus_mcp.plugins.external.unified_pdp import UnifiedPDPPlugin

        p = UnifiedPDPPlugin(
            _make_config(
                "pdp",
                {
                    "engines": [
                        {"name": "a", "url": "http://a"},
                        {"name": "b", "url": "http://b"},
                    ],
                    "combination_mode": "first_match",
                },
            )
        )
        await p.on_load()
        p._client = AsyncMock()
        p._client.post = AsyncMock(return_value=_mock_response({"result": True}))
        ctx = _make_ctx()
        result = await p.tool_pre_invoke(ctx)
        assert result is ctx
        await p.on_unload()

    @pytest.mark.asyncio
    async def test_cache_hit(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(return_value=_mock_response({"result": True}))
        ctx1 = _make_ctx()
        await plugin.tool_pre_invoke(ctx1)
        initial_count = plugin._client.post.call_count

        ctx2 = _make_ctx()
        result = await plugin.tool_pre_invoke(ctx2)
        assert result is ctx2
        assert ctx2.metadata["pdp_tool_pre_invoke"] == "allow(cached)"
        assert plugin._client.post.call_count == initial_count
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_cache_deny(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(return_value=_mock_response({"result": False}))
        ctx = _make_ctx()
        with pytest.raises(ValueError):
            await plugin.tool_pre_invoke(ctx)

        ctx2 = _make_ctx()
        with pytest.raises(ValueError, match="cached"):
            await plugin.tool_pre_invoke(ctx2)
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_all_hooks(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(return_value=_mock_response({"result": True}))
        plugin._cache_ttl = 0
        for hook in (
            plugin.tool_pre_invoke,
            plugin.tool_post_invoke,
            plugin.prompt_pre_fetch,
            plugin.prompt_post_fetch,
            plugin.resource_pre_fetch,
            plugin.resource_post_fetch,
        ):
            ctx = _make_ctx()
            result = await hook(ctx)
            assert result is ctx
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_engine_error_uses_default(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(side_effect=httpx.ConnectError("down"))
        ctx = _make_ctx()
        result = await plugin.tool_pre_invoke(ctx)
        assert result is ctx
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_engine_error_default_false(self):
        from argus_mcp.plugins.external.unified_pdp import UnifiedPDPPlugin

        p = UnifiedPDPPlugin(
            _make_config(
                "pdp",
                {
                    "engines": [{"name": "x", "url": "http://x"}],
                    "default_decision": False,
                },
            )
        )
        await p.on_load()
        p._client = AsyncMock()
        p._client.post = AsyncMock(side_effect=httpx.ConnectError("down"))
        ctx = _make_ctx()
        with pytest.raises(ValueError, match="Unified PDP denied"):
            await p.tool_pre_invoke(ctx)
        await p.on_unload()

    @pytest.mark.asyncio
    async def test_no_engines(self):
        from argus_mcp.plugins.external.unified_pdp import UnifiedPDPPlugin

        p = UnifiedPDPPlugin(_make_config("pdp", {"engines": []}))
        await p.on_load()
        assert p._client is None
        ctx = _make_ctx()
        result = await p.tool_pre_invoke(ctx)
        assert result is ctx
        await p.on_unload()

    @pytest.mark.asyncio
    async def test_disabled_engine_filtered(self):
        from argus_mcp.plugins.external.unified_pdp import UnifiedPDPPlugin

        p = UnifiedPDPPlugin(
            _make_config(
                "pdp",
                {
                    "engines": [
                        {"name": "active", "url": "http://a", "enabled": True},
                        {"name": "disabled", "url": "http://b", "enabled": False},
                    ],
                },
            )
        )
        assert len(p._engines) == 1
        assert p._engines[0]["name"] == "active"

    @pytest.mark.asyncio
    async def test_string_allow_decision(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(return_value=_mock_response({"decision": "ALLOW"}))
        ctx = _make_ctx()
        result = await plugin.tool_pre_invoke(ctx)
        assert result is ctx
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_dict_decision(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(return_value=_mock_response({"decision": {"allow": True}}))
        ctx = _make_ctx()
        result = await plugin.tool_pre_invoke(ctx)
        assert result is ctx
        await plugin.on_unload()

    @pytest.mark.asyncio
    async def test_api_key_header(self, plugin):
        await plugin.on_load()
        plugin._client = AsyncMock()
        plugin._client.post = AsyncMock(return_value=_mock_response({"result": True}))
        plugin._engines = [{"name": "auth", "url": "http://a", "path": "", "api_key": "secret"}]
        ctx = _make_ctx()
        await plugin.tool_pre_invoke(ctx)
        call_kwargs = plugin._client.post.call_args_list[0]
        assert "Authorization" in call_kwargs.kwargs.get("headers", {}) or (
            len(call_kwargs.args) > 2 and "Authorization" in call_kwargs.args[2]
        )
        await plugin.on_unload()


# Plugin Registration ────────────────────────────────────────


class TestPluginRegistration:
    def test_external_plugins_register(self):
        from argus_mcp.plugins.external import (
            CedarPolicyPlugin,
            ClamAVPlugin,
            ContentModerationPlugin,
            LLMGuardPlugin,
            OPAPolicyPlugin,
            UnifiedPDPPlugin,
            VirusTotalPlugin,
        )

        assert CedarPolicyPlugin is not None
        assert ClamAVPlugin is not None
        assert ContentModerationPlugin is not None
        assert LLMGuardPlugin is not None
        assert OPAPolicyPlugin is not None
        assert UnifiedPDPPlugin is not None
        assert VirusTotalPlugin is not None


# PluginContext ───────────────────────────────────────────────


class TestPluginContextExternal:
    def test_copy_isolation(self):
        ctx = _make_ctx(arguments={"key": "value"}, metadata={"m": 1})
        copy = ctx.copy()
        copy.arguments["key"] = "changed"
        copy.metadata["m"] = 99
        assert ctx.arguments["key"] == "value"
        assert ctx.metadata["m"] == 1

    def test_defaults(self):
        ctx = PluginContext(capability_name="t", mcp_method="m")
        assert ctx.arguments == {}
        assert ctx.server_name == ""
        assert ctx.metadata == {}
        assert ctx.result is None
