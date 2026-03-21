"""Tests for argus_mcp.tui.server_manager — multi-server connection manager.

Covers:
- ServerEntry dataclass
- ServerManager: add/remove, set_active, properties
- Persistence: save/load from JSON
- Connection lifecycle: connect/disconnect/connect_all/close_all
- Factory methods: from_single, from_config
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus_mcp.tui.server_manager import ServerEntry, ServerManager

# ServerEntry


class TestServerEntry:
    def test_defaults(self):
        entry = ServerEntry(name="local", url="http://localhost:9000")
        assert entry.name == "local"
        assert entry.url == "http://localhost:9000"
        assert entry.token is None
        assert entry.client is None
        assert entry.connected is False

    def test_with_token(self):
        entry = ServerEntry(name="remote", url="http://host:9000", token="abc")
        assert entry.token == "abc"


# ServerManager basics


class TestServerManagerBasics:
    def test_empty_manager(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        assert mgr.count == 0
        assert mgr.names == []
        assert mgr.active_name is None
        assert mgr.active_entry is None
        assert mgr.active_client is None

    def test_add_first_becomes_active(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        mgr.add("local", "http://localhost:9000")
        assert mgr.count == 1
        assert mgr.active_name == "local"
        assert mgr.active_entry is not None
        assert mgr.active_entry.name == "local"

    def test_add_strips_trailing_slash(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        entry = mgr.add("srv", "http://localhost:9000/")
        assert entry.url == "http://localhost:9000"

    def test_add_overwrites(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        mgr.add("srv", "http://host1:9000")
        mgr.add("srv", "http://host2:9000")
        assert mgr.count == 1
        assert mgr.entries["srv"].url == "http://host2:9000"

    def test_add_set_active(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        mgr.add("first", "http://first:9000")
        mgr.add("second", "http://second:9000", set_active=True)
        assert mgr.active_name == "second"

    def test_add_no_set_active(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        mgr.add("first", "http://first:9000")
        mgr.add("second", "http://second:9000")
        assert mgr.active_name == "first"

    def test_remove(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        mgr.add("a", "http://a:9000")
        mgr.add("b", "http://b:9000")
        mgr.remove("a")
        assert mgr.count == 1
        assert "a" not in mgr.entries

    def test_remove_active_falls_back(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        mgr.add("a", "http://a:9000")
        mgr.add("b", "http://b:9000")
        mgr.set_active("a")
        mgr.remove("a")
        assert mgr.active_name is not None  # Falls back to remaining

    def test_remove_nonexistent_raises(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        with pytest.raises(KeyError):
            mgr.remove("nonexistent")

    def test_set_active(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        mgr.add("a", "http://a:9000")
        mgr.add("b", "http://b:9000")
        mgr.set_active("b")
        assert mgr.active_name == "b"

    def test_set_active_nonexistent_raises(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        with pytest.raises(KeyError):
            mgr.set_active("nonexistent")

    def test_names_sorted(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        mgr.add("charlie", "http://c:9000")
        mgr.add("alpha", "http://a:9000")
        mgr.add("bravo", "http://b:9000")
        assert mgr.names == ["alpha", "bravo", "charlie"]

    def test_entries_returns_copy(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        mgr.add("a", "http://a:9000")
        entries = mgr.entries
        entries["hacked"] = None  # type: ignore
        assert "hacked" not in mgr.entries


# active_client property


class TestActiveClient:
    def test_returns_none_when_not_connected(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        mgr.add("a", "http://a:9000")
        assert mgr.active_client is None

    def test_returns_client_when_connected(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        entry = mgr.add("a", "http://a:9000")
        entry.connected = True
        entry.client = MagicMock()
        assert mgr.active_client is entry.client


# mark_connected / mark_disconnected


class TestMarkMethods:
    def test_mark_disconnected(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        entry = mgr.add("a", "http://a:9000")
        entry.connected = True
        mgr.mark_disconnected("a")
        assert entry.connected is False

    def test_mark_connected(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        entry = mgr.add("a", "http://a:9000")
        mgr.mark_connected("a")
        assert entry.connected is True

    def test_mark_nonexistent_no_error(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        mgr.mark_disconnected("ghost")  # should not raise
        mgr.mark_connected("ghost")  # should not raise


# Persistence


class TestPersistence:
    def test_save_and_load(self, tmp_path):
        cfg_path = str(tmp_path / "servers.json")

        # Save
        mgr1 = ServerManager(config_path=cfg_path)
        mgr1.add("local", "http://localhost:9000", token="tok1")
        mgr1.add("remote", "http://remote:9000")
        mgr1.set_active("remote")
        mgr1.save()

        # Load into new manager
        mgr2 = ServerManager(config_path=cfg_path)
        mgr2.load()
        assert mgr2.count == 2
        assert mgr2.active_name == "remote"
        assert mgr2.entries["local"].token == "tok1"
        assert mgr2.entries["remote"].token is None

    def test_load_missing_file(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "nonexistent.json"))
        mgr.load()  # Should not raise
        assert mgr.count == 0

    def test_load_corrupt_file(self, tmp_path):
        cfg = tmp_path / "servers.json"
        cfg.write_text("NOT JSON")
        mgr = ServerManager(config_path=str(cfg))
        mgr.load()  # Should not raise
        assert mgr.count == 0

    def test_save_creates_directory(self, tmp_path):
        cfg_path = str(tmp_path / "subdir" / "servers.json")
        mgr = ServerManager(config_path=cfg_path)
        mgr.add("srv", "http://srv:9000")
        mgr.save()
        assert (tmp_path / "subdir" / "servers.json").exists()

    def test_load_skips_entries_missing_name(self, tmp_path):
        cfg = tmp_path / "servers.json"
        data = {
            "servers": [
                {"name": "", "url": "http://x:9000"},
                {"name": "ok", "url": "http://ok:9000"},
            ]
        }
        cfg.write_text(json.dumps(data))
        mgr = ServerManager(config_path=str(cfg))
        mgr.load()
        assert mgr.count == 1
        assert "ok" in mgr.entries


# Connection lifecycle


class TestConnectionLifecycle:
    @pytest.mark.asyncio
    async def test_connect(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        mgr.add("local", "http://localhost:9000")

        with patch("argus_mcp.tui.server_manager.ApiClient") as MockApiClient:
            mock_instance = AsyncMock()
            MockApiClient.return_value = mock_instance

            await mgr.connect("local")

        assert mgr.entries["local"].connected is True
        assert mgr.entries["local"].client is not None

    @pytest.mark.asyncio
    async def test_connect_nonexistent_raises(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        with pytest.raises(KeyError):
            await mgr.connect("nonexistent")

    @pytest.mark.asyncio
    async def test_connect_already_connected_is_noop(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        entry = mgr.add("local", "http://localhost:9000")
        entry.connected = True
        entry.client = MagicMock()

        await mgr.connect("local")  # Should not re-create client

    @pytest.mark.asyncio
    async def test_disconnect(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        entry = mgr.add("local", "http://localhost:9000")
        entry.client = AsyncMock()
        entry.connected = True

        await mgr.disconnect("local")
        assert entry.connected is False
        assert entry.client is None

    @pytest.mark.asyncio
    async def test_disconnect_nonexistent_no_error(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        await mgr.disconnect("ghost")  # Should not raise

    @pytest.mark.asyncio
    async def test_close_all(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        e1 = mgr.add("a", "http://a:9000")
        e2 = mgr.add("b", "http://b:9000")
        e1.client = AsyncMock()
        e1.connected = True
        e2.client = AsyncMock()
        e2.connected = True

        await mgr.close_all()
        assert e1.connected is False
        assert e2.connected is False

    @pytest.mark.asyncio
    async def test_connect_all(self, tmp_path):
        mgr = ServerManager(config_path=str(tmp_path / "servers.json"))
        mgr.add("a", "http://a:9000")
        mgr.add("b", "http://b:9000")

        with patch("argus_mcp.tui.server_manager.ApiClient") as MockApiClient:
            mock_instance = AsyncMock()
            MockApiClient.return_value = mock_instance
            results = await mgr.connect_all()

        assert results["a"] is None  # success
        assert results["b"] is None  # success


# Factory methods


class TestFactoryMethods:
    def test_from_single(self, tmp_path):
        mgr = ServerManager.from_single(
            name="test",
            url="http://test:9000",
            token="tok",
            config_path=str(tmp_path / "servers.json"),
        )
        assert mgr.count == 1
        assert mgr.active_name == "test"
        assert mgr.entries["test"].token == "tok"

    def test_from_config(self, tmp_path):
        cfg = tmp_path / "servers.json"
        data = {
            "servers": [{"name": "loaded", "url": "http://loaded:9000"}],
            "active": "loaded",
        }
        cfg.write_text(json.dumps(data))

        mgr = ServerManager.from_config(config_path=str(cfg))
        assert mgr.count == 1
        assert mgr.active_name == "loaded"

    def test_from_config_missing_file(self, tmp_path):
        mgr = ServerManager.from_config(config_path=str(tmp_path / "nonexistent.json"))
        assert mgr.count == 0
