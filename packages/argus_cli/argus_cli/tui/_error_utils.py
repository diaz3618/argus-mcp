"""Shared error-handling utilities for Argus MCP.

Provides helpers that replace overly broad ``except Exception: pass`` patterns
with narrower, type-safe alternatives.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, TypeVar, overload

if TYPE_CHECKING:
    from textual.widget import Widget

T = TypeVar("T", bound="Widget")
_F = TypeVar("_F", bound=Callable[..., object])

_logger = logging.getLogger(__name__)


@overload
def safe_query(
    host: Widget,
    selector: str,
    expect_type: type[T],
) -> T | None: ...


@overload
def safe_query(
    host: Widget,
    selector: str,
) -> Widget | None: ...


def safe_query(
    host: Widget,
    selector: str,
    expect_type: type[T] | None = None,
) -> T | None | Widget | None:
    """Query a single widget, returning *None* instead of raising.

    Catches only ``textual.css.query.NoMatches`` — anything else propagates.
    """
    from textual.css.query import NoMatches

    try:
        if expect_type is not None:
            return host.query_one(selector, expect_type)
        return host.query_one(selector)
    except NoMatches:
        return None


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
            except Exception:
                logger.log(level, "%s in %s", message, fn.__qualname__, exc_info=True)
                return default

        return wrapper  # type: ignore[return-value]

    return decorator
