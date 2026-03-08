"""Shared asyncio task utilities.

Provides a done-callback that logs unhandled exceptions from
fire-and-forget ``asyncio.Task`` instances, preventing silent failures.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


def _log_task_exception(task: asyncio.Task) -> None:  # type: ignore[type-arg]
    """Done-callback: log unhandled exceptions from background tasks."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logger.error(
            "Background task %s failed: %s",
            task.get_name(),
            exc,
            exc_info=exc,
        )
