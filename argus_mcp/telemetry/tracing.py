"""Distributed tracing helpers.

Wraps the OpenTelemetry tracing API with safe fallbacks when
OTel is not installed.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Generator, Optional

logger = logging.getLogger(__name__)

try:
    from opentelemetry import trace

    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False

_TRACER_NAME = "argus_mcp"


def get_tracer() -> Any:
    """Return the Argus MCP tracer (or a no-op proxy)."""
    if not _HAS_OTEL:
        return _NoOpTracer()
    return trace.get_tracer(_TRACER_NAME)


@contextmanager
def start_span(
    name: str,
    attributes: Optional[dict[str, Any]] = None,
) -> Generator[Any, None, None]:
    """Context manager that starts a trace span.

    When OTel is not installed, yields a no-op span.
    """
    if not _HAS_OTEL:
        yield _NoOpSpan()
        return

    tracer = trace.get_tracer(_TRACER_NAME)
    with tracer.start_as_current_span(name, attributes=attributes or {}) as span:
        yield span


# ── No-op fallbacks ─────────────────────────────────────────────────────


class _NoOpSpan:
    """Dummy span when OTel is not installed."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, *args: Any, **kwargs: Any) -> None:
        pass

    def record_exception(self, exc: Exception) -> None:
        pass

    def end(self) -> None:
        pass


class _NoOpTracer:
    """Dummy tracer when OTel is not installed."""

    @contextmanager
    def start_as_current_span(self, name: str, **kwargs: Any) -> Generator[_NoOpSpan, None, None]:
        yield _NoOpSpan()
