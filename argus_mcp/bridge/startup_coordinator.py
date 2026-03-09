"""Startup orchestration: staggered launch, retry loop, cancellation.

Extracted from ``ClientManager`` to keep the facade class focused on
lifecycle orchestration while this module owns the startup / retry
algorithm.
"""

import asyncio
import logging
import os
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from argus_mcp.constants import (
    AUTH_DISCOVERY_TIMEOUT,
    BACKEND_RETRIES,
    BACKEND_RETRY_BACKOFF,
    BACKEND_RETRY_DELAY,
    STARTUP_CONCURRENCY,
    STARTUP_STAGGER_DELAY,
)

logger = logging.getLogger(__name__)

# Startup ordering: connect fast transports first, then build+connect stdio.
_TYPE_PRIORITY = {"streamable-http": 0, "sse": 1, "stdio": 2}


# ── Helpers ──────────────────────────────────────────────────────────────


def _sort_backends(
    config_data: Dict[str, Dict[str, Any]],
) -> Tuple[List[Tuple[str, Dict[str, Any]]], List[Tuple[str, Dict[str, Any]]]]:
    """Split and sort backends into (remote, stdio) lists by type priority."""
    sorted_items = sorted(
        config_data.items(),
        key=lambda kv: _TYPE_PRIORITY.get(kv[1].get("type", "stdio"), 2),
    )
    remote = [(n, c) for n, c in sorted_items if c.get("type") != "stdio"]
    stdio = [(n, c) for n, c in sorted_items if c.get("type") == "stdio"]
    return remote, stdio


# ── Launch helpers ───────────────────────────────────────────────────────


def launch_remote_tasks(
    remote_items: List[Tuple[str, Dict[str, Any]]],
    sem: asyncio.Semaphore,
    stagger: float,
    concurrency: int,
    start_one: Callable[..., Awaitable[bool]],
    pending_tasks: Dict[str, "asyncio.Task[Any]"],
) -> Dict[str, "asyncio.Task[Any]"]:
    """Create asyncio tasks for remote backends (concurrent).

    *start_one* is the per-backend connect coroutine
    (``ClientManager._start_backend_svr``).
    """
    remote_tasks: Dict[str, asyncio.Task[Any]] = {}
    for idx, (name, conf) in enumerate(remote_items):

        async def _gated_remote(
            n: str = name,
            c: Dict[str, Any] = conf,
            i: int = idx,
        ) -> bool:
            async with sem:
                if i > 0 and stagger > 0:
                    await asyncio.sleep(stagger * (i % concurrency))
                return await start_one(n, c)

        task = asyncio.create_task(_gated_remote(), name=f"start_{name}")
        remote_tasks[name] = task
        pending_tasks[name] = task
    return remote_tasks


async def build_and_connect_stdio(
    stdio_items: List[Tuple[str, Dict[str, Any]]],
    pre_build: Callable[..., Awaitable[None]],
    start_one: Callable[..., Awaitable[bool]],
    pending_tasks: Dict[str, "asyncio.Task[Any]"],
    shutdown_requested: bool,
) -> Dict[str, bool]:
    """Sequential loop: pre-build image, then connect for each stdio backend."""
    stdio_results: Dict[str, bool] = {}
    for svr_name, svr_conf in stdio_items:
        if shutdown_requested:
            stdio_results[svr_name] = False
            break

        async def _stdio_build_and_connect(
            name: str = svr_name,
            conf: Dict[str, Any] = svr_conf,
        ) -> bool:
            try:
                await pre_build(name, conf)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "[%s] Sequential pre-build failed: %s",
                    name,
                    exc,
                    exc_info=True,
                )
            return await start_one(name, conf)

        task = asyncio.create_task(
            _stdio_build_and_connect(),
            name=f"start_{svr_name}",
        )
        pending_tasks[svr_name] = task
        try:
            ok = await task
            stdio_results[svr_name] = ok
        except asyncio.CancelledError:
            logger.info("[%s] Stdio startup cancelled.", svr_name)
            stdio_results[svr_name] = False
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[%s] Startup task failed with exception '%s'.",
                svr_name,
                type(exc).__name__,
            )
            stdio_results[svr_name] = False
    return stdio_results


async def gather_remote_results(
    remote_tasks: Dict[str, "asyncio.Task[Any]"],
) -> Dict[str, bool]:
    """Await remote tasks and collect pass/fail results."""
    results_map: Dict[str, bool] = {}
    if not remote_tasks:
        return results_map
    results = await asyncio.gather(*remote_tasks.values(), return_exceptions=True)
    for svr_name, result in zip(remote_tasks.keys(), results):
        if isinstance(result, Exception):
            logger.error(
                "[%s] Startup task failed with exception '%s'.",
                svr_name,
                type(result).__name__,
            )
            results_map[svr_name] = False
        else:
            results_map[svr_name] = bool(result)
    return results_map


# ── Auth discovery wait ──────────────────────────────────────────────────


async def await_auth_discoveries(
    failed_names: List[str],
    auth_discovery_tasks: Dict[str, "asyncio.Task[Any]"],
    progress_cb: Optional[Callable[..., None]],
) -> None:
    """Wait for pending auth discovery tasks before retrying."""
    auth_wait_names = [
        n for n in failed_names if n in auth_discovery_tasks and not auth_discovery_tasks[n].done()
    ]
    if not auth_wait_names:
        return

    logger.info(
        "Waiting up to %.0fs for pending auth discovery on %d backend(s): %s",
        AUTH_DISCOVERY_TIMEOUT,
        len(auth_wait_names),
        ", ".join(auth_wait_names),
    )
    pending = [auth_discovery_tasks[n] for n in auth_wait_names]
    for n in auth_wait_names:
        if progress_cb is not None:
            progress_cb(n, "initializing", "Waiting for browser authentication…")
    try:
        await asyncio.wait(pending, timeout=AUTH_DISCOVERY_TIMEOUT)
        for n in auth_wait_names:
            auth_task = auth_discovery_tasks.get(n)
            if auth_task and auth_task.done():
                try:
                    auth_ok = auth_task.result()
                    if auth_ok:
                        logger.info(
                            "[%s] Auth discovery completed — will retry with credentials.",
                            n,
                        )
                        if progress_cb is not None:
                            progress_cb(
                                n,
                                "initializing",
                                "Authenticated — retrying connection\u2026",
                            )
                    else:
                        logger.info(
                            "[%s] Auth discovery finished without credentials.",
                            n,
                        )
                        if progress_cb is not None:
                            progress_cb(
                                n,
                                "initializing",
                                "Authentication incomplete — retrying\u2026",
                            )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Auth discovery failed for '%s': %s", n, exc)
                    if progress_cb is not None:
                        progress_cb(
                            n,
                            "initializing",
                            f"Auth discovery error: {exc}",
                        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Error while waiting for auth discovery tasks: %s", exc)


# ── Retry logic ──────────────────────────────────────────────────────────


def signal_retry_phase(
    failed_names: List[str],
    attempt: int,
    max_retries: int,
    delay: float,
    status_records: Dict[str, Any],
    progress_cb: Optional[Callable[..., None]],
) -> None:
    """Signal RETRYING phase on status records and progress callback."""
    from argus_mcp.runtime.models import BackendPhase

    for svr_name in failed_names:
        record = status_records.get(svr_name)
        if record is not None:
            try:
                record.transition(BackendPhase.RETRYING, f"Retry {attempt}/{max_retries}")
            except ValueError:
                pass
        if progress_cb is not None:
            progress_cb(svr_name, "retrying", f"Retry {attempt}/{max_retries} in {delay:.0f}s…")


async def launch_retry_tasks(
    failed_names: List[str],
    config_data: Dict[str, Dict[str, Any]],
    attempt: int,
    sem: asyncio.Semaphore,
    stagger: float,
    concurrency: int,
    start_one: Callable[..., Awaitable[bool]],
) -> None:
    """Create and await retry tasks for failed backends."""
    retry_tasks: Dict[str, asyncio.Task[Any]] = {}
    retry_idx = 0
    for svr_name in failed_names:
        svr_conf = config_data[svr_name]
        per_backend_retries = svr_conf.get("retries", BACKEND_RETRIES)
        if attempt > per_backend_retries:
            continue

        async def _gated_retry(name: str, conf: Dict[str, Any], idx: int) -> bool:
            async with sem:
                if idx > 0 and stagger > 0:
                    await asyncio.sleep(stagger * (idx % concurrency))
                return await start_one(name, conf)

        task = asyncio.create_task(
            _gated_retry(svr_name, svr_conf, retry_idx),
            name=f"retry_{svr_name}_{attempt}",
        )
        retry_tasks[svr_name] = task
        retry_idx += 1

    if retry_tasks:
        retry_results = await asyncio.gather(*retry_tasks.values(), return_exceptions=True)
        for svr_name, result in zip(retry_tasks.keys(), retry_results):
            if isinstance(result, Exception):
                logger.error(
                    "[%s] Retry %d failed with exception '%s'.",
                    svr_name,
                    attempt,
                    type(result).__name__,
                )
            elif result is True:
                logger.info("[%s] Retry %d succeeded.", svr_name, attempt)


async def retry_failed_backends(
    failed_names: List[str],
    config_data: Dict[str, Dict[str, Any]],
    sessions: Dict[str, Any],
    sem: asyncio.Semaphore,
    stagger: float,
    concurrency: int,
    start_one: Callable[..., Awaitable[bool]],
    status_records: Dict[str, Any],
    auth_discovery_tasks: Dict[str, "asyncio.Task[Any]"],
    progress_cb: Optional[Callable[..., None]],
    shutdown_requested_fn: Callable[[], bool],
) -> None:
    """Retry loop with exponential backoff for backends that failed on first pass."""
    max_retries = max(config_data[n].get("retries", BACKEND_RETRIES) for n in failed_names)
    logger.info(
        "%d backend(s) failed on first attempt — will retry up to %d time(s): %s",
        len(failed_names),
        max_retries,
        ", ".join(failed_names),
    )

    for attempt in range(1, max_retries + 1):
        if not failed_names or shutdown_requested_fn():
            break

        base_delay = max(
            config_data[n].get("retry_delay", BACKEND_RETRY_DELAY) for n in failed_names
        )
        backoff = config_data[failed_names[0]].get("retry_backoff", BACKEND_RETRY_BACKOFF)
        delay = base_delay * (backoff ** (attempt - 1))
        logger.info(
            "Retry attempt %d/%d — waiting %.1fs before retrying %d backend(s)...",
            attempt,
            max_retries,
            delay,
            len(failed_names),
        )

        signal_retry_phase(failed_names, attempt, max_retries, delay, status_records, progress_cb)
        await asyncio.sleep(delay)
        await await_auth_discoveries(failed_names, auth_discovery_tasks, progress_cb)
        await launch_retry_tasks(
            failed_names, config_data, attempt, sem, stagger, concurrency, start_one
        )

        # Refresh the failed list for next iteration
        failed_names = [n for n, ok in {n: n in sessions for n in failed_names}.items() if not ok]
        failed_names = [n for n in failed_names if n not in sessions]


async def start_all(
    config_data: Dict[str, Dict[str, Any]],
    start_one: Callable[..., Awaitable[bool]],
    pre_build: Callable[..., Awaitable[None]],
    sessions: Dict[str, Any],
    pending_tasks: Dict[str, "asyncio.Task[Any]"],
    status_records: Dict[str, Any],
    auth_discovery_tasks: Dict[str, "asyncio.Task[Any]"],
    progress_cb_holder: Any,
    progress_callback: Optional[Callable[..., None]],
    shutdown_requested_fn: Callable[[], bool],
) -> None:
    """Start all backend server connections, retrying failures.

    This is the top-level startup orchestration extracted from
    ``ClientManager.start_all``.
    """
    progress_cb_holder._progress_cb = progress_callback
    total = len(config_data)
    concurrency = max(1, int(os.environ.get("ARGUS_STARTUP_CONCURRENCY", STARTUP_CONCURRENCY)))
    stagger = float(os.environ.get("ARGUS_STARTUP_STAGGER", STARTUP_STAGGER_DELAY))
    logger.info(
        "Starting all backend server connections (%s total, concurrency=%s, stagger=%.1fs)...",
        total,
        concurrency,
        stagger,
    )

    remote_items, stdio_items = _sort_backends(config_data)
    sem = asyncio.Semaphore(concurrency)

    # Phase 1: Launch remotes concurrently + sequential stdio builds
    remote_tasks = launch_remote_tasks(
        remote_items, sem, stagger, concurrency, start_one, pending_tasks
    )
    if remote_tasks:
        await asyncio.sleep(0)

    stdio_results = await build_and_connect_stdio(
        stdio_items, pre_build, start_one, pending_tasks, shutdown_requested_fn()
    )

    # Phase 2: Gather remote results
    remote_results = await gather_remote_results(remote_tasks)

    # Merge all first-pass results
    first_pass = {**remote_results, **stdio_results}
    pending_tasks.clear()

    # Phase 3: Retry failures
    failed_names = [n for n, ok in first_pass.items() if not ok]
    if failed_names and not shutdown_requested_fn():
        await retry_failed_backends(
            failed_names,
            config_data,
            sessions,
            sem,
            stagger,
            concurrency,
            start_one,
            status_records,
            auth_discovery_tasks,
            progress_cb_holder._progress_cb,
            shutdown_requested_fn,
        )

    pending_tasks.clear()
    progress_cb_holder._progress_cb = None

    active_svrs_count = len(sessions)
    total_svrs_count = len(config_data)
    logger.info(
        "All backend startup attempts completed. Active servers: %s/%s",
        active_svrs_count,
        total_svrs_count,
    )
    if active_svrs_count < total_svrs_count:
        logger.warning("Some backend servers failed to start/connect. Check file logs for details.")
