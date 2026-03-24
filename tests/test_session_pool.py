"""Tests for :mod:`argus_mcp.bridge.session_pool`."""

from __future__ import annotations

from contextlib import AsyncExitStack
from unittest.mock import AsyncMock, MagicMock

import pytest

from argus_mcp.bridge.session_pool import (
    DEFAULT_CB_THRESHOLD,
    DEFAULT_PER_KEY_MAX,
    DEFAULT_TTL,
    PoolEntry,
    SessionKey,
    SessionPool,
)

# Helpers


def _key(url: str = "http://backend:8080", identity: str = "abc", transport: str = "sse"):
    return SessionKey(url=url, identity_hash=identity, transport_type=transport)


def _mock_session() -> MagicMock:
    return MagicMock(name="ClientSession")


def _mock_stack() -> AsyncExitStack:
    stack = AsyncMock(spec=AsyncExitStack)
    stack.aclose = AsyncMock()
    return stack


# SessionKey


class TestSessionKey:
    def test_namedtuple_fields(self):
        k = _key("u", "i", "stdio")
        assert k.url == "u"
        assert k.identity_hash == "i"
        assert k.transport_type == "stdio"

    def test_equality_and_hash(self):
        a = _key("u", "i", "stdio")
        b = _key("u", "i", "stdio")
        assert a == b
        assert hash(a) == hash(b)

    def test_different_keys_not_equal(self):
        a = _key("u1", "i", "stdio")
        b = _key("u2", "i", "stdio")
        assert a != b


# PoolEntry


class TestPoolEntry:
    def test_defaults(self):
        entry = PoolEntry(session=_mock_session(), stack=_mock_stack())
        assert not entry.in_use
        assert entry.age >= 0
        assert entry.idle_time >= 0


# SessionPool lifecycle


class TestSessionPoolLifecycle:
    @pytest.mark.asyncio
    async def test_start_and_stop(self):
        pool = SessionPool()
        await pool.start()
        assert pool._reaper_task is not None
        assert not pool._reaper_task.done()
        await pool.stop()
        assert pool._reaper_task is None

    @pytest.mark.asyncio
    async def test_double_start_is_noop(self):
        pool = SessionPool()
        await pool.start()
        task = pool._reaper_task
        await pool.start()
        assert pool._reaper_task is task
        await pool.stop()

    @pytest.mark.asyncio
    async def test_stop_closes_all_sessions(self):
        pool = SessionPool()
        await pool.start()
        key = _key()
        stack = _mock_stack()
        await pool.add(key, _mock_session(), stack)
        await pool.stop()
        stack.aclose.assert_awaited_once()
        assert pool.total_sessions == 0


# Acquire / release


class TestAcquireRelease:
    @pytest.mark.asyncio
    async def test_acquire_empty_pool_returns_none(self):
        pool = SessionPool()
        await pool.start()
        result = await pool.acquire(_key())
        assert result is None
        await pool.stop()

    @pytest.mark.asyncio
    async def test_acquire_returns_pooled_entry(self):
        pool = SessionPool()
        await pool.start()
        key = _key()
        session = _mock_session()
        added = await pool.add(key, session, _mock_stack())
        assert not added.in_use

        acquired = await pool.acquire(key)
        assert acquired is not None
        assert acquired.session is session
        assert acquired.in_use
        await pool.stop()

    @pytest.mark.asyncio
    async def test_release_marks_not_in_use(self):
        pool = SessionPool()
        await pool.start()
        key = _key()
        await pool.add(key, _mock_session(), _mock_stack())
        acquired = await pool.acquire(key)
        assert acquired is not None

        await pool.release(key, acquired)
        assert not acquired.in_use
        await pool.stop()

    @pytest.mark.asyncio
    async def test_release_with_failure_closes_session(self):
        pool = SessionPool()
        await pool.start()
        key = _key()
        stack = _mock_stack()
        await pool.add(key, _mock_session(), stack)
        acquired = await pool.acquire(key)
        assert acquired is not None

        await pool.release(key, acquired, failed=True)
        stack.aclose.assert_awaited_once()
        assert pool.total_sessions == 0
        await pool.stop()

    @pytest.mark.asyncio
    async def test_acquire_after_close_returns_none(self):
        pool = SessionPool()
        await pool.start()
        key = _key()
        await pool.add(key, _mock_session(), _mock_stack())
        await pool.stop()
        result = await pool.acquire(key)
        assert result is None


# Capacity / eviction


class TestCapacityEviction:
    @pytest.mark.asyncio
    async def test_add_evicts_oldest_when_at_capacity(self):
        pool = SessionPool(per_key_max=2)
        await pool.start()
        key = _key()

        s1 = _mock_stack()
        await pool.add(key, _mock_session(), s1)
        s2 = _mock_stack()
        await pool.add(key, _mock_session(), s2)
        s3 = _mock_stack()
        await pool.add(key, _mock_session(), s3)

        # s1 should have been evicted
        s1.aclose.assert_awaited_once()
        assert pool.total_sessions == 2
        await pool.stop()


# Circuit breaker integration


class TestCircuitBreakerIntegration:
    @pytest.mark.asyncio
    async def test_open_circuit_prevents_acquire(self):
        pool = SessionPool(circuit_breaker_threshold=2)
        await pool.start()
        key = _key()
        await pool.add(key, _mock_session(), _mock_stack())

        cb = pool.get_circuit_breaker(key)
        cb.record_failure()
        cb.record_failure()
        assert not cb.allows_request

        result = await pool.acquire(key)
        assert result is None
        await pool.stop()

    @pytest.mark.asyncio
    async def test_release_failure_increments_cb(self):
        pool = SessionPool(circuit_breaker_threshold=3)
        await pool.start()
        key = _key()
        await pool.add(key, _mock_session(), _mock_stack())
        acquired = await pool.acquire(key)
        assert acquired is not None

        await pool.release(key, acquired, failed=True)
        cb = pool.get_circuit_breaker(key)
        assert cb.consecutive_failures == 1
        await pool.stop()

    @pytest.mark.asyncio
    async def test_release_success_resets_cb(self):
        pool = SessionPool(circuit_breaker_threshold=3)
        await pool.start()
        key = _key()
        await pool.add(key, _mock_session(), _mock_stack())
        cb = pool.get_circuit_breaker(key)
        cb.record_failure()
        assert cb.consecutive_failures == 1

        acquired = await pool.acquire(key)
        assert acquired is not None
        await pool.release(key, acquired)
        assert cb.consecutive_failures == 0
        await pool.stop()


# remove_all


class TestRemoveAll:
    @pytest.mark.asyncio
    async def test_remove_all_closes_and_returns_count(self):
        pool = SessionPool()
        await pool.start()
        key = _key()
        s1 = _mock_stack()
        s2 = _mock_stack()
        await pool.add(key, _mock_session(), s1)
        await pool.add(key, _mock_session(), s2)

        removed = await pool.remove_all(key)
        assert removed == 2
        s1.aclose.assert_awaited_once()
        s2.aclose.assert_awaited_once()
        assert pool.total_sessions == 0
        await pool.stop()

    @pytest.mark.asyncio
    async def test_remove_all_missing_key(self):
        pool = SessionPool()
        await pool.start()
        removed = await pool.remove_all(_key("nonexistent"))
        assert removed == 0
        await pool.stop()


# TTL reaping


class TestReaping:
    @pytest.mark.asyncio
    async def test_expired_sessions_are_reaped(self):
        pool = SessionPool(ttl=10.0, reap_interval=5.0)
        await pool.start()
        key = _key()
        stack = _mock_stack()
        entry = await pool.add(key, _mock_session(), stack)

        # Artificially age the entry beyond TTL
        entry.created_at -= 20.0

        await pool._reap_expired()
        stack.aclose.assert_awaited_once()
        assert pool.total_sessions == 0
        await pool.stop()

    @pytest.mark.asyncio
    async def test_in_use_sessions_not_reaped(self):
        pool = SessionPool(ttl=10.0)
        await pool.start()
        key = _key()
        stack = _mock_stack()
        entry = await pool.add(key, _mock_session(), stack)
        entry.in_use = True
        entry.created_at -= 20.0

        await pool._reap_expired()
        stack.aclose.assert_not_awaited()
        assert pool.total_sessions == 1
        await pool.stop()

    @pytest.mark.asyncio
    async def test_acquire_rejects_expired_entry(self):
        pool = SessionPool(ttl=10.0)
        await pool.start()
        key = _key()
        entry = await pool.add(key, _mock_session(), _mock_stack())
        entry.created_at -= 20.0

        result = await pool.acquire(key)
        assert result is None
        await pool.stop()


# Stats


class TestStats:
    @pytest.mark.asyncio
    async def test_stats_snapshot(self):
        pool = SessionPool(per_key_max=4, ttl=300.0)
        await pool.start()
        key = _key()
        await pool.add(key, _mock_session(), _mock_stack())
        entry = await pool.acquire(key)
        assert entry is not None

        s = pool.stats()
        assert s["total"] == 1
        assert s["active"] == 1
        assert s["keys"] == 1
        assert s["per_key_max"] == 4
        assert s["ttl"] == 300.0
        await pool.stop()

    @pytest.mark.asyncio
    async def test_total_sessions_across_keys(self):
        pool = SessionPool()
        await pool.start()
        await pool.add(_key("a"), _mock_session(), _mock_stack())
        await pool.add(_key("b"), _mock_session(), _mock_stack())
        assert pool.total_sessions == 2
        await pool.stop()


# Config model


class TestSessionPoolConfig:
    def test_defaults(self):
        from argus_mcp.config.schema import SessionPoolConfig

        cfg = SessionPoolConfig()
        assert cfg.enabled is True
        assert cfg.per_key_max == DEFAULT_PER_KEY_MAX
        assert cfg.ttl == DEFAULT_TTL
        assert cfg.circuit_breaker_threshold == DEFAULT_CB_THRESHOLD

    def test_in_argus_config(self):
        from argus_mcp.config.schema import ArgusConfig

        cfg = ArgusConfig()
        assert hasattr(cfg, "session_pool")
        assert cfg.session_pool.enabled is True

    def test_custom_values(self):
        from argus_mcp.config.schema import SessionPoolConfig

        cfg = SessionPoolConfig(
            enabled=False, per_key_max=8, ttl=120.0, circuit_breaker_threshold=5
        )
        assert cfg.enabled is False
        assert cfg.per_key_max == 8
        assert cfg.ttl == 120.0
        assert cfg.circuit_breaker_threshold == 5

    def test_validation_bounds(self):
        from pydantic import ValidationError

        from argus_mcp.config.schema import SessionPoolConfig

        with pytest.raises(ValidationError):
            SessionPoolConfig(per_key_max=0)
        with pytest.raises(ValidationError):
            SessionPoolConfig(ttl=5.0)  # below 10.0
        with pytest.raises(ValidationError):
            SessionPoolConfig(circuit_breaker_threshold=0)
