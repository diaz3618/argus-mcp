"""Tests for argus_mcp.bridge.health.circuit_breaker — Circuit breaker state machine.

Covers:
- Initial state (CLOSED, 0 failures)
- State transitions: CLOSED → OPEN → HALF_OPEN → CLOSED
- Failure accumulation and threshold
- Cooldown timer for OPEN → HALF_OPEN
- allows_request for each state
- record_success resets to CLOSED
- record_failure in HALF_OPEN → OPEN
- Force reset
- Serialization (to_dict)
"""

from __future__ import annotations

import time

from argus_mcp.bridge.health.circuit_breaker import (
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_FAILURE_THRESHOLD,
    CircuitBreaker,
    CircuitState,
)


class TestCircuitBreakerInitialState:
    def test_starts_closed(self) -> None:
        cb = CircuitBreaker("test-backend")
        assert cb.state == CircuitState.CLOSED

    def test_zero_failures(self) -> None:
        cb = CircuitBreaker("test")
        assert cb.consecutive_failures == 0

    def test_allows_request(self) -> None:
        cb = CircuitBreaker("test")
        assert cb.allows_request is True

    def test_default_thresholds(self) -> None:
        cb = CircuitBreaker("test")
        assert cb.failure_threshold == DEFAULT_FAILURE_THRESHOLD
        assert cb.cooldown_seconds == DEFAULT_COOLDOWN_SECONDS

    def test_custom_thresholds(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=5, cooldown_seconds=30.0)
        assert cb.failure_threshold == 5
        assert cb.cooldown_seconds == 30.0


class TestCircuitBreakerFailures:
    def test_single_failure_stays_closed(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        assert cb.consecutive_failures == 1

    def test_threshold_failures_opens(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.consecutive_failures == 3

    def test_more_than_threshold_stays_open(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=2)
        for _ in range(5):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.consecutive_failures == 5

    def test_open_blocks_requests(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=9999)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allows_request is False


class TestCircuitBreakerHalfOpen:
    def test_transitions_after_cooldown(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=0.01)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        # Wait for cooldown
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allows_request is True

    def test_success_in_half_open_closes(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=0.01)
        cb.record_failure()
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.consecutive_failures == 0

    def test_failure_in_half_open_reopens(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=0.01)
        cb.record_failure()
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN

        cb.record_failure()
        assert cb.state == CircuitState.OPEN


class TestCircuitBreakerSuccess:
    def test_success_resets_failures(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=5)
        cb.record_failure()
        cb.record_failure()
        assert cb.consecutive_failures == 2

        cb.record_success()
        assert cb.consecutive_failures == 0
        assert cb.state == CircuitState.CLOSED

    def test_success_from_closed_stays_closed(self) -> None:
        cb = CircuitBreaker("test")
        cb.record_success()
        assert cb.state == CircuitState.CLOSED


class TestCircuitBreakerReset:
    def test_force_reset_from_open(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=9999)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.consecutive_failures == 0

    def test_force_reset_from_closed(self) -> None:
        cb = CircuitBreaker("test")
        cb.record_failure()
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.consecutive_failures == 0


class TestCircuitBreakerSerialization:
    def test_to_dict(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=3, cooldown_seconds=60.0)
        d = cb.to_dict()
        assert d["state"] == "closed"
        assert d["consecutive_failures"] == 0
        assert d["failure_threshold"] == 3
        assert d["cooldown_seconds"] == 60.0

    def test_to_dict_after_failures(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=2, cooldown_seconds=9999)
        cb.record_failure()
        cb.record_failure()
        d = cb.to_dict()
        assert d["state"] == "open"
        assert d["consecutive_failures"] == 2

    def test_to_dict_half_open(self) -> None:
        cb = CircuitBreaker("test", failure_threshold=1, cooldown_seconds=0.01)
        cb.record_failure()
        time.sleep(0.02)
        d = cb.to_dict()
        assert d["state"] == "half-open"


class TestCircuitBreakerEdgeCases:
    def test_failure_threshold_of_one(self) -> None:
        """Single failure should open immediately."""
        cb = CircuitBreaker("test", failure_threshold=1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_name_stored(self) -> None:
        cb = CircuitBreaker("my-backend")
        assert cb.name == "my-backend"
