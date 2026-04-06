"""Rust-accelerated circuit breaker with Python fallback."""

from __future__ import annotations

from argus_mcp.bridge.health.circuit_breaker import CircuitState

RUST_AVAILABLE = False

try:
    from circuit_breaker_rs import RustCircuitBreaker as _RawRustCB

    class CircuitBreaker:
        def __init__(
            self,
            name: str,
            failure_threshold: int = 3,
            cooldown_seconds: float = 60.0,
        ) -> None:
            self._inner = _RawRustCB(name, failure_threshold, cooldown_seconds)

        @property
        def name(self) -> str:
            return self._inner.name

        @property
        def failure_threshold(self) -> int:
            return self._inner.failure_threshold

        @property
        def cooldown_seconds(self) -> float:
            return self._inner.cooldown_seconds

        @property
        def state(self) -> CircuitState:
            return CircuitState(self._inner.state)

        @property
        def consecutive_failures(self) -> int:
            return self._inner.consecutive_failures

        @property
        def allows_request(self) -> bool:
            return self._inner.allows_request

        def record_success(self) -> None:
            return self._inner.record_success()

        def record_failure(self) -> None:
            return self._inner.record_failure()

        def reset(self) -> None:
            return self._inner.reset()

        def to_dict(self) -> dict:
            return self._inner.to_dict()

    RUST_AVAILABLE = True
except ImportError:
    from argus_mcp.bridge.health.circuit_breaker import CircuitBreaker  # type: ignore[assignment]

__all__ = ["CircuitBreaker", "RUST_AVAILABLE"]
