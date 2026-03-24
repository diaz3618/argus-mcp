"""MCP session pool with TTL, max-per-key, and circuit breaker awareness.

Pools :class:`mcp.ClientSession` objects keyed by
``(url, identity_hash, transport_type)`` to avoid the overhead of
re-establishing transport connections for every request.  A background
reaper task evicts sessions that exceed their TTL.

Usage::

    pool = SessionPool(per_key_max=4, ttl=300.0)
    await pool.start()

    entry = pool.acquire(key)
    if entry is not None:
        session = entry.session
        ...
        pool.release(key, entry)
    else:
        session = await create_new_session(...)
        pool.add(key, session, stack)

    await pool.stop()
"""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from typing import Dict, List, NamedTuple, Optional

from mcp import ClientSession

from argus_mcp.bridge.health.circuit_breaker import CircuitBreaker
from argus_mcp.constants import STACK_CLOSE_TIMEOUT

try:
    from argus_mcp.bridge.health._circuit_breaker_rs import (
        RUST_AVAILABLE as _CB_RUST,
    )
    from argus_mcp.bridge.health._circuit_breaker_rs import (
        CircuitBreaker as _RustCB,
    )
except ImportError:
    _CB_RUST = False
    _RustCB = None

logger = logging.getLogger(__name__)


class SessionKey(NamedTuple):
    """Composite key for pooled sessions."""

    url: str
    identity_hash: str
    transport_type: str


@dataclass
class PoolEntry:
    """A single pooled session with creation metadata."""

    session: ClientSession
    stack: AsyncExitStack
    created_at: float = field(default_factory=time.monotonic)
    last_used: float = field(default_factory=time.monotonic)
    in_use: bool = False

    @property
    def age(self) -> float:
        return time.monotonic() - self.created_at

    @property
    def idle_time(self) -> float:
        return time.monotonic() - self.last_used


DEFAULT_PER_KEY_MAX = 4
DEFAULT_TTL = 300.0  # seconds
DEFAULT_REAP_INTERVAL = 30.0  # seconds
DEFAULT_CB_THRESHOLD = 3


class SessionPool:
    """MCP ClientSession pool with TTL eviction and circuit breaker awareness.

    Parameters
    ----------
    per_key_max:
        Maximum number of sessions per key.
    ttl:
        Time-to-live in seconds for idle sessions.
    reap_interval:
        Seconds between background reaper sweeps.
    circuit_breaker_threshold:
        Failure count before the circuit breaker opens for a key.
    """

    def __init__(
        self,
        per_key_max: int = DEFAULT_PER_KEY_MAX,
        ttl: float = DEFAULT_TTL,
        reap_interval: float = DEFAULT_REAP_INTERVAL,
        circuit_breaker_threshold: int = DEFAULT_CB_THRESHOLD,
    ) -> None:
        self._per_key_max = max(1, per_key_max)
        self._ttl = max(1.0, ttl)
        self._reap_interval = max(5.0, reap_interval)
        self._cb_threshold = max(1, circuit_breaker_threshold)

        self._pool: Dict[SessionKey, List[PoolEntry]] = {}
        self._circuit_breakers: Dict[SessionKey, CircuitBreaker] = {}
        self._reaper_task: Optional[asyncio.Task[None]] = None
        self._lock = asyncio.Lock()
        self._closed = False

    async def start(self) -> None:
        """Start the background reaper task."""
        if self._reaper_task is not None:
            return
        self._closed = False
        self._reaper_task = asyncio.create_task(self._reap_loop(), name="session-pool-reaper")
        logger.info(
            "SessionPool started (per_key_max=%d, ttl=%.0fs, reap_interval=%.0fs).",
            self._per_key_max,
            self._ttl,
            self._reap_interval,
        )

    async def stop(self) -> None:
        """Stop the reaper and close all pooled sessions."""
        self._closed = True
        if self._reaper_task is not None:
            self._reaper_task.cancel()
            try:
                await self._reaper_task
            except asyncio.CancelledError:
                pass
            self._reaper_task = None

        async with self._lock:
            for key, entries in self._pool.items():
                for entry in entries:
                    await self._close_entry(key, entry)
            self._pool.clear()
            self._circuit_breakers.clear()

        logger.info("SessionPool stopped — all sessions closed.")

    async def acquire(self, key: SessionKey) -> Optional[PoolEntry]:
        """Acquire an idle session from the pool for *key*.

        Returns ``None`` if no idle session is available or the circuit
        breaker is open.
        """
        if self._closed:
            return None

        cb = self._get_circuit_breaker(key)
        if not cb.allows_request:
            logger.debug("SessionPool: circuit open for %s — skipping pool.", key)
            return None

        async with self._lock:
            entries = self._pool.get(key)
            if not entries:
                return None
            for entry in entries:
                if not entry.in_use and entry.age < self._ttl:
                    entry.in_use = True
                    entry.last_used = time.monotonic()
                    logger.debug("SessionPool: acquired cached session for %s.", key)
                    return entry
        return None

    async def release(self, key: SessionKey, entry: PoolEntry, *, failed: bool = False) -> None:
        """Return a session to the pool after use.

        Parameters
        ----------
        failed:
            If ``True`` the session experienced an error — it will be
            closed instead of returned to the pool, and the circuit
            breaker failure count is incremented.
        """
        cb = self._get_circuit_breaker(key)

        if failed:
            cb.record_failure()
            await self._close_entry(key, entry)
            async with self._lock:
                entries = self._pool.get(key, [])
                if entry in entries:
                    entries.remove(entry)
            return

        cb.record_success()
        async with self._lock:
            entry.in_use = False
            entry.last_used = time.monotonic()

    async def add(
        self,
        key: SessionKey,
        session: ClientSession,
        stack: AsyncExitStack,
    ) -> PoolEntry:
        """Add a newly created session to the pool.

        If the pool for *key* is already at capacity, the oldest idle
        entry is evicted.
        """
        entry = PoolEntry(session=session, stack=stack)

        async with self._lock:
            entries = self._pool.setdefault(key, [])

            # Evict oldest idle entry when at capacity.
            while len(entries) >= self._per_key_max:
                idle = [e for e in entries if not e.in_use]
                if not idle:
                    break
                oldest = min(idle, key=lambda e: e.last_used)
                entries.remove(oldest)
                await self._close_entry(key, oldest)
                logger.debug("SessionPool: evicted oldest idle session for %s.", key)

            entries.append(entry)

        logger.debug(
            "SessionPool: added session for %s (pool size: %d).",
            key,
            len(self._pool.get(key, [])),
        )
        return entry

    async def remove_all(self, key: SessionKey) -> int:
        """Remove and close all sessions for *key*. Returns count removed."""
        async with self._lock:
            entries = self._pool.pop(key, [])
        closed = 0
        for entry in entries:
            await self._close_entry(key, entry)
            closed += 1
        if closed:
            logger.info("SessionPool: removed %d session(s) for %s.", closed, key)
        return closed

    @property
    def total_sessions(self) -> int:
        """Total number of sessions across all keys."""
        return sum(len(entries) for entries in self._pool.values())

    @property
    def active_sessions(self) -> int:
        """Number of sessions currently in use."""
        return sum(1 for entries in self._pool.values() for entry in entries if entry.in_use)

    def stats(self) -> Dict[str, object]:
        """Return a snapshot of pool statistics."""
        return {
            "total": self.total_sessions,
            "active": self.active_sessions,
            "keys": len(self._pool),
            "per_key_max": self._per_key_max,
            "ttl": self._ttl,
        }

    def get_circuit_breaker(self, key: SessionKey) -> CircuitBreaker:
        """Expose the circuit breaker for a key (read-only diagnostics)."""
        return self._get_circuit_breaker(key)

    def _get_circuit_breaker(self, key: SessionKey) -> CircuitBreaker:
        cb = self._circuit_breakers.get(key)
        if cb is None:
            _CB = _RustCB if _CB_RUST and _RustCB is not None else CircuitBreaker
            cb = _CB(
                name=f"pool:{key.url}",
                failure_threshold=self._cb_threshold,
            )
            self._circuit_breakers[key] = cb
        return cb

    async def _close_entry(self, key: SessionKey, entry: PoolEntry) -> None:
        """Close a single pool entry safely."""
        try:
            await asyncio.wait_for(entry.stack.aclose(), timeout=STACK_CLOSE_TIMEOUT)
        except asyncio.TimeoutError:
            logger.warning("SessionPool: timeout closing session for %s.", key)
        except Exception:  # noqa: BLE001
            logger.debug("SessionPool: error closing session for %s.", key, exc_info=True)

    async def _reap_loop(self) -> None:
        """Background loop that evicts expired idle sessions."""
        while not self._closed:
            try:
                await asyncio.sleep(self._reap_interval)
            except asyncio.CancelledError:
                return
            await self._reap_expired()

    async def _reap_expired(self) -> None:
        """Single pass: close idle sessions that exceed TTL."""
        now = time.monotonic()
        to_close: List[tuple[SessionKey, PoolEntry]] = []

        async with self._lock:
            for key, entries in list(self._pool.items()):
                expired = [e for e in entries if not e.in_use and (now - e.created_at) >= self._ttl]
                for entry in expired:
                    entries.remove(entry)
                    to_close.append((key, entry))
                if not entries:
                    del self._pool[key]

        for key, entry in to_close:
            await self._close_entry(key, entry)

        if to_close:
            logger.debug("SessionPool: reaped %d expired session(s).", len(to_close))
