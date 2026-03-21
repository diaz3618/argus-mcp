"""Tests for the registry module — models, cache, client."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock, MagicMock

import pytest

from argus_mcp.registry.cache import RegistryCache
from argus_mcp.registry.models import ServerEntry, ServerPage, ToolDefinition

# Models


class TestToolDefinition:
    def test_basic(self):
        t = ToolDefinition(name="read_file", description="Read a file")
        assert t.name == "read_file"
        assert t.description == "Read a file"
        assert t.input_schema == {}


class TestServerEntry:
    def test_from_dict_minimal(self):
        entry = ServerEntry.from_dict({"name": "my-server"})
        assert entry.name == "my-server"
        assert entry.transport == "stdio"
        assert entry.tools == []

    def test_from_dict_full(self):
        data = {
            "name": "github-mcp",
            "description": "GitHub integration",
            "transport": "sse",
            "url": "https://example.com/sse",
            "version": "v2.1.0",
            "categories": ["devtools", "git"],
            "tools": [
                {"name": "list_repos", "description": "List repos"},
                {"name": "create_issue", "description": "Create an issue"},
            ],
            "custom_field": "extra",
        }
        entry = ServerEntry.from_dict(data)
        assert entry.name == "github-mcp"
        assert entry.transport == "sse"
        assert entry.url == "https://example.com/sse"
        assert len(entry.tools) == 2
        assert entry.tools[0].name == "list_repos"
        assert entry.categories == ["devtools", "git"]
        assert entry.extra == {"custom_field": "extra"}

    def test_to_backend_config_stdio(self):
        entry = ServerEntry(name="test", transport="stdio", command="echo", args=["hello"])
        cfg = entry.to_backend_config()
        assert cfg == {"type": "stdio", "command": "echo", "args": ["hello"]}

    def test_to_backend_config_sse(self):
        entry = ServerEntry(name="test", transport="sse", url="http://localhost:8080/sse")
        cfg = entry.to_backend_config()
        assert cfg == {"type": "sse", "url": "http://localhost:8080/sse"}

    def test_to_backend_config_streamable_http(self):
        entry = ServerEntry(name="test", transport="streamable-http", url="http://x/mcp")
        cfg = entry.to_backend_config()
        assert cfg == {"type": "streamable-http", "url": "http://x/mcp"}

    def test_tools_tolerate_bad_data(self):
        data = {
            "name": "test",
            "tools": [
                {"name": "good"},
                "invalid_string",
                None,
            ],
        }
        entry = ServerEntry.from_dict(data)
        assert len(entry.tools) == 1


class TestServerPage:
    def test_from_dict_servers_key(self):
        data = {
            "servers": [
                {"name": "a"},
                {"name": "b"},
            ],
            "next_cursor": "abc123",
            "total": 10,
        }
        page = ServerPage.from_dict(data)
        assert len(page.servers) == 2
        assert page.next_cursor == "abc123"
        assert page.total == 10

    def test_from_dict_items_key(self):
        data = {"items": [{"name": "x"}]}
        page = ServerPage.from_dict(data)
        assert len(page.servers) == 1

    def test_from_dict_empty(self):
        page = ServerPage.from_dict({})
        assert page.servers == []
        assert page.next_cursor is None


# Cache


class TestRegistryCache:
    def test_put_and_get(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = RegistryCache(cache_dir=tmpdir, ttl=60.0)
            entries = [
                ServerEntry(name="a", transport="stdio"),
                ServerEntry(name="b", transport="sse", url="http://x"),
            ]
            cache.put("https://example.com", entries)
            got = cache.get("https://example.com")
            assert got is not None
            assert len(got) == 2
            assert got[0].name == "a"
            assert got[1].name == "b"

    def test_get_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = RegistryCache(cache_dir=tmpdir)
            assert cache.get("https://nowhere.example") is None

    def test_is_fresh(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = RegistryCache(cache_dir=tmpdir, ttl=60.0)
            cache.put("https://example.com", [ServerEntry(name="a")])
            assert cache.is_fresh("https://example.com") is True

    def test_is_not_fresh(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = RegistryCache(cache_dir=tmpdir, ttl=0.0)
            cache.put("https://example.com", [ServerEntry(name="a")])
            # TTL=0 means immediately stale
            assert cache.is_fresh("https://example.com") is False

    def test_clear_specific(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = RegistryCache(cache_dir=tmpdir)
            cache.put("https://a.com", [ServerEntry(name="a")])
            cache.put("https://b.com", [ServerEntry(name="b")])
            cache.clear("https://a.com")
            assert cache.get("https://a.com") is None
            assert cache.get("https://b.com") is not None

    def test_clear_all(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = RegistryCache(cache_dir=tmpdir)
            cache.put("https://a.com", [ServerEntry(name="a")])
            cache.put("https://b.com", [ServerEntry(name="b")])
            cache.clear()
            assert cache.get("https://a.com") is None
            assert cache.get("https://b.com") is None

    def test_corrupt_cache_returns_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = RegistryCache(cache_dir=tmpdir)
            # Write corrupt data
            path = cache._path_for("https://example.com")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write("{invalid json")
            assert cache.get("https://example.com") is None


# Client (with mocked HTTP)


class TestRegistryClient:
    @pytest.mark.anyio
    async def test_list_servers_success(self):
        from argus_mcp.registry.client import RegistryClient

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "servers": [{"name": "test-server", "transport": "sse", "url": "http://x"}]
        }

        mock_httpx_client = AsyncMock()
        mock_httpx_client.get = AsyncMock(return_value=mock_resp)

        client = RegistryClient("https://registry.example.com")
        client._client = mock_httpx_client

        page = await client.list_servers()
        assert len(page.servers) == 1
        assert page.servers[0].name == "test-server"

    @pytest.mark.anyio
    async def test_list_servers_fallback_to_cache(self):
        from argus_mcp.registry.client import RegistryClient

        with tempfile.TemporaryDirectory() as tmpdir:
            cache = RegistryCache(cache_dir=tmpdir, ttl=3600)
            cache.put("https://registry.example.com", [ServerEntry(name="cached-server")])

            mock_httpx_client = AsyncMock()
            mock_httpx_client.get = AsyncMock(side_effect=Exception("Connection refused"))

            client = RegistryClient("https://registry.example.com", cache=cache)
            client._client = mock_httpx_client

            page = await client.list_servers()
            assert len(page.servers) == 1
            assert page.servers[0].name == "cached-server"

    @pytest.mark.anyio
    async def test_get_server_success(self):
        from argus_mcp.registry.client import RegistryClient

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "name": "my-server",
            "transport": "stdio",
            "command": "python",
        }

        mock_httpx_client = AsyncMock()
        mock_httpx_client.get = AsyncMock(return_value=mock_resp)

        client = RegistryClient("https://r.example.com")
        client._client = mock_httpx_client

        entry = await client.get_server("my-server")
        assert entry is not None
        assert entry.name == "my-server"

    @pytest.mark.anyio
    async def test_search_filters_locally_on_failure(self):
        from argus_mcp.registry.client import RegistryClient

        with tempfile.TemporaryDirectory() as tmpdir:
            cache = RegistryCache(cache_dir=tmpdir)
            cache.put(
                "https://r.example.com",
                [
                    ServerEntry(name="github-mcp", description="GitHub tools"),
                    ServerEntry(name="slack-mcp", description="Slack tools"),
                ],
            )

            mock_httpx_client = AsyncMock()
            mock_httpx_client.get = AsyncMock(side_effect=Exception("timeout"))

            client = RegistryClient("https://r.example.com", cache=cache)
            client._client = mock_httpx_client

            results = await client.search("github")
            assert len(results) == 1
            assert results[0].name == "github-mcp"

    @pytest.mark.anyio
    async def test_close(self):
        from argus_mcp.registry.client import RegistryClient

        mock_httpx_client = AsyncMock()
        client = RegistryClient("https://r.example.com")
        client._client = mock_httpx_client

        await client.close()
        mock_httpx_client.aclose.assert_awaited_once()
        assert client._client is None


# Client Config Generator


class TestClientConfigGenerator:
    def test_supported_clients_list(self):
        from argus_mcp.config.client_gen import SUPPORTED_CLIENTS

        assert len(SUPPORTED_CLIENTS) >= 4
        assert "claude-desktop" in SUPPORTED_CLIENTS
        assert "vscode" in SUPPORTED_CLIENTS
