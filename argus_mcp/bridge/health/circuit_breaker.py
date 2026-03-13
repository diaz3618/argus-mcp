"""Circuit breaker state machine for backend servers.

States::

    CLOSED ──(N failures)──► OPEN ──(cooldown)──► HALF_OPEN
       ▲                                              │
       └──────────(probe success)─────────────────────┘
                  (probe fail) ──► OPEN
"""

from __future__ import annotations

import logging
import time
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_FAILURE_THRESHOLD = 3
DEFAULT_COOLDOWN_SECONDS = 60.0


class CircuitState(Enum):
    """States for the circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half-open"


class CircuitBreaker:
    """Per-backend circuit breaker.

    Parameters
    ----------
    name:
        Backend server name (for logging).
    failure_threshold:
        Consecutive failures before opening the circuit.
    cooldown_seconds:
        Seconds to wait in OPEN before transitioning to HALF_OPEN.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds

        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._last_failure_time: float = 0.0
        self._last_success_time: float = 0.0

    @property
    def state(self) -> CircuitState:
        """Current circuit state, with automatic OPEN → HALF_OPEN transition."""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self.cooldown_seconds:
                self._state = CircuitState.HALF_OPEN
                logger.info(
                    "[%s] Circuit breaker: OPEN → HALF_OPEN (cooldown %.1fs elapsed)",
                    self.name,
                    elapsed,
                )
        return self._state

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def allows_request(self) -> bool:
        """Whether the circuit allows traffic.

        CLOSED and HALF_OPEN allow requests; OPEN does not.
        """
        s = self.state  # triggers auto-transition check
        return s in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    def record_success(self) -> None:
        """Record a successful probe/request — closes the circuit."""
        prev = self._state
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._last_success_time = time.monotonic()
        if prev != CircuitState.CLOSED:
            logger.info(
                "[%s] Circuit breaker: %s → CLOSED (success)",
                self.name,
                prev.value,
            )

    def record_failure(self) -> None:
        """Record a failed probe/request — may trip the breaker."""
        self._consecutive_failures += 1
        self._last_failure_time = time.monotonic()

        if (
            self._state in (CircuitState.CLOSED, CircuitState.HALF_OPEN)
            and self._consecutive_failures >= self.failure_threshold
        ):
            prev = self._state
            self._state = CircuitState.OPEN
            logger.warning(
                "[%s] Circuit breaker: %s → OPEN (%d consecutive failures)",
                self.name,
                prev.value,
                self._consecutive_failures,
            )

    def reset(self) -> None:
        """Force-reset to CLOSED (e.g. after manual reconnect)."""
        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        logger.info("[%s] Circuit breaker force-reset to CLOSED", self.name)

    def to_dict(self) -> dict[str, Any]:
        """Snapshot for the management API / TUI."""
        return {
            "state": self.state.value,
            "consecutive_failures": self._consecutive_failures,
            "failure_threshold": self.failure_threshold,
            "cooldown_seconds": self.cooldown_seconds,
        }
