"""Rust-accelerated circuit breaker with Python fallback."""

from __future__ import annotations

RUST_AVAILABLE = False

try:
    from circuit_breaker_rs import RustCircuitBreaker as CircuitBreaker

    RUST_AVAILABLE = True
except ImportError:
    from argus_mcp.bridge.health.circuit_breaker import CircuitBreaker

__all__ = ["CircuitBreaker", "RUST_AVAILABLE"]
