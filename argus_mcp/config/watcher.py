"""Async config file watcher with debounce.

Watches the config file for modifications and triggers a reload
callback after a debounce period.  Uses ``asyncio`` polling (stat-based)
rather than ``watchdog`` to avoid an extra dependency.  A polling
interval of 2 seconds keeps overhead negligible while detecting changes
within a few seconds.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Awaitable, Callable, Optional

from argus_mcp._task_utils import _log_task_exception

logger = logging.getLogger(__name__)

DEFAULT_POLL_INTERVAL: float = 2.0
DEFAULT_DEBOUNCE: float = 1.0


class ConfigWatcher:
    """Poll-based async config file watcher.

    Parameters
    ----------
    config_path:
        Absolute path to the config file to watch.
    on_change:
        Async callback invoked when the file changes (after debounce).
        Receives no arguments; typically calls ``service.reload()``.
    poll_interval:
        Seconds between ``os.stat`` polls.
    debounce:
        Seconds to wait after last detected change before invoking
        the callback.  Editors often perform multiple rapid writes;
        the debounce collapses them into a single reload.
    """

    def __init__(
        self,
        config_path: str,
        on_change: Callable[[], Awaitable[Any]],
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        debounce: float = DEFAULT_DEBOUNCE,
    ) -> None:
        self._path = config_path
        self._on_change = on_change
        self._poll_interval = poll_interval
        self._debounce = debounce

        self._task: Optional[asyncio.Task[None]] = None
        self._last_mtime: float = 0.0
        self._stop_event = asyncio.Event()

    # ── Lifecycle ────────────────────────────────────────────────────

    def start(self) -> None:
        """Begin watching.  Safe to call multiple times."""
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._last_mtime = self._current_mtime()
        self._task = asyncio.create_task(self._poll_loop(), name="config-watcher")
        self._task.add_done_callback(_log_task_exception)
        logger.info("Config watcher started: %s", self._path)

    async def stop(self) -> None:
        """Stop watching and await task cleanup."""
        self._stop_event.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Config watcher stopped.")

    @property
    def watching(self) -> bool:
        return self._task is not None and not self._task.done()

    # ── Internal ─────────────────────────────────────────────────────

    def _current_mtime(self) -> float:
        try:
            return os.stat(self._path).st_mtime
        except OSError:
            return 0.0

    async def _poll_loop(self) -> None:
        """Poll the config file and trigger reload on change."""
        while not self._stop_event.is_set():
            try:
                await asyncio.sleep(self._poll_interval)
            except asyncio.CancelledError:
                return

            mtime = self._current_mtime()
            if mtime == 0.0:
                continue  # file missing / inaccessible

            if mtime != self._last_mtime:
                logger.debug(
                    "Config change detected (mtime %.3f → %.3f), debouncing...",
                    self._last_mtime,
                    mtime,
                )
                self._last_mtime = mtime
                # Debounce: wait, then re-check for further edits
                await asyncio.sleep(self._debounce)
                new_mtime = self._current_mtime()
                if new_mtime != mtime:
                    # Another change happened during debounce — restart loop
                    self._last_mtime = new_mtime
                    continue

                try:
                    logger.info("Config file changed, triggering reload...")
                    await self._on_change()
                except Exception:
                    logger.exception("Error in config-change callback.")
