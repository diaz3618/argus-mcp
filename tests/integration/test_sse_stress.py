"""Stress tests for SSE resilience guards.

Exercises the GuardedWriteStream, GuardedReadStream, SseResilience
orchestrator, and SseStreamMetrics under concurrent / rapid-fire
conditions to verify correctness under load.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from argus_mcp.server.sse_resilience import (
    GuardedWriteStream,
    SseResilience,
    SseStreamMetrics,
)

pytestmark = [pytest.mark.stress]


# Helpers


def _mock_send_stream(delay: float = 0.0) -> AsyncMock:
    """Build a mock MemoryObjectSendStream with optional per-send delay."""
    stream = AsyncMock()

    async def _slow_send(item):
        if delay:
            await asyncio.sleep(delay)

    stream.send = AsyncMock(side_effect=_slow_send)
    stream.aclose = AsyncMock()
    return stream


def _mock_recv_stream() -> AsyncMock:
    """Build a mock MemoryObjectReceiveStream that yields nothing."""
    stream = AsyncMock()
    stream.receive = AsyncMock(side_effect=StopAsyncIteration)
    stream.aclose = AsyncMock()
    return stream


# GuardedWriteStream stress


class TestGuardedWriteStreamStress:
    """High-throughput and edge-case tests for the write guard."""

    @pytest.mark.asyncio
    async def test_rapid_fire_sends_counted(self) -> None:
        """Many sequential sends should all be counted in metrics."""
        inner = _mock_send_stream(delay=0.0)
        metrics = SseStreamMetrics()
        guard = GuardedWriteStream(
            inner,
            send_timeout=5.0,
            spin_window=1.0,
            spin_threshold=10000,  # high threshold — no spin warnings
            metrics=metrics,
        )
        count = 500
        for i in range(count):
            await guard.send(f"msg-{i}")
        assert metrics.messages_sent == count
        assert metrics.send_timeouts == 0

    @pytest.mark.asyncio
    async def test_send_timeout_fires(self) -> None:
        """A slow inner stream should trigger a send timeout."""
        inner = _mock_send_stream(delay=5.0)
        metrics = SseStreamMetrics()
        guard = GuardedWriteStream(
            inner,
            send_timeout=0.05,  # 50ms
            spin_window=1.0,
            spin_threshold=10000,
            metrics=metrics,
        )
        with pytest.raises(asyncio.TimeoutError):
            await guard.send("payload")
        assert metrics.send_timeouts == 1

    @pytest.mark.asyncio
    async def test_spin_loop_detection(self) -> None:
        """Writes exceeding spin threshold within the window should trigger a warning."""
        inner = _mock_send_stream(delay=0.0)
        metrics = SseStreamMetrics()
        threshold = 20
        guard = GuardedWriteStream(
            inner,
            send_timeout=5.0,
            spin_window=10.0,  # wide window so all writes are captured
            spin_threshold=threshold,
            metrics=metrics,
        )
        for i in range(threshold + 10):
            await guard.send(f"msg-{i}")
        assert metrics.spin_loop_warnings > 0

    @pytest.mark.asyncio
    async def test_spin_loop_window_expiry(self) -> None:
        """Writes spread across separate windows should NOT trigger spin detection."""
        inner = _mock_send_stream(delay=0.0)
        metrics = SseStreamMetrics()
        guard = GuardedWriteStream(
            inner,
            send_timeout=5.0,
            spin_window=0.05,  # 50ms window
            spin_threshold=5,
            metrics=metrics,
        )
        # Batch 1 — under threshold
        for i in range(4):
            await guard.send(f"batch1-{i}")
        # Wait for window to expire
        await asyncio.sleep(0.1)
        # Batch 2 — under threshold again
        for i in range(4):
            await guard.send(f"batch2-{i}")
        assert metrics.spin_loop_warnings == 0

    @pytest.mark.asyncio
    async def test_concurrent_sends(self) -> None:
        """Concurrent send calls should all complete without deadlock."""
        inner = _mock_send_stream(delay=0.001)
        metrics = SseStreamMetrics()
        guard = GuardedWriteStream(
            inner,
            send_timeout=5.0,
            spin_window=1.0,
            spin_threshold=10000,
            metrics=metrics,
        )
        tasks = [asyncio.create_task(guard.send(f"msg-{i}")) for i in range(50)]
        await asyncio.gather(*tasks)
        assert metrics.messages_sent == 50


# SseResilience orchestrator stress


class TestSseResilienceStress:
    """Integration-level stress tests for the SseResilience orchestrator."""

    def test_wrap_streams_returns_guarded_pair(self) -> None:
        """wrap_streams should return guarded read, write, and shared metrics."""
        resilience = SseResilience(
            send_timeout=5.0,
            cleanup_deadline=5.0,
            keepalive_interval=0.0,
            spin_loop_window=1.0,
            spin_loop_threshold=1000,
        )
        read_stream = _mock_recv_stream()
        write_stream = _mock_send_stream()
        guarded_read, guarded_write, metrics = resilience.wrap_streams(read_stream, write_stream)
        assert metrics is not None
        assert metrics.messages_sent == 0

    @pytest.mark.asyncio
    async def test_cleanup_with_deadline_succeeds(self) -> None:
        """Cleanup that finishes in time should not raise."""
        resilience = SseResilience(
            cleanup_deadline=5.0,
        )

        async def fast_cleanup() -> None:
            pass

        await resilience.cleanup_with_deadline(fast_cleanup())

    @pytest.mark.asyncio
    async def test_cleanup_with_deadline_timeout(self) -> None:
        """Cleanup that exceeds deadline should be cancelled (not raise)."""
        resilience = SseResilience(
            cleanup_deadline=0.05,  # 50ms
        )

        async def slow_cleanup() -> None:
            await asyncio.sleep(5.0)

        # Should NOT raise — the timeout is handled internally
        await resilience.cleanup_with_deadline(slow_cleanup())


# SseStreamMetrics


class TestSseStreamMetricsStress:
    """Verify metrics accuracy under rapid updates."""

    def test_elapsed_monotonic(self) -> None:
        metrics = SseStreamMetrics()
        e1 = metrics.elapsed()
        # Busy wait a tiny bit
        time.sleep(0.01)
        e2 = metrics.elapsed()
        assert e2 > e1

    def test_counter_accuracy(self) -> None:
        metrics = SseStreamMetrics()
        for _ in range(1000):
            metrics.messages_sent += 1
        assert metrics.messages_sent == 1000
