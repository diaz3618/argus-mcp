"""Tests for argus_mcp.server.sse_resilience — SSE stream resilience guards."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus_mcp.config.schema import ArgusConfig, SseResilienceConfig
from argus_mcp.server.sse_resilience import (
    DEFAULT_CLEANUP_DEADLINE,
    DEFAULT_KEEPALIVE_INTERVAL,
    DEFAULT_SEND_TIMEOUT,
    DEFAULT_SPIN_LOOP_THRESHOLD,
    DEFAULT_SPIN_LOOP_WINDOW,
    GuardedReadStream,
    GuardedWriteStream,
    SseResilience,
    SseStreamMetrics,
)

#  SseStreamMetrics


class TestSseStreamMetrics:
    def test_defaults(self) -> None:
        m = SseStreamMetrics()
        assert m.messages_sent == 0
        assert m.messages_received == 0
        assert m.keepalives_sent == 0
        assert m.send_timeouts == 0
        assert m.spin_loop_warnings == 0
        assert isinstance(m.started_at, float)

    def test_elapsed_grows(self) -> None:
        m = SseStreamMetrics(started_at=time.monotonic() - 1.0)
        assert m.elapsed() >= 1.0

    def test_elapsed_fresh(self) -> None:
        m = SseStreamMetrics()
        assert m.elapsed() < 1.0


#  GuardedWriteStream


class TestGuardedWriteStream:
    def _make_stream(
        self,
        *,
        send_timeout: float = DEFAULT_SEND_TIMEOUT,
        spin_window: float = DEFAULT_SPIN_LOOP_WINDOW,
        spin_threshold: int = DEFAULT_SPIN_LOOP_THRESHOLD,
    ) -> tuple[GuardedWriteStream, AsyncMock, SseStreamMetrics]:
        inner = AsyncMock()
        inner.send = AsyncMock()
        inner.aclose = AsyncMock()
        metrics = SseStreamMetrics()
        gw = GuardedWriteStream(
            inner,
            send_timeout=send_timeout,
            spin_window=spin_window,
            spin_threshold=spin_threshold,
            metrics=metrics,
        )
        return gw, inner, metrics

    async def test_send_delegates_and_counts(self) -> None:
        gw, inner, metrics = self._make_stream()
        await gw.send("hello")
        inner.send.assert_awaited_once_with("hello")
        assert metrics.messages_sent == 1

    async def test_send_multiple_counts(self) -> None:
        gw, inner, metrics = self._make_stream()
        for i in range(5):
            await gw.send(f"msg-{i}")
        assert metrics.messages_sent == 5
        assert inner.send.await_count == 5

    async def test_send_timeout_increments_metric(self) -> None:
        gw, inner, metrics = self._make_stream(send_timeout=0.01)

        # Replace inner.send with a real coroutine function that blocks
        async def _hang(item: object) -> None:
            await asyncio.sleep(5.0)

        inner.send = _hang
        with pytest.raises(asyncio.TimeoutError):
            await gw.send("slow")
        assert metrics.send_timeouts == 1
        assert metrics.messages_sent == 0

    async def test_aclose_delegates(self) -> None:
        gw, inner, _ = self._make_stream()
        await gw.aclose()
        inner.aclose.assert_awaited_once()

    async def test_getattr_forwards(self) -> None:
        gw, inner, _ = self._make_stream()
        inner.some_attr = "test_value"
        assert gw.some_attr == "test_value"

    async def test_spin_loop_detection(self) -> None:
        gw, inner, metrics = self._make_stream(
            spin_window=10.0,  # wide window
            spin_threshold=5,  # low threshold
        )
        for _ in range(10):
            await gw.send("x")
        assert metrics.spin_loop_warnings > 0

    async def test_no_spin_loop_below_threshold(self) -> None:
        gw, inner, metrics = self._make_stream(
            spin_window=10.0,
            spin_threshold=100,
        )
        for _ in range(5):
            await gw.send("x")
        assert metrics.spin_loop_warnings == 0


#  GuardedReadStream


class TestGuardedReadStream:
    def _make_stream(self) -> tuple[GuardedReadStream, AsyncMock, SseStreamMetrics]:
        inner = AsyncMock()
        inner.receive = AsyncMock(return_value="msg")
        inner.aclose = AsyncMock()
        metrics = SseStreamMetrics()
        gr = GuardedReadStream(inner, metrics=metrics)
        return gr, inner, metrics

    async def test_receive_delegates_and_counts(self) -> None:
        gr, inner, metrics = self._make_stream()
        result = await gr.receive()
        assert result == "msg"
        assert metrics.messages_received == 1

    async def test_receive_multiple_counts(self) -> None:
        gr, inner, metrics = self._make_stream()
        for _ in range(4):
            await gr.receive()
        assert metrics.messages_received == 4

    async def test_aclose_delegates(self) -> None:
        gr, inner, _ = self._make_stream()
        await gr.aclose()
        inner.aclose.assert_awaited_once()

    async def test_getattr_forwards(self) -> None:
        gr, inner, _ = self._make_stream()
        inner.some_prop = 42
        assert gr.some_prop == 42


#  SseResilience


class TestSseResilience:
    def test_defaults(self) -> None:
        r = SseResilience()
        assert r.send_timeout == DEFAULT_SEND_TIMEOUT
        assert r.cleanup_deadline == DEFAULT_CLEANUP_DEADLINE
        assert r.keepalive_interval == DEFAULT_KEEPALIVE_INTERVAL
        assert r.spin_loop_window == DEFAULT_SPIN_LOOP_WINDOW
        assert r.spin_loop_threshold == DEFAULT_SPIN_LOOP_THRESHOLD

    def test_custom_values(self) -> None:
        r = SseResilience(
            send_timeout=5.0,
            cleanup_deadline=10.0,
            keepalive_interval=60.0,
            spin_loop_window=2.0,
            spin_loop_threshold=500,
        )
        assert r.send_timeout == 5.0
        assert r.cleanup_deadline == 10.0
        assert r.keepalive_interval == 60.0
        assert r.spin_loop_window == 2.0
        assert r.spin_loop_threshold == 500

    def test_wrap_streams_returns_guards_and_metrics(self) -> None:
        r = SseResilience(send_timeout=7.0, spin_loop_window=3.0, spin_loop_threshold=99)
        read_inner = MagicMock()
        write_inner = MagicMock()

        gr, gw, metrics = r.wrap_streams(read_inner, write_inner)

        assert isinstance(gr, GuardedReadStream)
        assert isinstance(gw, GuardedWriteStream)
        assert isinstance(metrics, SseStreamMetrics)
        # Verify write stream got the correct config
        assert gw._send_timeout == 7.0
        assert gw._spin_window == 3.0
        assert gw._spin_threshold == 99

    async def test_cleanup_with_deadline_success(self) -> None:
        r = SseResilience(cleanup_deadline=5.0)
        called = False

        async def cleanup() -> None:
            nonlocal called
            called = True

        await r.cleanup_with_deadline(cleanup())
        assert called

    async def test_cleanup_with_deadline_timeout(self) -> None:
        r = SseResilience(cleanup_deadline=0.01)

        async def slow_cleanup() -> None:
            await asyncio.sleep(5.0)

        # Should not raise — swallows timeout and logs warning
        with patch("argus_mcp.server.sse_resilience.logger") as mock_logger:
            await r.cleanup_with_deadline(slow_cleanup())
            mock_logger.warning.assert_called_once()
            assert "exceeded deadline" in mock_logger.warning.call_args[0][0]

    async def test_cleanup_with_deadline_exception(self) -> None:
        r = SseResilience(cleanup_deadline=5.0)

        async def failing_cleanup() -> None:
            raise RuntimeError("boom")

        with patch("argus_mcp.server.sse_resilience.logger") as mock_logger:
            await r.cleanup_with_deadline(failing_cleanup())
            mock_logger.exception.assert_called_once()
            assert "failed" in mock_logger.exception.call_args[0][0]

    def test_log_connection_summary(self) -> None:
        r = SseResilience()
        metrics = SseStreamMetrics(
            messages_sent=100,
            messages_received=50,
            keepalives_sent=3,
            send_timeouts=1,
            spin_loop_warnings=0,
            started_at=time.monotonic() - 10.0,
        )

        with patch("argus_mcp.server.sse_resilience.logger") as mock_logger:
            r.log_connection_summary(metrics, url="http://example.com/sse")
            mock_logger.info.assert_called_once()
            log_msg = mock_logger.info.call_args[0][0]
            assert "sent=" in log_msg
            assert "recv=" in log_msg

    def test_log_connection_summary_no_url(self) -> None:
        r = SseResilience()
        metrics = SseStreamMetrics()

        with patch("argus_mcp.server.sse_resilience.logger") as mock_logger:
            r.log_connection_summary(metrics)
            mock_logger.info.assert_called_once()


#  SseResilienceConfig (Pydantic model)


class TestSseResilienceConfig:
    def test_defaults(self) -> None:
        cfg = SseResilienceConfig()
        assert cfg.enabled is True
        assert cfg.send_timeout == 30.0
        assert cfg.cleanup_deadline == 15.0
        assert cfg.keepalive_interval == 30.0
        assert cfg.spin_loop_window == 1.0
        assert cfg.spin_loop_threshold == 200

    def test_custom_values(self) -> None:
        cfg = SseResilienceConfig(
            enabled=False,
            send_timeout=5.0,
            cleanup_deadline=10.0,
            keepalive_interval=0.0,
            spin_loop_window=0.5,
            spin_loop_threshold=50,
        )
        assert cfg.enabled is False
        assert cfg.send_timeout == 5.0
        assert cfg.cleanup_deadline == 10.0
        assert cfg.keepalive_interval == 0.0
        assert cfg.spin_loop_window == 0.5
        assert cfg.spin_loop_threshold == 50

    def test_send_timeout_too_low(self) -> None:
        with pytest.raises(Exception):  # Pydantic ValidationError
            SseResilienceConfig(send_timeout=0.5)

    def test_send_timeout_too_high(self) -> None:
        with pytest.raises(Exception):
            SseResilienceConfig(send_timeout=500.0)

    def test_spin_loop_threshold_too_low(self) -> None:
        with pytest.raises(Exception):
            SseResilienceConfig(spin_loop_threshold=5)

    def test_argus_config_has_sse_resilience(self) -> None:
        cfg = ArgusConfig()
        assert hasattr(cfg, "sse_resilience")
        assert isinstance(cfg.sse_resilience, SseResilienceConfig)

    def test_argus_config_sse_resilience_custom(self) -> None:
        cfg = ArgusConfig(sse_resilience=SseResilienceConfig(send_timeout=10.0))
        assert cfg.sse_resilience.send_timeout == 10.0
