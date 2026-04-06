"""Shared error-handling utilities for Argus MCP.

Provides helpers that replace overly broad ``except Exception: pass`` patterns
with narrower, type-safe alternatives.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import TypeVar, cast

_F = TypeVar("_F", bound=Callable[..., object])

_logger = logging.getLogger(__name__)


def log_on_exception(
    logger: logging.Logger,
    *,
    message: str = "Unexpected error",
    level: int = logging.DEBUG,
    default: object = None,
) -> Callable[[_F], _F]:
    """Decorator: catch *Exception*, log it, and return *default*.

    Use for best-effort operations where failure should be logged but not
    propagate (e.g. UI updates, non-critical background work).
    """

    def decorator(fn: _F) -> _F:
        @functools.wraps(fn)
        def wrapper(*args: object, **kwargs: object) -> object:
            try:
                return fn(*args, **kwargs)
            except Exception:  # noqa: BLE001
                logger.log(level, "%s in %s", message, fn.__qualname__, exc_info=True)
                return default

        return cast(_F, wrapper)

    return decorator
