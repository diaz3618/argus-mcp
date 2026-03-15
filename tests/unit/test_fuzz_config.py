"""Fuzz / property-based tests for configuration schema models.

Uses Hypothesis to generate randomised inputs that exercise Pydantic
``Field(ge=…, le=…)`` constraints on RetryConfig, SseResilienceConfig,
SessionPoolConfig, HttpPoolConfig, AuditConfig, and the top-level
``ArgusConfig.backends`` name validator.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from argus_mcp.config.schema import (
    ArgusConfig,
    AuditConfig,
    HttpPoolConfig,
    RetryConfig,
    SessionPoolConfig,
    SseResilienceConfig,
)

pytestmark = [pytest.mark.fuzz]


# Hypothesis strategies ───────────────────────────────────────────────

# Finite floats excluding NaN/Inf (Pydantic rejects them).
_finite_float = st.floats(allow_nan=False, allow_infinity=False)
_finite_pos_float = st.floats(min_value=0.0, allow_nan=False, allow_infinity=False)
_any_int = st.integers()


# RetryConfig ─────────────────────────────────────────────────────────


class TestRetryConfigFuzz:
    """Property tests for RetryConfig field constraints."""

    @given(
        max_retries=st.integers(min_value=0, max_value=10),
        base_delay=st.floats(min_value=0.1, max_value=30.0, allow_nan=False, allow_infinity=False),
        backoff_factor=st.floats(
            min_value=1.0, max_value=10.0, allow_nan=False, allow_infinity=False
        ),
        max_delay=st.floats(min_value=1.0, max_value=300.0, allow_nan=False, allow_infinity=False),
        jitter=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_valid_ranges_accepted(
        self,
        max_retries: int,
        base_delay: float,
        backoff_factor: float,
        max_delay: float,
        jitter: float,
    ) -> None:
        cfg = RetryConfig(
            max_retries=max_retries,
            base_delay=base_delay,
            backoff_factor=backoff_factor,
            max_delay=max_delay,
            jitter=jitter,
        )
        assert 0 <= cfg.max_retries <= 10
        assert 0.1 <= cfg.base_delay <= 30.0
        assert 1.0 <= cfg.backoff_factor <= 10.0
        assert 1.0 <= cfg.max_delay <= 300.0
        assert 0.0 <= cfg.jitter <= 1.0

    @given(max_retries=st.integers(min_value=11, max_value=10000))
    @settings(max_examples=50)
    def test_max_retries_above_upper_bound_rejected(self, max_retries: int) -> None:
        with pytest.raises(ValidationError):
            RetryConfig(max_retries=max_retries)

    @given(max_retries=st.integers(min_value=-10000, max_value=-1))
    @settings(max_examples=50)
    def test_max_retries_below_lower_bound_rejected(self, max_retries: int) -> None:
        with pytest.raises(ValidationError):
            RetryConfig(max_retries=max_retries)

    @given(
        base_delay=st.floats(min_value=30.01, max_value=1e6, allow_nan=False, allow_infinity=False)
    )
    @settings(max_examples=50)
    def test_base_delay_above_upper_bound_rejected(self, base_delay: float) -> None:
        with pytest.raises(ValidationError):
            RetryConfig(base_delay=base_delay)

    @given(jitter=st.floats(min_value=1.01, max_value=1e6, allow_nan=False, allow_infinity=False))
    @settings(max_examples=50)
    def test_jitter_above_upper_bound_rejected(self, jitter: float) -> None:
        with pytest.raises(ValidationError):
            RetryConfig(jitter=jitter)


# SseResilienceConfig ─────────────────────────────────────────────────


class TestSseResilienceConfigFuzz:
    """Property tests for SseResilienceConfig field constraints."""

    @given(
        send_timeout=st.floats(
            min_value=1.0, max_value=300.0, allow_nan=False, allow_infinity=False
        ),
        cleanup_deadline=st.floats(
            min_value=1.0, max_value=120.0, allow_nan=False, allow_infinity=False
        ),
        keepalive_interval=st.floats(
            min_value=0.0, max_value=600.0, allow_nan=False, allow_infinity=False
        ),
        spin_loop_window=st.floats(
            min_value=0.1, max_value=30.0, allow_nan=False, allow_infinity=False
        ),
        spin_loop_threshold=st.integers(min_value=10, max_value=10000),
    )
    @settings(max_examples=200)
    def test_valid_ranges_accepted(
        self,
        send_timeout: float,
        cleanup_deadline: float,
        keepalive_interval: float,
        spin_loop_window: float,
        spin_loop_threshold: int,
    ) -> None:
        cfg = SseResilienceConfig(
            send_timeout=send_timeout,
            cleanup_deadline=cleanup_deadline,
            keepalive_interval=keepalive_interval,
            spin_loop_window=spin_loop_window,
            spin_loop_threshold=spin_loop_threshold,
        )
        assert 1.0 <= cfg.send_timeout <= 300.0
        assert 1.0 <= cfg.cleanup_deadline <= 120.0
        assert 0.0 <= cfg.keepalive_interval <= 600.0

    @given(
        send_timeout=st.floats(
            min_value=300.01, max_value=1e6, allow_nan=False, allow_infinity=False
        )
    )
    @settings(max_examples=50)
    def test_send_timeout_above_upper_bound_rejected(self, send_timeout: float) -> None:
        with pytest.raises(ValidationError):
            SseResilienceConfig(send_timeout=send_timeout)

    @given(
        send_timeout=st.floats(
            min_value=-1e6, max_value=0.99, allow_nan=False, allow_infinity=False
        )
    )
    @settings(max_examples=50)
    def test_send_timeout_below_lower_bound_rejected(self, send_timeout: float) -> None:
        with pytest.raises(ValidationError):
            SseResilienceConfig(send_timeout=send_timeout)

    @given(spin_loop_threshold=st.integers(min_value=-1000, max_value=9))
    @settings(max_examples=50)
    def test_spin_loop_threshold_below_lower_bound_rejected(self, spin_loop_threshold: int) -> None:
        with pytest.raises(ValidationError):
            SseResilienceConfig(spin_loop_threshold=spin_loop_threshold)


# SessionPoolConfig ───────────────────────────────────────────────────


class TestSessionPoolConfigFuzz:
    """Property tests for SessionPoolConfig field constraints."""

    @given(
        per_key_max=st.integers(min_value=1, max_value=64),
        ttl=st.floats(min_value=10.0, max_value=3600.0, allow_nan=False, allow_infinity=False),
        circuit_breaker_threshold=st.integers(min_value=1, max_value=50),
    )
    @settings(max_examples=100)
    def test_valid_ranges_accepted(
        self, per_key_max: int, ttl: float, circuit_breaker_threshold: int
    ) -> None:
        cfg = SessionPoolConfig(
            per_key_max=per_key_max,
            ttl=ttl,
            circuit_breaker_threshold=circuit_breaker_threshold,
        )
        assert 1 <= cfg.per_key_max <= 64
        assert 10.0 <= cfg.ttl <= 3600.0
        assert 1 <= cfg.circuit_breaker_threshold <= 50

    @given(per_key_max=st.integers(min_value=65, max_value=10000))
    @settings(max_examples=30)
    def test_per_key_max_above_upper_bound_rejected(self, per_key_max: int) -> None:
        with pytest.raises(ValidationError):
            SessionPoolConfig(per_key_max=per_key_max)


# HttpPoolConfig ──────────────────────────────────────────────────────


class TestHttpPoolConfigFuzz:
    """Property tests for HttpPoolConfig field constraints."""

    @given(
        max_connections=st.integers(min_value=1, max_value=2000),
        max_keepalive=st.integers(min_value=0, max_value=2000),
        timeout=st.floats(min_value=1.0, max_value=300.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_valid_ranges_accepted(
        self, max_connections: int, max_keepalive: int, timeout: float
    ) -> None:
        cfg = HttpPoolConfig(
            max_connections=max_connections,
            max_keepalive=max_keepalive,
            timeout=timeout,
        )
        assert 1 <= cfg.max_connections <= 2000
        assert 0 <= cfg.max_keepalive <= 2000
        assert 1.0 <= cfg.timeout <= 300.0


# AuditConfig ─────────────────────────────────────────────────────────


class TestAuditConfigFuzz:
    """Property tests for AuditConfig field constraints."""

    @given(
        max_size_mb=st.integers(min_value=1, max_value=10000),
        backup_count=st.integers(min_value=0, max_value=10000),
    )
    @settings(max_examples=100)
    def test_valid_ranges_accepted(self, max_size_mb: int, backup_count: int) -> None:
        cfg = AuditConfig(max_size_mb=max_size_mb, backup_count=backup_count)
        assert cfg.max_size_mb >= 1
        assert cfg.backup_count >= 0

    @given(max_size_mb=st.integers(min_value=-10000, max_value=0))
    @settings(max_examples=30)
    def test_max_size_mb_below_lower_bound_rejected(self, max_size_mb: int) -> None:
        with pytest.raises(ValidationError):
            AuditConfig(max_size_mb=max_size_mb)


# ArgusConfig.backends name validation ────────────────────────────────


class TestArgusConfigBackendNameFuzz:
    """Property tests for ArgusConfig backend name validator."""

    @given(name=st.text(min_size=1).filter(lambda s: s.strip() == s and s.strip()))
    @settings(max_examples=100)
    def test_non_empty_trimmed_names_accepted(self, name: str) -> None:
        # Build a minimal stdio backend for the name
        backends = {
            name: {
                "type": "stdio",
                "command": "echo",
                "args": ["hello"],
            }
        }
        cfg = ArgusConfig(backends=backends)
        assert name in cfg.backends

    @given(
        core=st.text(
            min_size=1, alphabet=st.characters(blacklist_categories=("Zs", "Cc", "Zl", "Zp", "Cs"))
        ),
        pad=st.sampled_from([" ", "\t", "\n", "  ", "\t\t"]),
        side=st.sampled_from(["left", "right", "both"]),
    )
    @settings(max_examples=50)
    def test_names_with_whitespace_padding_rejected(self, core: str, pad: str, side: str) -> None:
        if side == "left":
            name = pad + core
        elif side == "right":
            name = core + pad
        else:
            name = pad + core + pad
        backends = {
            name: {
                "type": "stdio",
                "command": "echo",
                "args": ["hello"],
            }
        }
        with pytest.raises(ValidationError, match="whitespace"):
            ArgusConfig(backends=backends)

    def test_empty_backend_name_rejected(self) -> None:
        backends = {
            "": {
                "type": "stdio",
                "command": "echo",
                "args": ["hello"],
            }
        }
        with pytest.raises(ValidationError, match="non-empty"):
            ArgusConfig(backends=backends)

    def test_whitespace_only_name_rejected(self) -> None:
        backends = {
            "   ": {
                "type": "stdio",
                "command": "echo",
                "args": ["hello"],
            }
        }
        with pytest.raises(ValidationError):
            ArgusConfig(backends=backends)
