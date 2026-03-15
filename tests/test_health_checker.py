"""Tests for argus_mcp.bridge.health.checker — Health checker.

Covers:
- HealthState enum values
- BackendHealth initial state and to_dict
- HealthChecker start/stop lifecycle
- _check probes and state transitions
- Circuit breaker integration
- Capability hiding/restoring on unhealthy/recovered
- Status record synchronization
- State change notification callback
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from argus_mcp.bridge.health.checker import (
    BackendHealth,
    HealthChecker,
    HealthState,
)
from argus_mcp.bridge.health.circuit_breaker import CircuitBreaker, CircuitState


class TestHealthState:
    def test_values(self) -> None:
        assert HealthState.HEALTHY.value == "healthy"
        assert HealthState.DEGRADED.value == "degraded"
        assert HealthState.UNHEALTHY.value == "unhealthy"
        assert HealthState.UNKNOWN.value == "unknown"

    def test_all_states_present(self) -> None:
        states = {s.value for s in HealthState}
        assert states == {"healthy", "degraded", "unhealthy", "unknown"}


class TestBackendHealth:
    def test_initial_state(self) -> None:
        cb = CircuitBreaker("test")
        h = BackendHealth(circuit=cb)
        assert h.state == HealthState.UNKNOWN
        assert h.last_check == 0.0
        assert h.last_latency_ms == 0.0
        assert h.last_error is None

    def test_to_dict(self) -> None:
        cb = CircuitBreaker("test")
        h = BackendHealth(circuit=cb)
        h.state = HealthState.HEALTHY
        h.last_latency_ms = 42.567
        d = h.to_dict()
        assert d["state"] == "healthy"
        assert d["last_latency_ms"] == 42.57  # rounded
        assert d["last_error"] is None
        assert "circuit" in d


class TestHealthCheckerLifecycle:
    @pytest.mark.asyncio
    async def test_start_creates_task(self) -> None:
        manager = MagicMock()
        manager.get_all_sessions.return_value = {}
        registry = MagicMock()

        hc = HealthChecker(manager, registry, interval=0.01)
        hc.start()
        assert hc._task is not None
        assert not hc._task.done()

        await hc.stop()
        assert hc._task is None

    @pytest.mark.asyncio
    async def test_double_start_is_safe(self) -> None:
        manager = MagicMock()
        manager.get_all_sessions.return_value = {}
        registry = MagicMock()

        hc = HealthChecker(manager, registry, interval=0.01)
        hc.start()
        task1 = hc._task
        hc.start()  # should not create a new task
        assert hc._task is task1

        await hc.stop()

    @pytest.mark.asyncio
    async def test_stop_without_start(self) -> None:
        manager = MagicMock()
        registry = MagicMock()
        hc = HealthChecker(manager, registry)
        await hc.stop()  # should not raise


class TestHealthCheckerProbing:
    @pytest.mark.asyncio
    async def test_healthy_probe(self) -> None:
        """Successful probe → HEALTHY."""
        session = AsyncMock()
        session.list_tools = AsyncMock(return_value=MagicMock())

        manager = MagicMock()
        manager.get_all_sessions.return_value = {"backend-1": session}
        manager.get_session.return_value = session
        manager.get_status_record.return_value = None

        registry = MagicMock()
        registry.remove_backend = MagicMock(return_value=0)

        hc = HealthChecker(
            manager,
            registry,
            interval=9999,  # we'll call _check directly
            probe_timeout=5.0,
        )
        await hc._check("backend-1")

        health = hc.get_health("backend-1")
        assert health is not None
        assert health.state == HealthState.HEALTHY
        assert health.last_error is None

    @pytest.mark.asyncio
    async def test_failed_probe_degraded(self) -> None:
        """Failed probe (but below threshold) → DEGRADED."""
        session = AsyncMock()
        session.list_tools = AsyncMock(side_effect=ConnectionError("refused"))

        manager = MagicMock()
        manager.get_all_sessions.return_value = {"b1": session}
        manager.get_session.return_value = session
        manager.get_status_record.return_value = None

        registry = MagicMock()
        registry.remove_backend = MagicMock(return_value=0)

        hc = HealthChecker(
            manager,
            registry,
            interval=9999,
            failure_threshold=3,  # needs 3 failures to open
        )
        await hc._check("b1")
        health = hc.get_health("b1")
        assert health is not None
        assert health.state == HealthState.DEGRADED

    @pytest.mark.asyncio
    async def test_no_session_marks_unhealthy(self) -> None:
        manager = MagicMock()
        manager.get_all_sessions.return_value = {"b1": None}
        manager.get_session.return_value = None
        manager.get_status_record.return_value = None

        registry = MagicMock()
        registry.remove_backend = MagicMock(return_value=0)

        hc = HealthChecker(manager, registry, interval=9999)
        await hc._check("b1")
        health = hc.get_health("b1")
        assert health.state == HealthState.UNHEALTHY
        assert "No active session" in health.last_error

    @pytest.mark.asyncio
    async def test_state_change_callback(self) -> None:
        session = AsyncMock()
        session.list_tools = AsyncMock(return_value=MagicMock())

        manager = MagicMock()
        manager.get_all_sessions.return_value = {"b1": session}
        manager.get_session.return_value = session
        manager.get_status_record.return_value = None

        registry = MagicMock()
        registry.remove_backend = MagicMock(return_value=0)

        callback = MagicMock()
        hc = HealthChecker(manager, registry, interval=9999, on_state_change=callback)

        await hc._check("b1")
        # UNKNOWN → HEALTHY should trigger callback
        callback.assert_called_once()
        args = callback.call_args[0]
        assert args[0] == "b1"
        assert args[1] == HealthState.UNKNOWN
        assert args[2] == HealthState.HEALTHY


class TestHealthCheckerManagement:
    def test_get_health_unknown_backend(self) -> None:
        manager = MagicMock()
        registry = MagicMock()
        hc = HealthChecker(manager, registry)
        assert hc.get_health("nonexistent") is None

    def test_get_all_health_empty(self) -> None:
        manager = MagicMock()
        registry = MagicMock()
        hc = HealthChecker(manager, registry)
        assert hc.get_all_health() == {}

    @pytest.mark.asyncio
    async def test_reset_backend(self) -> None:
        session = AsyncMock()
        session.list_tools = AsyncMock(side_effect=ConnectionError())

        manager = MagicMock()
        manager.get_all_sessions.return_value = {"b1": session}
        manager.get_session.return_value = session
        manager.get_status_record.return_value = None

        registry = MagicMock()
        registry.remove_backend = MagicMock(return_value=0)

        hc = HealthChecker(manager, registry, interval=9999, failure_threshold=1)
        await hc._check("b1")
        health = hc.get_health("b1")
        assert health.circuit.state == CircuitState.OPEN

        hc.reset_backend("b1")
        assert health.circuit.state == CircuitState.CLOSED
        assert health.state == HealthState.UNKNOWN


class TestHealthCheckerCapabilityVisibility:
    @pytest.mark.asyncio
    async def test_unhealthy_hides_capabilities(self) -> None:
        """When a probe fails and circuit opens, capabilities are removed.

        Note: the session=None early-return path does NOT reach the
        hide/restore block. We must use a session whose list_tools raises
        so that the except branch sets UNHEALTHY *and* falls through to
        _hide_backend_capabilities.
        """
        session = AsyncMock()
        session.list_tools = AsyncMock(side_effect=ConnectionError("gone"))

        manager = MagicMock()
        manager.get_session.return_value = session
        manager.get_status_record.return_value = None

        registry = MagicMock()
        registry.remove_backend = MagicMock(return_value=3)

        hc = HealthChecker(manager, registry, interval=9999, failure_threshold=1)
        await hc._check("b1")
        health = hc.get_health("b1")
        assert health.state == HealthState.UNHEALTHY
        registry.remove_backend.assert_called_with("b1")

    @pytest.mark.asyncio
    async def test_no_session_does_not_reach_hide(self) -> None:
        """When session is None, _check returns early before hide/restore."""
        manager = MagicMock()
        manager.get_session.return_value = None
        manager.get_status_record.return_value = None

        registry = MagicMock()
        registry.remove_backend = MagicMock()

        hc = HealthChecker(manager, registry, interval=9999, failure_threshold=1)
        await hc._check("b1")
        health = hc.get_health("b1")
        assert health.state == HealthState.UNHEALTHY
        registry.remove_backend.assert_not_called()

    @pytest.mark.asyncio
    async def test_recovered_restores_capabilities(self) -> None:
        """When recovering from UNHEALTHY, capabilities are re-discovered."""
        session = AsyncMock()
        session.list_tools = AsyncMock(return_value=MagicMock())

        manager = MagicMock()
        manager.get_session.return_value = session
        manager.get_status_record.return_value = None

        registry = MagicMock()
        registry.remove_backend = MagicMock(return_value=0)
        registry.discover_single_backend = AsyncMock()

        hc = HealthChecker(manager, registry, interval=9999, failure_threshold=1)

        # First: make it UNHEALTHY via probe failure
        session.list_tools = AsyncMock(side_effect=ConnectionError("down"))
        await hc._check("b1")
        health = hc.get_health("b1")
        assert health.state == HealthState.UNHEALTHY

        # Reset circuit for recovery test
        health.circuit.reset()

        # Now: make it respond → HEALTHY (recovering from UNHEALTHY)
        session.list_tools = AsyncMock(return_value=MagicMock())
        manager.get_session.return_value = session
        await hc._check("b1")
        assert health.state == HealthState.HEALTHY
