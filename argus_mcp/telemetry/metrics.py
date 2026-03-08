"""Metrics helpers — counters and histograms.

Wraps the OpenTelemetry metrics API with safe fallbacks.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    from opentelemetry import metrics as otel_metrics

    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False

_METER_NAME = "argus_mcp"

# Module-level references (initialised lazily)
_request_counter: Any = None
_request_duration: Any = None
_error_counter: Any = None


def get_meter() -> Any:
    """Return the Argus MCP meter (or a no-op proxy)."""
    if not _HAS_OTEL:
        return _NoOpMeter()
    return otel_metrics.get_meter(_METER_NAME)


def _ensure_instruments() -> None:
    """Create metric instruments on first use."""
    global _request_counter, _request_duration, _error_counter

    if _request_counter is not None:
        return

    if not _HAS_OTEL:
        _request_counter = _NoOpCounter()
        _request_duration = _NoOpHistogram()
        _error_counter = _NoOpCounter()
        return

    meter = otel_metrics.get_meter(_METER_NAME)
    _request_counter = meter.create_counter(
        "argus_mcp.requests_total",
        description="Total MCP requests processed",
    )
    _request_duration = meter.create_histogram(
        "argus_mcp.request_duration_seconds",
        description="MCP request duration in seconds",
        unit="s",
    )
    _error_counter = meter.create_counter(
        "argus_mcp.errors_total",
        description="Total MCP request errors",
    )


def record_request(
    *,
    tool_name: str,
    backend: str,
    duration_ms: float,
    success: bool,
) -> None:
    """Record metrics for a completed MCP request."""
    _ensure_instruments()

    attrs = {"tool": tool_name, "backend": backend}
    _request_counter.add(1, attrs)
    _request_duration.record(duration_ms / 1000.0, attrs)

    if not success:
        _error_counter.add(1, attrs)


# ── No-op fallbacks ─────────────────────────────────────────────────────


class _NoOpCounter:
    def add(self, _amount: int, attributes: Optional[dict[str, Any]] = None) -> None:
        pass


class _NoOpHistogram:
    def record(self, value: float, attributes: Optional[dict[str, Any]] = None) -> None:
        pass


class _NoOpMeter:
    def create_counter(self, name: str, **kwargs: Any) -> _NoOpCounter:
        return _NoOpCounter()

    def create_histogram(self, name: str, **kwargs: Any) -> _NoOpHistogram:
        return _NoOpHistogram()
