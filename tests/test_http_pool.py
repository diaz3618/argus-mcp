"""Tests for :mod:`argus_mcp.bridge.http_pool`."""

from __future__ import annotations

import pytest

from argus_mcp.bridge.http_pool import (
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MAX_KEEPALIVE,
    DEFAULT_TIMEOUT,
    HttpPool,
)

# Defaults


class TestDefaults:
    def test_default_max_connections(self):
        assert DEFAULT_MAX_CONNECTIONS == 200

    def test_default_max_keepalive(self):
        assert DEFAULT_MAX_KEEPALIVE == 100

    def test_default_timeout(self):
        assert DEFAULT_TIMEOUT == 30.0


# Lifecycle


class TestLifecycle:
    async def test_start_creates_client(self):
        pool = HttpPool()
        assert not pool.is_running
        await pool.start()
        try:
            assert pool.is_running
        finally:
            await pool.stop()

    async def test_start_is_idempotent(self):
        pool = HttpPool()
        await pool.start()
        client1 = pool.client
        await pool.start()  # second start — should be a noop
        assert pool.client is client1
        await pool.stop()

    async def test_stop_closes_client(self):
        pool = HttpPool()
        await pool.start()
        assert pool.is_running
        await pool.stop()
        assert not pool.is_running

    async def test_stop_is_idempotent(self):
        pool = HttpPool()
        await pool.start()
        await pool.stop()
        await pool.stop()  # second stop — no error
        assert not pool.is_running


# Client access


class TestClientAccess:
    async def test_client_before_start_raises(self):
        pool = HttpPool()
        with pytest.raises(RuntimeError, match="not running"):
            _ = pool.client

    async def test_client_after_stop_raises(self):
        pool = HttpPool()
        await pool.start()
        await pool.stop()
        with pytest.raises(RuntimeError, match="not running"):
            _ = pool.client

    async def test_client_returns_httpx_client(self):
        import httpx

        pool = HttpPool()
        await pool.start()
        try:
            assert isinstance(pool.client, httpx.AsyncClient)
        finally:
            await pool.stop()


# Custom configuration


class TestCustomConfig:
    async def test_custom_limits(self):
        pool = HttpPool(max_connections=50, max_keepalive=25, timeout=10.0)
        await pool.start()
        try:
            stats = pool.stats()
            assert stats["max_connections"] == 50
            assert stats["max_keepalive"] == 25
            assert stats["timeout"] == 10.0
            assert stats["running"] is True
        finally:
            await pool.stop()


# Stats


class TestStats:
    async def test_stats_when_stopped(self):
        pool = HttpPool()
        stats = pool.stats()
        assert stats["running"] is False
        assert stats["max_connections"] == DEFAULT_MAX_CONNECTIONS
        assert stats["max_keepalive"] == DEFAULT_MAX_KEEPALIVE
        assert stats["timeout"] == DEFAULT_TIMEOUT

    async def test_stats_when_running(self):
        pool = HttpPool()
        await pool.start()
        try:
            stats = pool.stats()
            assert stats["running"] is True
        finally:
            await pool.stop()


# HttpPoolConfig schema


class TestHttpPoolConfig:
    def test_defaults(self):
        from argus_mcp.config.schema import HttpPoolConfig

        cfg = HttpPoolConfig()
        assert cfg.enabled is True
        assert cfg.max_connections == 200
        assert cfg.max_keepalive == 100
        assert cfg.timeout == 30.0

    def test_in_argus_config(self):
        from argus_mcp.config.schema import ArgusConfig

        config = ArgusConfig()
        assert hasattr(config, "http_pool")
        assert config.http_pool.enabled is True

    def test_custom_values(self):
        from argus_mcp.config.schema import HttpPoolConfig

        cfg = HttpPoolConfig(
            enabled=False,
            max_connections=50,
            max_keepalive=25,
            timeout=10.0,
        )
        assert cfg.enabled is False
        assert cfg.max_connections == 50
        assert cfg.max_keepalive == 25
        assert cfg.timeout == 10.0

    def test_validation_bounds(self):
        from argus_mcp.config.schema import HttpPoolConfig

        with pytest.raises(Exception):
            HttpPoolConfig(max_connections=0)
        with pytest.raises(Exception):
            HttpPoolConfig(max_connections=3000)
        with pytest.raises(Exception):
            HttpPoolConfig(timeout=0.5)
        with pytest.raises(Exception):
            HttpPoolConfig(timeout=500.0)
