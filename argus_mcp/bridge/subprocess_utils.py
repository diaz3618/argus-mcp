"""Subprocess lifecycle management for backend MCP servers.

Extracted from :pymod:`argus_mcp.bridge.client_manager` to reduce that
module's complexity.  Provides async context managers and helpers for
spawning, logging, and terminating child processes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional

from argus_mcp._task_utils import _log_task_exception
from argus_mcp.errors import ConfigurationError

logger = logging.getLogger(__name__)

try:
    import httpx

    SSE_NET_EXCS: tuple[type, ...] = (
        httpx.ConnectError,
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
    )
except ImportError:
    SSE_NET_EXCS = ()


async def log_subproc_stream(
    stream: Optional[asyncio.StreamReader], svr_name: str, stream_name: str
) -> None:
    """Asynchronously read and log lines from subprocess streams."""
    if not stream:
        return
    while True:  # nosemgrep: mcp-unbounded-tool-loop
        try:
            line_bytes = await stream.readline()
            if not line_bytes:
                logger.debug("[%s-%s] Stream ended (EOF).", svr_name, stream_name)
                break
            line = line_bytes.decode(errors="replace").strip()
            if line:
                logger.info("[%s-%s] %s", svr_name, stream_name, line)
        except asyncio.CancelledError:
            logger.debug("[%s-%s] Logging task was cancelled.", svr_name, stream_name)
            break
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "[%s-%s] Error while reading stream: %s",
                svr_name,
                stream_name,
                exc,
                exc_info=True,
            )
            break


async def cancel_stream_loggers(
    svr_name: str,
    stdout_task: Optional[asyncio.Task[None]],
    stderr_task: Optional[asyncio.Task[None]],
) -> None:
    """Cancel and await subprocess stream logging tasks."""
    if stdout_task and not stdout_task.done():
        stdout_task.cancel()
    if stderr_task and not stderr_task.done():
        stderr_task.cancel()
    if stdout_task or stderr_task:
        tasks_to_await = [t for t in (stdout_task, stderr_task) if t is not None]
        await asyncio.gather(*tasks_to_await, return_exceptions=True)
        logger.debug("[%s] Subprocess stream logging tasks completed.", svr_name)


async def terminate_subproc(
    svr_name: str,
    process: asyncio.subprocess.Process,
) -> None:
    """Gracefully terminate a subprocess, escalating to kill on timeout."""
    logger.info("[%s] Attempting to terminate local process (PID: %s)...", svr_name, process.pid)
    try:
        process.terminate()
        await asyncio.wait_for(process.wait(), timeout=3.0)
        logger.info("[%s] Local process (PID: %s) terminated successfully.", svr_name, process.pid)
    except asyncio.TimeoutError:
        logger.warning(
            "[%s] Timeout while terminating local process (PID: %s), trying kill...",
            svr_name,
            process.pid,
        )
        process.kill()
        await process.wait()
        logger.info("[%s] Local process (PID: %s) was force-killed.", svr_name, process.pid)
    except ProcessLookupError:
        logger.warning(
            "[%s] Local process not found while terminating (PID: %s).", svr_name, process.pid
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[%s] Error terminating local process (PID: %s): %s",
            svr_name,
            process.pid,
            exc,
            exc_info=True,
        )


@asynccontextmanager
async def manage_subproc(
    cmd_to_exec: str,
    args: List[str],
    proc_env: Optional[Dict[str, str]],
    svr_name: str,
) -> AsyncGenerator[asyncio.subprocess.Process, None]:
    """Async context manager for starting and stopping subprocesses."""
    process: Optional[asyncio.subprocess.Process] = None
    stdout_log_task: Optional[asyncio.Task[None]] = None
    stderr_log_task: Optional[asyncio.Task[None]] = None
    actual_cmd = cmd_to_exec

    try:
        py_exec = sys.executable or "python"
        actual_cmd = py_exec if cmd_to_exec.lower() == "python" else cmd_to_exec

        logger.info(
            "[%s] Preparing to start local process: '%s' args: %s",
            svr_name,
            actual_cmd,
            args,
        )

        current_env = os.environ.copy()
        if proc_env:
            current_env.update(proc_env)

        process = await asyncio.create_subprocess_exec(
            actual_cmd,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=current_env,
        )
        logger.info("[%s] Local process started (PID: %s).", svr_name, process.pid)

        if process.stdout:
            stdout_log_task = asyncio.create_task(
                log_subproc_stream(process.stdout, svr_name, "stdout"),
                name=f"{svr_name}_stdout_logger",
            )
            stdout_log_task.add_done_callback(_log_task_exception)
        if process.stderr:
            stderr_log_task = asyncio.create_task(
                log_subproc_stream(process.stderr, svr_name, "stderr"),
                name=f"{svr_name}_stderr_logger",
            )
            stderr_log_task.add_done_callback(_log_task_exception)
        yield process

    except FileNotFoundError:
        logger.debug(
            "[%s] Failed to start local process: command '%s' not found.",
            svr_name,
            actual_cmd,
            exc_info=True,
        )
        raise
    except Exception:  # noqa: BLE001
        logger.debug(
            "[%s] Unexpected error starting local process '%s'.",
            svr_name,
            actual_cmd,
            exc_info=True,
        )
        raise
    finally:
        await cancel_stream_loggers(svr_name, stdout_log_task, stderr_log_task)
        if process and process.returncode is None:
            await terminate_subproc(svr_name, process)


def log_backend_fail(
    svr_name: str,
    svr_type: Optional[str],
    e: Any,
    context: str = "startup",
) -> None:
    """Helper to log backend startup/connection failures."""
    svr_type_str = svr_type or "unknown type"
    if isinstance(e, asyncio.TimeoutError):
        logger.error("[%s] (%s) %s timed out.", svr_name, svr_type_str, context)
    elif isinstance(e, ConfigurationError):
        logger.error(
            "[%s] (%s) Configuration error during %s: %s",
            svr_name,
            svr_type_str,
            context,
            e,
        )
    elif isinstance(e, (*SSE_NET_EXCS, ConnectionRefusedError, BrokenPipeError, ConnectionError)):
        logger.error(
            "[%s] (%s) Network/connection error during %s: %s: %s",
            svr_name,
            svr_type_str,
            context,
            type(e).__name__,
            e,
        )
    elif isinstance(e, FileNotFoundError):
        logger.error(
            "[%s] (local launch %s) Command or file not found '%s' during %s.",
            svr_name,
            svr_type_str,
            e.filename,
            context,
        )
    else:
        logger.exception(
            "[%s] (%s) Unexpected fatal error during %s.",
            svr_name,
            svr_type_str,
            context,
        )
