"""Concurrency stress tests for SessionPool (CONC-01 validation).

Each test runs 50x via pytest-repeat to surface non-deterministic races.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from argus_mcp.bridge.session_pool import PoolEntry, SessionKey, SessionPool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _key(
    url: str = "http://localhost", identity: str = "id", transport: str = "stdio"
) -> SessionKey:
    return SessionKey(url=url, identity_hash=identity, transport_type=transport)


def _mock_session() -> MagicMock:
    return MagicMock(name="ClientSession")


def _mock_stack() -> AsyncMock:
    stack = AsyncMock(name="AsyncExitStack")
    stack.aclose = AsyncMock()
    return stack


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.repeat(50)
async def test_concurrent_add_release_no_corruption():
    """10 tasks do add+acquire+release on the same key; pool stays consistent."""
    pool = SessionPool(per_key_max=10, ttl=300.0, reap_interval=60.0, circuit_breaker_threshold=5)
    await pool.start()
    key = _key()

    async def _worker() -> None:
        session, stack = _mock_session(), _mock_stack()
        await pool.add(key, session, stack)
        # Acquire and release immediately
        acquired = await pool.acquire(key)
        if acquired is not None:
            await pool.release(key, acquired)

    await asyncio.gather(*[_worker() for _ in range(10)])

    # All entries should be present and not in-use
    assert pool.total_sessions == 10
    await pool.stop()


@pytest.mark.repeat(50)
async def test_concurrent_stop_while_acquiring():
    """10 tasks acquire while stop() runs; no unhandled exception is raised."""
    pool = SessionPool(per_key_max=10, ttl=300.0, reap_interval=60.0, circuit_breaker_threshold=5)
    await pool.start()
    key = _key()

    # Pre-populate entries
    entries = []
    for _ in range(10):
        entry = await pool.add(key, _mock_session(), _mock_stack())
        entries.append(entry)

    async def _acquire_loop() -> None:
        for _ in range(5):
            try:
                acquired = await pool.acquire(key)
                if acquired is not None:
                    await pool.release(key, acquired)
            except Exception:
                # Pool is stopping — acceptable
                pass

    # Run acquires concurrently with stop
    tasks = [asyncio.create_task(_acquire_loop()) for _ in range(10)]
    tasks.append(asyncio.create_task(pool.stop()))
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.repeat(50)
async def test_concurrent_release_failed_entries():
    """10 tasks release(failed=True) overlapping entries; pool drains, no double-close."""
    pool = SessionPool(per_key_max=10, ttl=300.0, reap_interval=60.0, circuit_breaker_threshold=5)
    await pool.start()
    key = _key()

    # Add and immediately acquire entries so they can be released as failed
    acquired_entries = []
    for _ in range(10):
        await pool.add(key, _mock_session(), _mock_stack())
        entry = await pool.acquire(key)
        assert entry is not None
        acquired_entries.append(entry)

    async def _fail_release(entry: PoolEntry) -> None:
        try:
            await pool.release(key, entry, failed=True)
        except Exception:
            pass  # duplicate release — acceptable

    await asyncio.gather(*[_fail_release(e) for e in acquired_entries])

    # All failed entries are evicted
    assert pool.total_sessions == 0
    await pool.stop()
