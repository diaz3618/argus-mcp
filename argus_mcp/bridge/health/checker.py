"""Periodic health checker for backend MCP servers.

Runs an asyncio background task that probes each backend at a configurable
interval, updates circuit breaker state, and dynamically shows/hides
capabilities in the registry based on health.
"""

from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import Any, Callable, Dict, Optional

from argus_mcp._task_utils import _log_task_exception
from argus_mcp.bridge.health.circuit_breaker import CircuitBreaker, CircuitState

logger = logging.getLogger(__name__)

DEFAULT_CHECK_INTERVAL = 30.0  # seconds
DEFAULT_PROBE_TIMEOUT = 10.0  # seconds
DEFAULT_DEGRADED_LATENCY_MS = 5000.0  # threshold for "degraded"


class HealthState(Enum):
    """Observed health of a backend."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class BackendHealth:
    """Mutable health record for one backend."""

    __slots__ = (
        "state",
        "circuit",
        "last_check",
        "last_latency_ms",
        "last_error",
    )

    def __init__(self, circuit: CircuitBreaker) -> None:
        self.state: HealthState = HealthState.UNKNOWN
        self.circuit: CircuitBreaker = circuit
        self.last_check: float = 0.0
        self.last_latency_ms: float = 0.0
        self.last_error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state.value,
            "circuit": self.circuit.to_dict(),
            "last_check": self.last_check,
            "last_latency_ms": round(self.last_latency_ms, 2),
            "last_error": self.last_error,
        }


class HealthChecker:
    """Background health-check scheduler.

    Parameters
    ----------
    manager:
        The :class:`ClientManager` instance — used to obtain sessions.
    registry:
        The :class:`CapabilityRegistry` instance — used to hide/show caps.
    interval:
        Seconds between health check rounds (default 30).
    probe_timeout:
        Seconds to wait for a probe response (default 10).
    failure_threshold:
        Consecutive failures before a circuit opens (default 3).
    cooldown:
        Seconds before an open circuit transitions to half-open (default 60).
    degraded_latency_ms:
        Probe latency above this is "degraded" (default 5000).
    on_state_change:
        Optional callback ``(backend_name, old_state, new_state)`` for events.
    """

    def __init__(
        self,
        manager: Any,
        registry: Any,
        *,
        interval: float = DEFAULT_CHECK_INTERVAL,
        probe_timeout: float = DEFAULT_PROBE_TIMEOUT,
        failure_threshold: int = 3,
        cooldown: float = 60.0,
        degraded_latency_ms: float = DEFAULT_DEGRADED_LATENCY_MS,
        on_state_change: Optional[Callable[..., Any]] = None,
    ) -> None:
        self._manager = manager
        self._registry = registry
        self._interval = interval
        self._probe_timeout = probe_timeout
        self._failure_threshold = failure_threshold
        self._cooldown = cooldown
        self._degraded_latency_ms = degraded_latency_ms
        self._on_state_change = on_state_change

        self._health: Dict[str, BackendHealth] = {}
        self._task: Optional[asyncio.Task[None]] = None
        self._background_tasks: set[asyncio.Task[None]] = set()
        self._stopped = asyncio.Event()

    def start(self) -> None:
        """Launch the background check loop."""
        if self._task is not None and not self._task.done():
            logger.warning("Health checker already running.")
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name="health-checker")
        self._task.add_done_callback(_log_task_exception)
        logger.info(
            "Health checker started (interval=%.0fs, probe_timeout=%.0fs)",
            self._interval,
            self._probe_timeout,
        )

    async def stop(self) -> None:
        """Signal the loop to stop and wait for it."""
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Health checker stopped.")

    def get_health(self, name: str) -> Optional[BackendHealth]:
        """Get health record for a backend (or ``None``)."""
        return self._health.get(name)

    def get_all_health(self) -> Dict[str, BackendHealth]:
        """Return a snapshot of all health records."""
        return dict(self._health)

    def reset_backend(self, name: str) -> None:
        """Force-reset a backend's circuit to CLOSED."""
        h = self._health.get(name)
        if h is not None:
            h.circuit.reset()
            h.state = HealthState.UNKNOWN
            logger.info("[%s] Health reset by operator", name)

    async def _run(self) -> None:
        """Periodically probe all backends."""
        while not self._stopped.is_set():
            # Gather backend names from the manager's sessions
            sessions = self._manager.get_all_sessions()
            if sessions:
                await asyncio.gather(
                    *(self._check(name) for name in sessions),
                    return_exceptions=True,
                )
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._interval)
                break  # stopped was set
            except asyncio.TimeoutError:
                pass  # interval elapsed, loop again

    async def _check(self, name: str) -> None:
        """Probe a single backend and update state."""
        health = self._health.get(name)
        if health is None:
            cb = CircuitBreaker(
                name,
                failure_threshold=self._failure_threshold,
                cooldown_seconds=self._cooldown,
            )
            health = BackendHealth(circuit=cb)
            self._health[name] = health

        # If circuit is OPEN (and hasn't auto-transitioned), skip
        if not health.circuit.allows_request:
            return

        old_state = health.state
        session = self._manager.get_session(name)
        if session is None:
            health.state = HealthState.UNHEALTHY
            health.last_error = "No active session"
            health.circuit.record_failure()
            health.last_check = time.monotonic()
            self._sync_status_record(name, health)
            self._notify(name, old_state, health.state)
            return

        start = time.monotonic()
        try:
            # MCP has no dedicated ping — use list_tools as a lightweight probe
            await asyncio.wait_for(session.list_tools(), timeout=self._probe_timeout)
            latency_ms = (time.monotonic() - start) * 1000.0
            health.last_latency_ms = latency_ms
            health.last_error = None
            health.circuit.record_success()

            if latency_ms > self._degraded_latency_ms:
                health.state = HealthState.DEGRADED
            else:
                health.state = HealthState.HEALTHY

        except Exception as exc:  # noqa: BLE001
            health.last_error = f"{type(exc).__name__}: {exc}"
            health.circuit.record_failure()
            if health.circuit.state == CircuitState.OPEN:
                health.state = HealthState.UNHEALTHY
            else:
                # Still accumulating failures
                health.state = HealthState.DEGRADED

        health.last_check = time.monotonic()

        # Dynamic capability visibility
        if health.state == HealthState.UNHEALTHY:
            self._hide_backend_capabilities(name)
        elif old_state == HealthState.UNHEALTHY and health.state in (
            HealthState.HEALTHY,
            HealthState.DEGRADED,
        ):
            self._restore_backend_capabilities(name)

        # Sync phase to BackendStatusRecord
        self._sync_status_record(name, health)

        self._notify(name, old_state, health.state)

    def _sync_status_record(self, name: str, health: BackendHealth) -> None:
        """Update the BackendStatusRecord phase from health check results."""
        record = self._manager.get_status_record(name)
        if record is None:
            return

        from argus_mcp.runtime.models import BackendPhase

        # Map HealthState → BackendPhase
        phase_map = {
            HealthState.HEALTHY: BackendPhase.READY,
            HealthState.DEGRADED: BackendPhase.DEGRADED,
            HealthState.UNHEALTHY: BackendPhase.FAILED,
        }
        target_phase = phase_map.get(health.state)
        if target_phase is None or target_phase == record.phase:
            return

        # Build a descriptive message
        if health.state == HealthState.DEGRADED:
            msg = f"High latency: {health.last_latency_ms:.0f}ms"
        elif health.state == HealthState.UNHEALTHY:
            msg = health.last_error or "Health check failed"
        else:
            msg = f"Healthy ({health.last_latency_ms:.0f}ms)"

        try:
            record.transition(target_phase, msg)
            record.last_latency_ms = health.last_latency_ms
        except ValueError:
            # Invalid transition (e.g. SHUTTING_DOWN → READY) — add condition only
            record.add_condition(
                "HealthCheck",
                "Warning",
                f"Skipped transition to {target_phase.value}: {msg}",
            )

    def _hide_backend_capabilities(self, name: str) -> None:
        """Remove a backend's capabilities from the exposed lists."""
        if self._registry is None:
            return
        removed = self._registry.remove_backend(name)
        if removed > 0:
            logger.warning(
                "[%s] Unhealthy — removed %d capabilities from registry",
                name,
                removed,
            )

    def _restore_backend_capabilities(self, name: str) -> None:
        """Re-discover and add a backend's capabilities."""
        if self._registry is None or self._manager is None:
            return
        session = self._manager.get_session(name)
        if session is None:
            return
        # Schedule async re-discovery as a task to not block the checker
        task = asyncio.create_task(
            self._registry.discover_single_backend(name, session),
            name=f"restore-caps-{name}",
        )
        task.add_done_callback(_log_task_exception)
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)
        logger.info("[%s] Recovered — scheduling capability re-discovery", name)

    def _notify(self, name: str, old: HealthState, new: HealthState) -> None:
        if old != new and self._on_state_change is not None:
            try:
                self._on_state_change(name, old, new)
            except Exception:  # noqa: BLE001
                logger.debug("[%s] on_state_change callback error", name, exc_info=True)
