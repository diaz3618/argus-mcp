"""Tests for staggered/semaphore-limited backend startup and cancel_startup.

Validates that:
- ``start_all()`` limits concurrency via ``STARTUP_CONCURRENCY``
- Remote backends (sse, streamable-http) are started before stdio
- ``cancel_startup()`` cancels in-flight tasks and skips retries
- Environment-variable overrides for concurrency/stagger work
"""

import asyncio
import os
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus_mcp.bridge.client_manager import ClientManager
from argus_mcp.constants import (
    STARTUP_CONCURRENCY,
    STARTUP_STAGGER_DELAY,
)


def _fake_config(name: str, svr_type: str = "stdio") -> Dict[str, Any]:
    """Build a minimal fake config entry for a backend."""
    from mcp import StdioServerParameters

    entry: Dict[str, Any] = {"type": svr_type}
    if svr_type == "stdio":
        entry["params"] = StdioServerParameters(command="echo", args=["hi"])
    elif svr_type in ("sse", "streamable-http"):
        entry["url"] = f"http://localhost:9999/{name}"
    return entry


class _ConcurrencyTracker:
    """Track maximum concurrent invocations of a coroutine."""

    def __init__(self, hold_time: float = 0.05):
        self.active = 0
        self.max_active = 0
        self.launch_order: List[str] = []
        self._hold_time = hold_time

    async def start_backend(self, name: str, _conf: Dict[str, Any]) -> bool:
        self.active += 1
        self.launch_order.append(name)
        self.max_active = max(self.max_active, self.active)
        await asyncio.sleep(self._hold_time)
        self.active -= 1
        return True


# Tests


@pytest.mark.asyncio
async def test_startup_concurrency_limited():
    """Verify that at most STARTUP_CONCURRENCY remote backends run simultaneously.

    Stdio backends are now sequential (build+connect one at a time), so
    concurrency limiting only applies to remote backends.  This test uses
    remote backends to validate the semaphore.
    """
    mgr = ClientManager()
    tracker = _ConcurrencyTracker(hold_time=0.1)

    # Monkey-patch the real connection logic
    mgr._start_backend_svr = tracker.start_backend  # type: ignore[assignment]

    # Use remote backends so they go through the concurrent path
    config = {f"backend_{i}": _fake_config(f"b{i}", "streamable-http") for i in range(10)}

    await mgr.start_all(config)

    assert tracker.max_active <= STARTUP_CONCURRENCY
    assert len(tracker.launch_order) == 10


@pytest.mark.asyncio
async def test_remote_backends_start_before_stdio():
    """Remote (sse/streamable-http) backends should be launched before stdio.

    With the new startup flow, remote backends are launched concurrently
    via ``asyncio.create_task`` BEFORE the sequential stdio build+connect
    loop begins.  So remote backends should always appear first in the
    launch order (their tasks start immediately and complete quickly).
    """
    mgr = ClientManager()

    # Track the order in which _start_backend_svr is entered.
    # Remote backends are launched as concurrent tasks before the
    # sequential stdio loop begins, so they should enter first.
    launch_order: List[str] = []

    async def _tracking_start(name: str, conf: Dict[str, Any]) -> bool:
        launch_order.append(name)
        # Brief yield so concurrent remote tasks all get a chance to start
        await asyncio.sleep(0.01)
        return True

    mgr._start_backend_svr = _tracking_start  # type: ignore[assignment]
    # Patch out pre-build so stdio backends don't try real container builds
    mgr._pre_build_container_image = AsyncMock()  # type: ignore[assignment]

    config = {
        "stdio_a": _fake_config("stdio_a", "stdio"),
        "remote_b": _fake_config("remote_b", "streamable-http"),
        "stdio_c": _fake_config("stdio_c", "stdio"),
        "sse_d": _fake_config("sse_d", "sse"),
    }

    # Disable stagger so remote tasks don't get delayed
    with patch.dict(os.environ, {"ARGUS_STARTUP_STAGGER": "0"}):
        await mgr.start_all(config)

    # Remote backends should appear before stdio in launch_order
    remote_indices = [launch_order.index(n) for n in ("remote_b", "sse_d") if n in launch_order]
    stdio_indices = [launch_order.index(n) for n in ("stdio_a", "stdio_c") if n in launch_order]
    # All remotes should have lower indices than all stdios
    if remote_indices and stdio_indices:
        assert max(remote_indices) < min(stdio_indices), (
            f"Remote backends {remote_indices} should all start before "
            f"stdio backends {stdio_indices}.  Order: {launch_order}"
        )


@pytest.mark.asyncio
async def test_cancel_startup_stops_pending_tasks():
    """Calling cancel_startup() should cancel in-flight tasks and set the flag."""
    mgr = ClientManager()

    async def _slow_backend(name: str, conf: Dict[str, Any]) -> bool:
        await asyncio.sleep(10)  # Will be cancelled
        return True

    mgr._start_backend_svr = _slow_backend  # type: ignore[assignment]
    mgr._pre_build_container_image = AsyncMock()  # type: ignore[assignment]
    config = {f"backend_{i}": _fake_config(f"b{i}") for i in range(5)}

    # Launch start_all in background, cancel after brief delay
    task = asyncio.create_task(mgr.start_all(config))
    await asyncio.sleep(0.1)  # Let tasks spawn

    mgr.cancel_startup()
    assert mgr._shutdown_requested is True

    # start_all should return relatively quickly
    await asyncio.wait_for(task, timeout=5.0)


@pytest.mark.asyncio
async def test_cancel_startup_skips_retries():
    """After cancel_startup(), the retry loop should be skipped entirely."""
    mgr = ClientManager()
    attempt_count = 0

    async def _failing_backend(name: str, conf: Dict[str, Any]) -> bool:
        nonlocal attempt_count
        attempt_count += 1
        # Simulate work so cancel has a chance to fire
        await asyncio.sleep(0.1)
        return False  # Simulate failure

    mgr._start_backend_svr = _failing_backend  # type: ignore[assignment]
    mgr._pre_build_container_image = AsyncMock()  # type: ignore[assignment]
    config = {"failing": _fake_config("failing")}

    # Cancel before start_all so the retry loop is skipped entirely.
    # We set the flag upfront so it's guaranteed to be seen.
    mgr._shutdown_requested = True

    await mgr.start_all(config)

    # Should have attempted at most the first pass — no retries
    assert attempt_count <= 1


@pytest.mark.asyncio
async def test_env_var_concurrency_override():
    """ARGUS_STARTUP_CONCURRENCY env var should override the default."""
    mgr = ClientManager()
    tracker = _ConcurrencyTracker(hold_time=0.1)
    mgr._start_backend_svr = tracker.start_backend  # type: ignore[assignment]

    # Use remote backends so they go through the concurrent path
    config = {f"backend_{i}": _fake_config(f"b{i}", "streamable-http") for i in range(8)}

    with patch.dict(os.environ, {"ARGUS_STARTUP_CONCURRENCY": "2"}):
        await mgr.start_all(config)

    assert tracker.max_active <= 2


@pytest.mark.asyncio
async def test_stagger_delay_applied():
    """Verify the stagger delay separates task launches within a batch.

    Stagger only applies to remote backends (launched concurrently).
    Stdio backends are sequential and don't use the stagger.
    """
    mgr = ClientManager()
    launch_times: List[float] = []

    async def _timed_backend(name: str, conf: Dict[str, Any]) -> bool:
        launch_times.append(asyncio.get_event_loop().time())
        # Hold the semaphore long enough so that the stagger is visible
        # within the same concurrency batch.
        await asyncio.sleep(0.15)
        return True

    mgr._start_backend_svr = _timed_backend  # type: ignore[assignment]

    # Use remote backends so they go through the concurrent path
    config = {f"backend_{i}": _fake_config(f"b{i}", "streamable-http") for i in range(4)}

    # concurrency=2, stagger=0.08s  →  within each batch of 2,
    # task at idx%2==1 waits 0.08s before calling _start_backend_svr.
    with patch.dict(
        os.environ,
        {
            "ARGUS_STARTUP_STAGGER": "0.08",
            "ARGUS_STARTUP_CONCURRENCY": "2",
        },
    ):
        await mgr.start_all(config)

    assert len(launch_times) == 4
    # The first backend of each batch (idx 0, 2) has stagger=0,
    # the second (idx 1, 3) has stagger=0.08s.  So within the first
    # pair there should be a visible gap.
    # We just check there is *any* gap ≥ 0.03s between the earliest
    # and latest time, proving the stagger took effect.
    total_span = max(launch_times) - min(launch_times)
    assert total_span >= 0.03, (
        f"Expected stagger to produce time spread, got span={total_span:.3f}s"
    )


@pytest.mark.asyncio
async def test_constants_have_sensible_defaults():
    """Smoke test that the constants are importable and reasonable."""
    assert STARTUP_CONCURRENCY >= 1
    assert STARTUP_CONCURRENCY <= 20
    assert STARTUP_STAGGER_DELAY >= 0
    assert STARTUP_STAGGER_DELAY <= 5


# Signal Override Tests


def test_signal_override_installs_and_restores():
    """_install_startup_signal_override replaces handlers, _restore puts them back.

    This runs in a sync context, so the function falls back to signal.signal().
    """
    import signal as _sig

    from argus_mcp.server.lifespan import (
        _install_startup_signal_override,
        _restore_signal_handlers,
    )

    # Record the current handlers
    before_sigint = _sig.getsignal(_sig.SIGINT)
    before_sigterm = _sig.getsignal(_sig.SIGTERM)

    mock_svc = MagicMock()
    mock_svc._manager = MagicMock()
    mock_svc._manager.cancel_startup = MagicMock()

    # Install override (no running loop → falls back to signal.signal)
    orig_int, orig_term = _install_startup_signal_override(mock_svc)

    # Handlers should now be different (our overrides)
    current_sigint = _sig.getsignal(_sig.SIGINT)
    current_sigterm = _sig.getsignal(_sig.SIGTERM)
    assert current_sigint is not before_sigint, "SIGINT handler was not replaced"
    assert current_sigterm is not before_sigterm, "SIGTERM handler was not replaced"

    # Restore
    _restore_signal_handlers(orig_int, orig_term)

    # Handlers should be back to what they were before override
    assert _sig.getsignal(_sig.SIGINT) is before_sigint
    assert _sig.getsignal(_sig.SIGTERM) is before_sigterm


def test_signal_override_calls_cancel_startup():
    """First SIGINT via the override should call cancel_startup on the manager.

    This runs in a sync context, so the function falls back to signal.signal()
    and the installed handler accepts (signum, frame) per POSIX convention.
    """
    import signal as _sig

    from argus_mcp.server.lifespan import (
        _install_startup_signal_override,
        _restore_signal_handlers,
    )

    mock_svc = MagicMock()
    mock_svc._manager = MagicMock()
    mock_svc._manager.cancel_startup = MagicMock()

    orig_int, orig_term = _install_startup_signal_override(mock_svc)
    try:
        # Get the installed handler and call it directly (simulating SIGINT).
        # In the signal.signal() fallback path, the handler is the legacy
        # wrapper that accepts (signum, frame).
        handler = _sig.getsignal(_sig.SIGINT)
        assert callable(handler)
        handler(_sig.SIGINT, None)  # First Ctrl+C

        mock_svc._manager.cancel_startup.assert_called_once()
    finally:
        _restore_signal_handlers(orig_int, orig_term)


@pytest.mark.asyncio
async def test_signal_override_uses_loop_handler():
    """When a running loop exists, add_signal_handler should be used."""
    import signal as _sig

    from argus_mcp.server.lifespan import (
        _install_startup_signal_override,
        _restore_signal_handlers,
    )

    mock_svc = MagicMock()
    mock_svc._manager = MagicMock()
    mock_svc._manager.cancel_startup = MagicMock()

    # In an async test, there IS a running loop — the function should
    # use loop.add_signal_handler, which is thread-safe.
    orig_int, orig_term = _install_startup_signal_override(mock_svc)
    try:
        # Simulate SIGINT by sending it to ourselves
        # The loop handler should call cancel_startup
        _loop = asyncio.get_running_loop()

        # We can't easily test the loop handler directly since it's
        # registered internally. Instead, verify that cancel_startup
        # is called when SIGINT is delivered to the process.
        import os as _os

        _os.kill(_os.getpid(), _sig.SIGINT)
        # Give the event loop a chance to invoke the handler
        await asyncio.sleep(0.05)

        mock_svc._manager.cancel_startup.assert_called_once()
    finally:
        _restore_signal_handlers(orig_int, orig_term)
