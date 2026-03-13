"""SSE stream resilience: cleanup deadlines, spin-loop detection, tunable knobs.

This module wraps SSE connection handling with configurable resilience
features that protect against runaway connections, slow-drain clients,
and spin-loop pathologies.

Usage::

    from argus_mcp.server.sse_resilience import SseResilience, SseResilienceConfig

    cfg = SseResilienceConfig(send_timeout=10.0, cleanup_deadline=15.0)
    resilience = SseResilience(cfg)

    async with resilience.guarded_sse(read_stream, write_stream) as (r, w):
        await mcp_server.run(r, w, init_opts)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

logger = logging.getLogger(__name__)

DEFAULT_SEND_TIMEOUT: float = 30.0  # seconds — max time to push a single SSE frame
DEFAULT_CLEANUP_DEADLINE: float = 15.0  # seconds — max time for post-disconnect cleanup
DEFAULT_KEEPALIVE_INTERVAL: float = 30.0  # seconds — SSE keepalive ping interval
DEFAULT_SPIN_LOOP_WINDOW: float = 1.0  # seconds — sliding window for spin detection
DEFAULT_SPIN_LOOP_THRESHOLD: int = 200  # max writes in the sliding window


@dataclass
class SseStreamMetrics:
    """Per-connection counters for observability."""

    messages_sent: int = 0
    messages_received: int = 0
    keepalives_sent: int = 0
    send_timeouts: int = 0
    spin_loop_warnings: int = 0
    started_at: float = field(default_factory=time.monotonic)

    def elapsed(self) -> float:
        """Seconds since the connection was opened."""
        return time.monotonic() - self.started_at


class GuardedWriteStream:
    """Wraps the MCP SDK write stream with send timeout and spin detection.

    Parameters
    ----------
    inner:
        The raw ``MemoryObjectSendStream`` from ``SseServerTransport.connect_sse()``.
    send_timeout:
        Maximum seconds to wait for a single ``send()`` call.
    spin_window:
        Sliding-window length (seconds) for spin-loop detection.
    spin_threshold:
        Maximum write calls within the spin window before a warning is logged.
    metrics:
        Shared per-connection metrics object.
    """

    def __init__(
        self,
        inner: MemoryObjectSendStream,
        *,
        send_timeout: float = DEFAULT_SEND_TIMEOUT,
        spin_window: float = DEFAULT_SPIN_LOOP_WINDOW,
        spin_threshold: int = DEFAULT_SPIN_LOOP_THRESHOLD,
        metrics: SseStreamMetrics,
    ) -> None:
        self._inner = inner
        self._send_timeout = send_timeout
        self._spin_window = spin_window
        self._spin_threshold = spin_threshold
        self._metrics = metrics
        self._write_timestamps: list[float] = []

    async def send(self, item: Any) -> None:
        """Send with timeout and spin-loop detection."""
        now = time.monotonic()
        self._detect_spin_loop(now)

        try:
            await asyncio.wait_for(self._inner.send(item), timeout=self._send_timeout)
            self._metrics.messages_sent += 1
        except asyncio.TimeoutError:
            self._metrics.send_timeouts += 1
            logger.warning(
                "SSE send timeout after %.1fs — client may be slow-draining",
                self._send_timeout,
            )
            raise

    async def aclose(self) -> None:
        await self._inner.aclose()

    # Forward common attributes so the SDK doesn't break
    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def _detect_spin_loop(self, now: float) -> None:
        """Track write rate and log a warning if threshold is exceeded."""
        cutoff = now - self._spin_window
        self._write_timestamps = [t for t in self._write_timestamps if t > cutoff]
        self._write_timestamps.append(now)

        if len(self._write_timestamps) > self._spin_threshold:
            self._metrics.spin_loop_warnings += 1
            if self._metrics.spin_loop_warnings <= 5:  # avoid log flood
                logger.warning(
                    "SSE spin-loop detected: %d writes in %.1fs window (threshold=%d, warning #%d)",
                    len(self._write_timestamps),
                    self._spin_window,
                    self._spin_threshold,
                    self._metrics.spin_loop_warnings,
                )


class GuardedReadStream:
    """Thin wrapper around the MCP SDK read stream for metrics."""

    def __init__(
        self,
        inner: MemoryObjectReceiveStream,
        *,
        metrics: SseStreamMetrics,
    ) -> None:
        self._inner = inner
        self._metrics = metrics

    async def receive(self) -> Any:
        item = await self._inner.receive()
        self._metrics.messages_received += 1
        return item

    async def aclose(self) -> None:
        await self._inner.aclose()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


class SseResilience:
    """Wraps SSE connections with cleanup deadlines and send-timeout guards.

    Parameters
    ----------
    send_timeout:
        Max seconds for a single SSE frame push.
    cleanup_deadline:
        Max seconds allowed for session cleanup after disconnect.
    keepalive_interval:
        Seconds between keepalive pings (0 disables).
    spin_loop_window:
        Sliding-window seconds for spin detection.
    spin_loop_threshold:
        Max write calls in the sliding window before warning.
    """

    def __init__(
        self,
        *,
        send_timeout: float = DEFAULT_SEND_TIMEOUT,
        cleanup_deadline: float = DEFAULT_CLEANUP_DEADLINE,
        keepalive_interval: float = DEFAULT_KEEPALIVE_INTERVAL,
        spin_loop_window: float = DEFAULT_SPIN_LOOP_WINDOW,
        spin_loop_threshold: int = DEFAULT_SPIN_LOOP_THRESHOLD,
    ) -> None:
        self.send_timeout = send_timeout
        self.cleanup_deadline = cleanup_deadline
        self.keepalive_interval = keepalive_interval
        self.spin_loop_window = spin_loop_window
        self.spin_loop_threshold = spin_loop_threshold

    def wrap_streams(
        self,
        read_stream: MemoryObjectReceiveStream,
        write_stream: MemoryObjectSendStream,
    ) -> tuple[GuardedReadStream, GuardedWriteStream, SseStreamMetrics]:
        """Wrap raw SDK streams with guarded read/write and shared metrics."""
        metrics = SseStreamMetrics()
        guarded_read = GuardedReadStream(read_stream, metrics=metrics)
        guarded_write = GuardedWriteStream(
            write_stream,
            send_timeout=self.send_timeout,
            spin_window=self.spin_loop_window,
            spin_threshold=self.spin_loop_threshold,
            metrics=metrics,
        )
        return guarded_read, guarded_write, metrics

    async def cleanup_with_deadline(
        self,
        coro: Any,
        *,
        label: str = "session cleanup",
    ) -> None:
        """Run a cleanup coroutine with a hard deadline.

        If the cleanup takes longer than ``cleanup_deadline`` seconds the task
        is cancelled and a warning is logged.
        """
        try:
            await asyncio.wait_for(
                coro if asyncio.iscoroutine(coro) else coro(),
                timeout=self.cleanup_deadline,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "SSE %s exceeded deadline of %.1fs — cancelled",
                label,
                self.cleanup_deadline,
            )
        except Exception:  # noqa: BLE001
            logger.exception("SSE %s failed", label)

    def log_connection_summary(
        self,
        metrics: SseStreamMetrics,
        *,
        url: Optional[str] = None,
    ) -> None:
        """Log a structured summary when the connection closes."""
        extra = f" url={url}" if url else ""
        logger.info(
            "SSE connection closed:%s sent=%d recv=%d keepalives=%d "
            "send_timeouts=%d spin_warnings=%d duration=%.1fs",
            extra,
            metrics.messages_sent,
            metrics.messages_received,
            metrics.keepalives_sent,
            metrics.send_timeouts,
            metrics.spin_loop_warnings,
            metrics.elapsed(),
        )
