"""Backend MCP server connection management."""

import asyncio
import logging
import os
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional, Tuple

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from argus_mcp._task_utils import _log_task_exception

try:
    import httpx

    SSE_NET_EXCS: tuple = (
        httpx.ConnectError,
        httpx.TimeoutException,
        httpx.NetworkError,
        httpx.ReadTimeout,
        httpx.WriteTimeout,
        httpx.PoolTimeout,
    )
except ImportError:
    SSE_NET_EXCS = ()

from argus_mcp.constants import (
    BACKEND_RETRIES,
    BACKEND_RETRY_BACKOFF,
    BACKEND_RETRY_DELAY,
    MCP_INIT_TIMEOUT,
    SSE_LOCAL_START_DELAY,
    STARTUP_CONCURRENCY,
    STARTUP_STAGGER_DELAY,
    STARTUP_TIMEOUT,
    STDIO_MCP_INIT_TIMEOUT,
)
from argus_mcp.errors import BackendServerError, ConfigurationError

logger = logging.getLogger(__name__)


async def _log_subproc_stream(
    stream: Optional[asyncio.StreamReader], svr_name: str, stream_name: str
) -> None:
    """Asynchronously read and log lines from subprocess streams."""
    if not stream:
        return
    while True:
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
        except Exception as e_stream:
            logger.error(
                "[%s-%s] Error while reading stream: %s",
                svr_name,
                stream_name,
                e_stream,
                exc_info=True,
            )
            break


@asynccontextmanager
async def _manage_subproc(
    cmd_to_exec: str,
    args: List[str],
    proc_env: Optional[Dict[str, str]],
    svr_name: str,
) -> AsyncGenerator[asyncio.subprocess.Process, None]:
    """Async context manager for starting and stopping subprocesses."""
    process: Optional[asyncio.subprocess.Process] = None
    stdout_log_task: Optional[asyncio.Task] = None
    stderr_log_task: Optional[asyncio.Task] = None
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
                _log_subproc_stream(process.stdout, svr_name, "stdout"),
                name=f"{svr_name}_stdout_logger",
            )
            stdout_log_task.add_done_callback(_log_task_exception)
        if process.stderr:
            stderr_log_task = asyncio.create_task(
                _log_subproc_stream(process.stderr, svr_name, "stderr"),
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
    except Exception:
        logger.debug(
            "[%s] Unexpected error starting local process '%s'.",
            svr_name,
            actual_cmd,
            exc_info=True,
        )
        raise
    finally:
        if stdout_log_task and not stdout_log_task.done():
            stdout_log_task.cancel()
        if stderr_log_task and not stderr_log_task.done():
            stderr_log_task.cancel()

        if stdout_log_task or stderr_log_task:
            await asyncio.gather(stdout_log_task, stderr_log_task, return_exceptions=True)
            logger.debug("[%s] Subprocess stream logging tasks completed.", svr_name)

        if process and process.returncode is None:
            logger.info(
                "[%s] Attempting to terminate local process (PID: %s)...",
                svr_name,
                process.pid,
            )
            try:
                process.terminate()
                await asyncio.wait_for(process.wait(), timeout=3.0)
                logger.info(
                    "[%s] Local process (PID: %s) terminated successfully.",
                    svr_name,
                    process.pid,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "[%s] Timeout while terminating local process (PID: %s), trying kill...",
                    svr_name,
                    process.pid,
                )
                process.kill()
                await process.wait()
                logger.info(
                    "[%s] Local process (PID: %s) was force-killed.",
                    svr_name,
                    process.pid,
                )
            except ProcessLookupError:
                logger.warning(
                    "[%s] Local process not found while terminating (PID: %s).",
                    svr_name,
                    process.pid,
                )
            except Exception as e_term:
                logger.error(
                    "[%s] Error terminating local process (PID: %s): %s",
                    svr_name,
                    process.pid,
                    e_term,
                    exc_info=True,
                )


def _log_backend_fail(
    svr_name: str,
    svr_type: Optional[str],
    e: Exception,
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


class ClientManager:
    """Manages connections and sessions for all backend MCP servers."""

    def __init__(self) -> None:
        self._sessions: Dict[str, ClientSession] = {}
        self._pending_tasks: Dict[str, asyncio.Task] = {}
        self._exit_stack = AsyncExitStack()
        self._backend_stacks: Dict[str, AsyncExitStack] = {}
        self._devnull_files: list = []
        self._status_records: Dict[str, Any] = {}
        self._progress_cb: Optional[Callable[..., None]] = None
        self._shutdown_requested: bool = False
        # Auth configs discovered at runtime (PKCE/OAuth auto-discovery).
        # Keyed by backend name → auth config dict suitable for
        # ``create_auth_provider``.
        self._discovered_auth: Dict[str, Dict[str, Any]] = {}
        # Track ongoing auth discovery tasks per backend.  Used to
        # prevent duplicate DCR registrations and PKCE flows when the
        # retry loop fires while interactive browser auth is pending.
        self._auth_discovery_tasks: Dict[str, asyncio.Task] = {}
        self._current_build_name: Optional[str] = None
        logger.info("ClientManager initialized.")

    def cancel_startup(self) -> None:
        """Cancel all pending startup tasks (safe to call from signal handler).

        Sets an internal flag so that ``start_all`` skips retries and
        cancels any in-flight connection tasks.  The cancel is
        cooperative — tasks will raise ``asyncio.CancelledError`` on
        their next ``await`` and ``asyncio.gather`` will collect them
        cleanly because ``return_exceptions=True`` is used.
        """
        self._shutdown_requested = True
        cancelled = 0
        for task in list(self._pending_tasks.values()):
            if not task.done():
                task.cancel()
                cancelled += 1
        if cancelled:
            logger.info(
                "cancel_startup: cancelled %d pending startup task(s).",
                cancelled,
            )

    @staticmethod
    def _apply_network_env(
        svr_name: str,
        svr_conf: Dict[str, Any],
        params: StdioServerParameters,
    ) -> StdioServerParameters:
        """Inject HTTP_PROXY / NO_PROXY env vars from network isolation config.

        If the backend config contains a ``network`` section, the proxy
        and bypass settings are merged into the subprocess environment.
        Unknown ``network_mode`` values are silently ignored (host mode).
        """
        net_cfg = svr_conf.get("network")
        if not isinstance(net_cfg, dict):
            return params

        mode = net_cfg.get("network_mode", "host")
        if mode == "host":
            return params  # no restrictions

        # Merge existing env into a mutable copy
        env = dict(params.env or {})

        if mode == "none":
            # Block all outbound HTTP via a dummy proxy
            env.setdefault("HTTP_PROXY", "http://0.0.0.0:0")
            env.setdefault("HTTPS_PROXY", "http://0.0.0.0:0")
            env.setdefault("NO_PROXY", "")
            logger.info("[%s] Network isolation: mode=none (offline).", svr_name)
        elif mode == "bridge":
            http_proxy = net_cfg.get("http_proxy", "")
            no_proxy = net_cfg.get("no_proxy", "localhost,127.0.0.1")
            if http_proxy:
                env["HTTP_PROXY"] = http_proxy
                env["HTTPS_PROXY"] = http_proxy
            if no_proxy:
                env["NO_PROXY"] = no_proxy
            logger.info(
                "[%s] Network isolation: mode=bridge, proxy=%s, no_proxy=%s.",
                svr_name,
                http_proxy or "(inherit)",
                no_proxy,
            )
        else:
            logger.debug("[%s] Unknown network_mode '%s'; skipping.", svr_name, mode)
            return params

        return StdioServerParameters(
            command=params.command,
            args=list(params.args) if params.args else [],
            env=env if env else None,
        )

    async def _init_stdio_backend(
        self,
        svr_name: str,
        stdio_cfg: StdioServerParameters,
        stack: Optional[AsyncExitStack] = None,
    ) -> Tuple[Any, ClientSession]:
        """Initialize and connect to a stdio backend server."""
        _stack = stack or self._exit_stack
        logger.debug("[%s] Stdio backend, preparing stdio_client.", svr_name)

        # Suppress subprocess stderr so it does not corrupt the TUI.
        # The MCP SDK defaults errlog=sys.stderr, which writes directly
        # to fd 2 — the same fd Textual uses for rendering.  Sending a
        # devnull file-object prevents any backend process output from
        # bleeding through.
        devnull = open(os.devnull, "w")  # noqa: SIM115
        self._devnull_files.append(devnull)
        transport_ctx = stdio_client(stdio_cfg, errlog=devnull)
        streams = await _stack.enter_async_context(transport_ctx)
        logger.debug("[%s] (stdio) transport streams established.", svr_name)

        session_ctx = ClientSession(*streams)
        session = await _stack.enter_async_context(session_ctx)
        return transport_ctx, session

    async def _init_sse_backend(
        self,
        svr_name: str,
        sse_url: str,
        sse_cmd: Optional[str],
        sse_cmd_args: List[str],
        sse_cmd_env: Optional[Dict[str, str]],
        sse_startup_delay: float = SSE_LOCAL_START_DELAY,
        headers: Optional[Dict[str, str]] = None,
        stack: Optional[AsyncExitStack] = None,
    ) -> Tuple[Any, ClientSession]:
        """Initialize and connect to an SSE backend; launch command first if configured."""
        _stack = stack or self._exit_stack
        if sse_cmd:
            logger.info(
                "[%s] Local launch command configured, starting SSE subprocess...",
                svr_name,
            )
            await _stack.enter_async_context(
                _manage_subproc(sse_cmd, sse_cmd_args, sse_cmd_env, svr_name)
            )
            logger.info(
                "[%s] Waiting %ss for local SSE server startup...",
                svr_name,
                sse_startup_delay,
            )
            await asyncio.sleep(sse_startup_delay)

        transport_ctx = sse_client(url=sse_url, headers=headers)
        streams = await _stack.enter_async_context(transport_ctx)
        logger.debug("[%s] (sse) transport streams established.", svr_name)

        session_ctx = ClientSession(*streams)
        session = await _stack.enter_async_context(session_ctx)
        return transport_ctx, session

    async def _init_streamablehttp_backend(
        self,
        svr_name: str,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        stack: Optional[AsyncExitStack] = None,
    ) -> Tuple[Any, ClientSession]:
        """Initialize and connect to a streamable-http backend server."""
        _stack = stack or self._exit_stack
        logger.debug("[%s] Streamable-HTTP backend, url=%s", svr_name, url)
        transport_ctx = streamablehttp_client(url=url, headers=headers)
        read_stream, write_stream, _get_session_id = await _stack.enter_async_context(transport_ctx)
        logger.debug("[%s] (streamable-http) transport streams established.", svr_name)

        session_ctx = ClientSession(read_stream, write_stream)
        session = await _stack.enter_async_context(session_ctx)
        return transport_ctx, session

    def _record_failure(
        self,
        svr_name: str,
        record: Any,
        msg: str,
    ) -> None:
        """Transition a status record to FAILED and notify progress display."""
        from argus_mcp.runtime.models import BackendPhase

        try:
            record.transition(BackendPhase.FAILED, msg)
        except ValueError:
            pass
        if self._progress_cb is not None:
            self._progress_cb(svr_name, "failed", msg)

    def _ensure_status_record(self, svr_name: str) -> Any:
        """Return (or create) the status record for *svr_name*."""
        from argus_mcp.runtime.models import BackendStatusRecord

        record = self._status_records.get(svr_name)
        if record is None:
            record = BackendStatusRecord(name=svr_name)
            self._status_records[svr_name] = record
        return record

    async def _handle_cancelled_error(
        self,
        svr_name: str,
        svr_conf: Dict[str, Any],
        svr_type: Optional[str],
    ) -> str:
        """Determine the failure reason for a CancelledError."""
        if self._shutdown_requested:
            logger.info(
                "[%s] (%s) startup cancelled (shutdown requested).",
                svr_name,
                svr_type or "unknown type",
            )
            return "Startup cancelled (shutdown requested)"

        cancel_reason = (
            "Connection rejected — possible auth failure "
            "(OAuth/API key). Attempting auto-discovery…"
        )
        logger.warning(
            "[%s] (%s) startup task cancelled — possible auth "
            "failure. Will attempt OAuth auto-discovery.",
            svr_name,
            svr_type or "unknown type",
        )
        return await self._attempt_auth_discovery_for_backend(
            svr_name,
            svr_conf,
            svr_type,
            cancel_reason,
        )

    async def _handle_base_exception(
        self,
        svr_name: str,
        svr_conf: Dict[str, Any],
        svr_type: Optional[str],
        e_start: BaseException,
    ) -> str:
        """Determine the failure reason for a BaseException (incl. ExceptionGroup)."""
        fail_reason = str(e_start)
        is_auth_failure = _looks_like_auth_failure(e_start)

        if is_auth_failure and not self._shutdown_requested:
            logger.warning(
                "[%s] (%s) connection failed with auth-related error: "
                "%s. Attempting OAuth auto-discovery.",
                svr_name,
                svr_type or "unknown type",
                type(e_start).__name__,
            )
            return await self._attempt_auth_discovery_for_backend(
                svr_name,
                svr_conf,
                svr_type,
                fail_reason,
            )

        _log_backend_fail(
            svr_name,
            svr_type,
            e_start,
            context="connect/initialize",
        )
        return fail_reason

    async def _start_backend_svr(self, svr_name: str, svr_conf: Dict[str, Any]) -> bool:
        """Start and initialize a single backend server connection.

        For stdio backends the flow is:

        1. **Image build phase** — builds a container image if the command
           is uvx/npx and no cached image exists.  There is NO overall
           timeout for stdio backends; builds take as long as they take.
           The user can Ctrl+C to cancel.
        2. **Connection phase** — spawns the subprocess (or ``docker run``)
           and initialises the MCP session.  A generous
           ``STDIO_MCP_INIT_TIMEOUT`` (60s) is applied only to the
           ``session.initialize()`` call after the process is running.

        Remote backends (SSE, streamable-http) keep an overall
        ``startup_timeout`` (default ``STARTUP_TIMEOUT`` = 90s) wrapping
        the entire spawn + init sequence.
        """
        svr_type = svr_conf.get("type")
        logger.info("[%s] Attempting connection, type: %s...", svr_name, svr_type)

        startup_timeout: Optional[float] = None
        if svr_type != "stdio":
            startup_timeout = svr_conf.get("startup_timeout", STARTUP_TIMEOUT)

        record = self._ensure_status_record(svr_name)

        from argus_mcp.runtime.models import BackendPhase

        try:
            record.transition(BackendPhase.INITIALIZING, f"Connecting ({svr_type})")
        except ValueError:
            pass
        if self._progress_cb is not None:
            self._progress_cb(svr_name, "initializing", f"Connecting ({svr_type})")

        # ── Pre-build container image (outside startup timeout) ──────
        if svr_type == "stdio" and "_prebuild_params" not in svr_conf:
            try:
                await self._pre_build_container_image(svr_name, svr_conf)
            except Exception as exc:
                msg = f"Container image pre-build failed: {exc}"
                logger.error("[%s] %s", svr_name, msg, exc_info=True)
                self._record_failure(svr_name, record, msg)
                return False

        try:
            if svr_type == "stdio":
                await self._connect_backend(svr_name, svr_conf, svr_type, record)
            else:
                await asyncio.wait_for(
                    self._connect_backend(svr_name, svr_conf, svr_type, record),
                    timeout=startup_timeout,
                )
            return True

        except asyncio.TimeoutError:
            msg = (
                f"Overall startup timed out after {startup_timeout}s (subprocess spawn + MCP init)"
            )
            logger.error("[%s] (%s) %s", svr_name, svr_type or "unknown", msg)
            self._record_failure(svr_name, record, msg)
            return False

        except asyncio.CancelledError:
            reason = await self._handle_cancelled_error(svr_name, svr_conf, svr_type)
            self._record_failure(svr_name, record, reason)
            return False

        except BaseException as e_start:
            reason = await self._handle_base_exception(
                svr_name,
                svr_conf,
                svr_type,
                e_start,
            )
            self._record_failure(svr_name, record, reason)
            return False

    def _build_line_cb(self, svr_name: str, line: str) -> None:
        """Forward a docker build output line to the progress display."""
        if self._progress_cb is not None:
            self._progress_cb(svr_name, "building", line)

    def _make_build_line_cb(self, svr_name: str) -> Callable[[str], None]:
        """Return a single-arg callback that binds *svr_name* for build output."""

        def _cb(line: str) -> None:
            self._build_line_cb(svr_name, line)

        return _cb

    async def _pre_build_container_image(
        self,
        svr_name: str,
        svr_conf: Dict[str, Any],
    ) -> None:
        """Pre-build the container image for a stdio backend.

        This runs OUTSIDE the startup timeout so that first-run image
        builds (which download base images + install packages) don't cause
        spurious timeouts.  The result is stored in ``svr_conf`` as
        ``_prebuild_params`` so ``_connect_backend`` can skip the build.

        If the backend is already containerised, disabled, or uses an
        unknown command, this is a no-op.

        Container isolation is **enabled by default** for all supported
        stdio commands (uvx, npx).  Whether missing images are built
        during startup is controlled by the ``ARGUS_BUILD_ON_STARTUP``
        env var.  When unset (the default), images are built
        automatically.  Set to ``false`` to use only cached images —
        backends without cached images gracefully fall back to bare
        subprocess.
        """
        stdio_params = svr_conf.get("params")
        if not isinstance(stdio_params, StdioServerParameters):
            return  # let _connect_backend raise the proper error

        # Notify display immediately so the user sees which backend is
        # being built instead of stale "Pending..." for 30+ seconds.
        if self._progress_cb is not None:
            self._progress_cb(svr_name, "building", "Building container image…")

        from argus_mcp.bridge.container import wrap_backend

        container_cfg = svr_conf.get("container") or {}
        net_override = container_cfg.get("network") or (
            (svr_conf.get("network") or {}).get("network_mode")
        )

        # Determine whether to build missing images during startup.
        # Default is True — container isolation builds images automatically.
        # Set ARGUS_BUILD_ON_STARTUP=false to disable and use pre-built
        # images only (run 'argus-mcp build' first in that case).
        env_build = os.environ.get("ARGUS_BUILD_ON_STARTUP", "").strip().lower()
        if env_build:
            build_if_missing = env_build in ("1", "true", "yes", "on", "enabled")
        else:
            build_if_missing = True

        wrapped_params, was_isolated = await wrap_backend(
            svr_name,
            stdio_params,
            enabled=container_cfg.get("enabled", True),
            runtime_override=container_cfg.get("runtime"),
            network=net_override,
            memory=container_cfg.get("memory"),
            cpus=container_cfg.get("cpus"),
            volumes=container_cfg.get("volumes"),
            extra_args=container_cfg.get("extra_args"),
            build_if_missing=build_if_missing,
            system_deps=container_cfg.get("system_deps"),
            builder_image=container_cfg.get("builder_image"),
            additional_packages=container_cfg.get("additional_packages"),
            transport_override=container_cfg.get("transport"),
            go_package=container_cfg.get("go_package"),
            line_callback=self._make_build_line_cb(svr_name),
        )

        # Stash the result so _connect_backend doesn't rebuild.
        svr_conf["_prebuild_params"] = wrapped_params
        svr_conf["_prebuild_isolated"] = was_isolated

    async def _prepare_backend_stack(
        self,
        svr_name: str,
    ) -> AsyncExitStack:
        """Create a per-backend exit stack, closing any previous one first."""
        old_stack = self._backend_stacks.pop(svr_name, None)
        if old_stack is not None:
            try:
                await asyncio.wait_for(old_stack.aclose(), timeout=5.0)
            except Exception:
                logger.debug(
                    "[%s] Error closing previous backend stack (benign).",
                    svr_name,
                    exc_info=True,
                )
        backend_stack = AsyncExitStack()
        self._backend_stacks[svr_name] = backend_stack
        return backend_stack

    async def _resolve_stdio_params(
        self,
        svr_name: str,
        svr_conf: Dict[str, Any],
    ) -> Tuple[StdioServerParameters, bool]:
        """Resolve stdio parameters, using pre-built or inline container wrapping."""
        stdio_params = svr_conf.get("params")
        if not isinstance(stdio_params, StdioServerParameters):
            raise ConfigurationError(
                f"Invalid stdio config for server '{svr_name}' ('params' type mismatch)."
            )
        # Use pre-built container params from _pre_build_container_image
        # (image was already built outside the startup timeout).
        prebuild_params = svr_conf.pop("_prebuild_params", None)
        prebuild_isolated = svr_conf.pop("_prebuild_isolated", None)

        if prebuild_params is not None:
            return prebuild_params, prebuild_isolated or False

        # Fallback: build inline (non-stdio types, or pre-build skipped).
        from argus_mcp.bridge.container import wrap_backend

        container_cfg = svr_conf.get("container") or {}
        net_override = container_cfg.get("network") or (
            (svr_conf.get("network") or {}).get("network_mode")
        )
        env_build = os.environ.get("ARGUS_BUILD_ON_STARTUP", "").strip().lower()
        if env_build:
            _build = env_build in ("1", "true", "yes", "on", "enabled")
        else:
            _build = True
        return await wrap_backend(
            svr_name,
            stdio_params,
            enabled=container_cfg.get("enabled", True),
            runtime_override=container_cfg.get("runtime"),
            network=net_override,
            memory=container_cfg.get("memory"),
            cpus=container_cfg.get("cpus"),
            volumes=container_cfg.get("volumes"),
            extra_args=container_cfg.get("extra_args"),
            build_if_missing=_build,
            system_deps=container_cfg.get("system_deps"),
            builder_image=container_cfg.get("builder_image"),
            additional_packages=container_cfg.get("additional_packages"),
            transport_override=container_cfg.get("transport"),
            go_package=container_cfg.get("go_package"),
        )

    async def _create_transport_session(
        self,
        svr_name: str,
        svr_conf: Dict[str, Any],
        svr_type: Optional[str],
        auth_headers: Optional[Dict[str, str]],
        backend_stack: AsyncExitStack,
    ) -> ClientSession:
        """Dispatch to the correct transport initializer and return the session."""
        if svr_type == "stdio":
            stdio_params, _isolated = await self._resolve_stdio_params(svr_name, svr_conf)
            if not _isolated:
                stdio_params = self._apply_network_env(
                    svr_name,
                    svr_conf,
                    stdio_params,
                )
            _, session = await self._init_stdio_backend(
                svr_name,
                stdio_params,
                stack=backend_stack,
            )

        elif svr_type == "sse":
            sse_url = svr_conf.get("url")
            if not isinstance(sse_url, str) or not sse_url:
                raise ConfigurationError(
                    f"Invalid SSE 'url' configuration for server '{svr_name}'."
                )
            sse_headers = _merge_headers(svr_conf.get("headers"), auth_headers)
            _, session = await self._init_sse_backend(
                svr_name,
                sse_url,
                svr_conf.get("command"),
                svr_conf.get("args", []),
                svr_conf.get("env"),
                sse_startup_delay=svr_conf.get("sse_startup_delay", SSE_LOCAL_START_DELAY),
                headers=sse_headers,
                stack=backend_stack,
            )

        elif svr_type == "streamable-http":
            sh_url = svr_conf.get("url")
            if not isinstance(sh_url, str) or not sh_url:
                raise ConfigurationError(
                    f"Invalid streamable-http 'url' configuration for server '{svr_name}'."
                )
            sh_headers = _merge_headers(svr_conf.get("headers"), auth_headers)
            _, session = await self._init_streamablehttp_backend(
                svr_name,
                sh_url,
                sh_headers,
                stack=backend_stack,
            )

        else:
            raise ConfigurationError(
                f"Unsupported server type '{svr_type}' for server '{svr_name}'."
            )

        if not session:
            raise BackendServerError(f"[{svr_name}] ({svr_type}) Session could not be created.")
        return session

    async def _initialize_session(
        self,
        svr_name: str,
        svr_conf: Dict[str, Any],
        svr_type: Optional[str],
        session: ClientSession,
    ) -> None:
        """Run ``session.initialize()`` with the appropriate timeout."""
        if svr_type == "stdio":
            init_timeout = svr_conf.get("init_timeout", STDIO_MCP_INIT_TIMEOUT)
            suffix = " (post-build)"
        else:
            init_timeout = svr_conf.get("init_timeout", MCP_INIT_TIMEOUT)
            suffix = ""
        logger.info(
            "[%s] Initializing MCP connection (timeout: %ss)...",
            svr_name,
            init_timeout,
        )
        try:
            await asyncio.wait_for(session.initialize(), timeout=init_timeout)
        except asyncio.TimeoutError:
            raise BackendServerError(
                f"[{svr_name}] MCP initialization timed out after {init_timeout}s{suffix}"
            ) from None

    async def _connect_backend(
        self,
        svr_name: str,
        svr_conf: Dict[str, Any],
        svr_type: Optional[str],
        record: Any,
    ) -> None:
        """Inner connection logic (spawn transport + MCP init).

        For remote backends, ``_start_backend_svr`` wraps this in
        ``asyncio.wait_for`` with the overall ``startup_timeout``.
        For stdio backends, this is called directly (no overall timeout);
        only ``session.initialize()`` has a ``STDIO_MCP_INIT_TIMEOUT``.

        Each backend gets its own :class:`AsyncExitStack` so that
        individual backends can be disconnected (and their transport /
        subprocess cleaned up) without tearing down every other backend.
        The per-backend stack is also entered into the global
        ``_exit_stack`` so that ``stop_all()`` still works as a
        catch-all during full shutdown.
        """
        from argus_mcp.runtime.models import BackendPhase

        auth_headers = await self._resolve_auth_headers(svr_name, svr_conf)
        backend_stack = await self._prepare_backend_stack(svr_name)

        session = await self._create_transport_session(
            svr_name,
            svr_conf,
            svr_type,
            auth_headers,
            backend_stack,
        )
        await self._initialize_session(svr_name, svr_conf, svr_type, session)

        self._sessions[svr_name] = session
        logger.info(
            "\u2705 MCP connection initialized for server '%s' (%s).",
            svr_name,
            svr_type,
        )
        try:
            record.transition(BackendPhase.READY, "Connection established")
        except ValueError:
            pass
        if self._progress_cb is not None:
            self._progress_cb(svr_name, "ready")

    def _launch_remote_backends(
        self,
        remote_items: List[Tuple[str, Dict[str, Any]]],
        sem: asyncio.Semaphore,
        stagger: float,
        concurrency: int,
    ) -> Dict[str, asyncio.Task]:
        """Create and return asyncio tasks for remote backends (concurrent).

        Remote backends (SSE, streamable-http) need no build phase and
        connect in seconds.  They are launched immediately so they appear
        as "Ready" while stdio builds proceed sequentially.
        """
        remote_tasks: Dict[str, asyncio.Task] = {}
        for idx, (name, conf) in enumerate(remote_items):

            async def _gated_remote(
                n: str = name,
                c: Dict[str, Any] = conf,
                i: int = idx,
            ) -> bool:
                async with sem:
                    if i > 0 and stagger > 0:
                        await asyncio.sleep(stagger * (i % concurrency))
                    return await self._start_backend_svr(n, c)

            task = asyncio.create_task(
                _gated_remote(),
                name=f"start_{name}",
            )
            remote_tasks[name] = task
            self._pending_tasks[name] = task
        return remote_tasks

    async def _build_and_connect_stdio(
        self,
        stdio_items: List[Tuple[str, Dict[str, Any]]],
    ) -> Dict[str, bool]:
        """Sequential loop: pre-build image, then connect for each stdio backend.

        Build container images one at a time so they don't compete for
        CPU / network / Docker daemon locks.  Each stdio backend is
        wrapped in a task so ``cancel_startup()`` can cancel via
        ``_pending_tasks``.
        """
        stdio_results: Dict[str, bool] = {}
        for svr_name, svr_conf in stdio_items:
            if self._shutdown_requested:
                stdio_results[svr_name] = False
                break

            async def _stdio_build_and_connect(
                name: str = svr_name,
                conf: Dict[str, Any] = svr_conf,
            ) -> bool:
                try:
                    await self._pre_build_container_image(name, conf)
                except Exception as exc:
                    logger.error(
                        "[%s] Sequential pre-build failed: %s",
                        name,
                        exc,
                        exc_info=True,
                    )
                return await self._start_backend_svr(name, conf)

            task = asyncio.create_task(
                _stdio_build_and_connect(),
                name=f"start_{svr_name}",
            )
            self._pending_tasks[svr_name] = task
            try:
                ok = await task
                stdio_results[svr_name] = ok
            except asyncio.CancelledError:
                logger.info("[%s] Stdio startup cancelled.", svr_name)
                stdio_results[svr_name] = False
            except Exception as exc:
                logger.error(
                    "[%s] Startup task failed with exception '%s'.",
                    svr_name,
                    type(exc).__name__,
                )
                stdio_results[svr_name] = False
        return stdio_results

    async def _gather_remote_results(
        self,
        remote_tasks: Dict[str, asyncio.Task],
    ) -> Dict[str, bool]:
        """Await remote tasks and collect results."""
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

    async def _await_auth_discoveries(
        self,
        failed_names: List[str],
    ) -> None:
        """Wait for pending auth discovery tasks before retrying.

        If a backend has an ongoing PKCE browser auth flow (from a
        previous attempt), wait for it to complete before retrying.
        This prevents duplicate DCR registrations and browser tabs.
        """
        auth_wait_names = [
            n
            for n in failed_names
            if n in self._auth_discovery_tasks and not self._auth_discovery_tasks[n].done()
        ]
        if not auth_wait_names:
            return

        _AUTH_WAIT_TIMEOUT = 120.0
        logger.info(
            "Waiting up to %.0fs for pending auth discovery on %d backend(s): %s",
            _AUTH_WAIT_TIMEOUT,
            len(auth_wait_names),
            ", ".join(auth_wait_names),
        )
        pending_tasks = [self._auth_discovery_tasks[n] for n in auth_wait_names]
        for n in auth_wait_names:
            if self._progress_cb is not None:
                self._progress_cb(
                    n,
                    "initializing",
                    "Waiting for browser authentication…",
                )
        try:
            done, _ = await asyncio.wait(
                pending_tasks,
                timeout=_AUTH_WAIT_TIMEOUT,
            )
            for n in auth_wait_names:
                auth_task = self._auth_discovery_tasks.get(n)
                if auth_task and auth_task.done():
                    try:
                        auth_ok = auth_task.result()
                        if auth_ok:
                            logger.info(
                                "[%s] Auth discovery completed — will retry with credentials.",
                                n,
                            )
                    except Exception:
                        pass
        except Exception:
            pass

    async def _retry_failed_backends(
        self,
        failed_names: List[str],
        config_data: Dict[str, Dict[str, Any]],
        sem: asyncio.Semaphore,
        stagger: float,
        concurrency: int,
    ) -> None:
        """Retry loop with exponential backoff for backends that failed on first pass."""
        from argus_mcp.runtime.models import BackendPhase

        max_retries = max(config_data[n].get("retries", BACKEND_RETRIES) for n in failed_names)
        logger.info(
            "%d backend(s) failed on first attempt — will retry up to %d time(s): %s",
            len(failed_names),
            max_retries,
            ", ".join(failed_names),
        )

        for attempt in range(1, max_retries + 1):
            if not failed_names or self._shutdown_requested:
                break

            # Per-backend delay with exponential backoff
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

            # Signal "retrying" phase to display
            for svr_name in failed_names:
                record = self._status_records.get(svr_name)
                if record is not None:
                    try:
                        record.transition(
                            BackendPhase.RETRYING,
                            f"Retry {attempt}/{max_retries}",
                        )
                    except ValueError:
                        pass
                if self._progress_cb is not None:
                    self._progress_cb(
                        svr_name,
                        "retrying",
                        f"Retry {attempt}/{max_retries} in {delay:.0f}s…",
                    )

            await asyncio.sleep(delay)

            # Wait for pending auth discovery tasks
            await self._await_auth_discoveries(failed_names)

            # Retry failed backends with same concurrency limiter
            retry_tasks: Dict[str, asyncio.Task] = {}
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
                        return await self._start_backend_svr(name, conf)

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
                        logger.info(
                            "[%s] Retry %d succeeded.",
                            svr_name,
                            attempt,
                        )

            # Refresh the failed list for next iteration
            failed_names = [n for n in failed_names if n not in self._sessions]

    async def start_all(
        self,
        config_data: Dict[str, Dict[str, Any]],
        progress_callback: Optional[Callable[..., None]] = None,
    ) -> None:
        """Start all backend server connections, retrying failures.

        Backends are started with **staggered concurrency** — at most
        ``STARTUP_CONCURRENCY`` backends spawn at the same time, with a
        small inter-launch delay (``STARTUP_STAGGER_DELAY``) to spread
        I/O and avoid npm/pip cache-lock contention.

        After the initial pass, any failures are automatically retried up
        to ``retries`` times (per-backend or global default) using the
        same concurrency limiter.
        """
        self._progress_cb = progress_callback
        total = len(config_data)
        concurrency = max(1, int(os.environ.get("ARGUS_STARTUP_CONCURRENCY", STARTUP_CONCURRENCY)))
        stagger = float(os.environ.get("ARGUS_STARTUP_STAGGER", STARTUP_STAGGER_DELAY))
        logger.info(
            "Starting all backend server connections (%s total, concurrency=%s, stagger=%.1fs)...",
            total,
            concurrency,
            stagger,
        )

        # ── Separate remote and stdio backends ────────────────────────
        _type_priority = {"streamable-http": 0, "sse": 1, "stdio": 2}
        sorted_items = sorted(
            config_data.items(),
            key=lambda kv: _type_priority.get(kv[1].get("type", "stdio"), 2),
        )
        remote_items = [(n, c) for n, c in sorted_items if c.get("type") != "stdio"]
        stdio_items = [(n, c) for n, c in sorted_items if c.get("type") == "stdio"]

        sem = asyncio.Semaphore(concurrency)

        # Phase 1: Launch remotes concurrently + sequential stdio builds
        remote_tasks = self._launch_remote_backends(
            remote_items,
            sem,
            stagger,
            concurrency,
        )
        if remote_tasks:
            await asyncio.sleep(0)

        stdio_results = await self._build_and_connect_stdio(stdio_items)

        # Phase 2: Gather remote results
        remote_results = await self._gather_remote_results(remote_tasks)

        # Merge all first-pass results
        first_pass = {**remote_results, **stdio_results}
        self._pending_tasks.clear()

        # Phase 3: Retry failures
        failed_names = [n for n, ok in first_pass.items() if not ok]
        if failed_names and not self._shutdown_requested:
            await self._retry_failed_backends(
                failed_names,
                config_data,
                sem,
                stagger,
                concurrency,
            )

        self._pending_tasks.clear()
        self._progress_cb = None

        active_svrs_count = len(self._sessions)
        total_svrs_count = len(config_data)
        logger.info(
            "All backend startup attempts completed. Active servers: %s/%s",
            active_svrs_count,
            total_svrs_count,
        )
        if active_svrs_count < total_svrs_count:
            logger.warning(
                "Some backend servers failed to start/connect. Check file logs for details."
            )

    async def stop_all(self) -> None:
        """Close all active sessions and subprocesses started by the manager."""
        logger.info("Stopping all backend connections and local processes...")

        # Transition operational backends to SHUTTING_DOWN
        from argus_mcp.runtime.models import BackendPhase

        for name, rec in self._status_records.items():
            if rec.is_operational:
                try:
                    rec.transition(BackendPhase.SHUTTING_DOWN, "Graceful shutdown")
                except ValueError:
                    pass

        if self._pending_tasks:
            logger.info(
                "Cancelling %s pending startup tasks...",
                len(self._pending_tasks),
            )
            for task in self._pending_tasks.values():
                if not task.done():
                    task.cancel()
            await asyncio.gather(*self._pending_tasks.values(), return_exceptions=True)
            self._pending_tasks.clear()
            logger.info("Pending startup tasks cancelled and cleaned up.")

        # Close per-backend stacks first (each closes its own transport +
        # session + subprocess).  This is the primary cleanup path.
        for name, stack in list(self._backend_stacks.items()):
            try:
                await asyncio.wait_for(stack.aclose(), timeout=5.0)
                logger.debug("Backend '%s' stack closed.", name)
            except asyncio.TimeoutError:
                logger.warning("Backend '%s' stack close timed out.", name)
            except RuntimeError as e_rt:
                logger.debug("Cancel scope error closing '%s': %s", name, e_rt)
            except Exception:
                logger.debug("Error closing backend '%s' stack.", name, exc_info=True)
        self._backend_stacks.clear()

        # Close the global exit stack as a safety net for any resources
        # that were entered there directly (e.g. by older code paths).
        logger.debug("Closing global AsyncExitStack as safety net...")
        try:
            await asyncio.wait_for(self._exit_stack.aclose(), timeout=10.0)
            logger.info("Global AsyncExitStack closed.")
        except asyncio.TimeoutError:
            logger.warning("Global AsyncExitStack.aclose() timed out after 10s.")
        except RuntimeError as e_rt:
            logger.warning("Cancel scope error during shutdown (safe to ignore): %s", e_rt)
        except Exception as e_aclose:
            logger.warning(
                "Error while closing global AsyncExitStack: %s.",
                e_aclose,
            )

        self._sessions.clear()

        # Remove any pre-created Docker containers tracked by the
        # container wrapper.  These are created during wrap_backend()
        # using ``docker create`` and need explicit removal.
        try:
            from argus_mcp.bridge.container.wrapper import (
                cleanup_all_containers,
            )

            await cleanup_all_containers()
        except Exception:
            logger.debug(
                "Container cleanup during shutdown failed.",
                exc_info=True,
            )

        # Close devnull file objects opened for subprocess stderr suppression
        for f in self._devnull_files:
            try:
                f.close()
            except Exception:
                pass
        self._devnull_files.clear()

        logger.info("ClientManager closed, all sessions cleared.")

    async def disconnect_one(self, name: str) -> None:
        """Disconnect and clean up a single backend by name.

        Closes the per-backend :class:`AsyncExitStack` which tears down
        the transport, session, and any subprocess created for this
        backend.  This is the correct way to disconnect an individual
        backend (e.g. during reconnect) without leaking child processes.

        If no per-backend stack exists (legacy path), only the session
        reference is removed — a warning is logged since this may leak.
        """
        backend_stack = self._backend_stacks.pop(name, None)
        if backend_stack is not None:
            try:
                await asyncio.wait_for(backend_stack.aclose(), timeout=10.0)
                logger.info(
                    "Backend '%s' disconnected (stack closed, subprocess terminated).", name
                )
            except asyncio.TimeoutError:
                logger.warning("Backend '%s' disconnect timed out after 10s.", name)
            except RuntimeError as e_rt:
                logger.debug(
                    "Cancel scope error disconnecting '%s' (benign): %s",
                    name,
                    e_rt,
                )
            except Exception:
                logger.warning("Error disconnecting backend '%s'.", name, exc_info=True)
        else:
            logger.warning(
                "Backend '%s' has no per-backend exit stack — "
                "subprocess may leak (legacy code path).",
                name,
            )

        # Remove any pre-created Docker container for this backend.
        try:
            from argus_mcp.bridge.container.wrapper import cleanup_container

            await cleanup_container(name)
        except Exception:
            logger.debug(
                "Container cleanup for '%s' failed.",
                name,
                exc_info=True,
            )

        self._sessions.pop(name, None)

    def get_session(self, svr_name: str) -> Optional[ClientSession]:
        """Get an active backend session by server name."""
        return self._sessions.get(svr_name)

    def get_active_session_count(self) -> int:
        """Get the number of active sessions."""
        return len(self._sessions)

    def get_all_sessions(self) -> Dict[str, ClientSession]:
        """Get a dictionary copy of all active sessions."""
        return self._sessions.copy()

    # ── Status records ───────────────────────────────────────────────────

    def get_status_record(self, svr_name: str) -> Optional[Any]:
        """Get the status record for a backend (or ``None``)."""
        return self._status_records.get(svr_name)

    def get_all_status_records(self) -> Dict[str, Any]:
        """Return a snapshot of all status records."""
        return dict(self._status_records)

    # ── Outgoing authentication ──────────────────────────────────────

    async def _resolve_auth_headers(
        self, svr_name: str, svr_conf: Dict[str, Any]
    ) -> Optional[Dict[str, str]]:
        """Resolve outgoing-auth headers for a backend, if configured.

        Checks (in order):
        1. Explicit ``auth`` block in the backend config.
        2. Runtime-discovered auth config from ``_discovered_auth``.
        """
        auth_cfg = svr_conf.get("auth")
        if not auth_cfg:
            # Check for runtime-discovered auth
            auth_cfg = self._discovered_auth.get(svr_name)
        if not auth_cfg:
            return None
        try:
            from argus_mcp.bridge.auth.provider import create_auth_provider

            provider = create_auth_provider(auth_cfg, backend_name=svr_name)
            headers = await provider.get_headers()
            logger.info("[%s] Auth provider resolved: %s", svr_name, provider.redacted_repr())
            return headers
        except Exception as exc:
            logger.error("[%s] Failed to resolve auth headers: %s", svr_name, exc)
            return None

    async def _attempt_auth_discovery_for_backend(
        self,
        svr_name: str,
        svr_conf: Dict[str, Any],
        svr_type: Optional[str],
        default_reason: str,
    ) -> str:
        """Run OAuth auto-discovery for a backend, shielded from cancellation.

        Returns an updated failure reason string.  Uses task tracking to
        prevent duplicate DCR registrations and PKCE flows — if an auth
        discovery task is already running for this backend, waits on it
        instead of starting a new one.

        For remote backends (SSE / streamable-http) only.
        """
        if svr_type not in ("sse", "streamable-http"):
            return default_reason

        # ── Deduplicate: reuse existing running task ────────────────
        existing_task = self._auth_discovery_tasks.get(svr_name)
        if existing_task is not None and not existing_task.done():
            logger.info(
                "[%s] Auth discovery already in progress — waiting for existing flow to complete.",
                svr_name,
            )
            try:
                auth_ok = await asyncio.shield(existing_task)
                if auth_ok:
                    return "Auth discovered — will retry with OAuth token."
            except asyncio.CancelledError:
                logger.info(
                    "[%s] Wait for existing auth flow interrupted by "
                    "cancellation — flow continues in background.",
                    svr_name,
                )
            except Exception as wait_exc:
                logger.debug(
                    "[%s] Existing auth flow failed: %s",
                    svr_name,
                    wait_exc,
                )
            return default_reason

        # ── Start a new auth discovery task ─────────────────────────
        coro = self._try_auth_discovery(svr_name, svr_conf)
        task = asyncio.create_task(
            coro,
            name=f"auth_discovery_{svr_name}",
        )
        task.add_done_callback(_log_task_exception)
        self._auth_discovery_tasks[svr_name] = task

        try:
            auth_ok = await asyncio.shield(task)
            if auth_ok:
                return "Auth discovered — will retry with OAuth token."
        except asyncio.CancelledError:
            # shield() re-raises CancelledError in the outer scope
            # when the parent task is cancelled, but the inner task
            # (auth discovery + PKCE) continues running independently.
            logger.info(
                "[%s] Auth discovery interrupted by cancellation — "
                "inner coroutine continues in background.",
                svr_name,
            )
        except Exception as auth_exc:
            logger.debug(
                "[%s] Auth discovery attempt failed: %s",
                svr_name,
                auth_exc,
            )
        return default_reason

    async def _try_auth_discovery(
        self,
        svr_name: str,
        svr_conf: Dict[str, Any],
    ) -> bool:
        """Attempt OAuth auto-discovery for a backend that failed with auth errors.

        Probes the backend URL for RFC 9728 / OIDC metadata.  If the
        server advertises OAuth with PKCE support, runs the interactive
        browser flow and stores the resulting auth config for subsequent
        retry attempts.

        Returns ``True`` if auth was successfully discovered and tokens
        obtained, ``False`` otherwise.
        """
        backend_url = svr_conf.get("url")
        if not backend_url:
            return False

        # Already has explicit auth config — don't override.
        if svr_conf.get("auth"):
            return False

        # Already discovered auth for this backend.
        if svr_name in self._discovered_auth:
            return False

        try:
            from argus_mcp.bridge.auth.discovery import discover_oauth_metadata

            logger.info(
                "[%s] Attempting OAuth auto-discovery on %s…",
                svr_name,
                backend_url,
            )

            if self._progress_cb is not None:
                self._progress_cb(
                    svr_name,
                    "initializing",
                    "Discovering auth requirements…",
                )

            meta = await discover_oauth_metadata(backend_url, timeout=15.0)
            if not meta:
                logger.info(
                    "[%s] No OAuth metadata found — auth discovery failed.",
                    svr_name,
                )
                return False

            logger.info(
                "[%s] OAuth discovered: issuer=%s, pkce=%s, registration=%s",
                svr_name,
                meta.issuer,
                meta.supports_pkce,
                meta.supports_dynamic_registration,
            )

            if not meta.authorization_endpoint or not meta.token_endpoint:
                logger.warning(
                    "[%s] OAuth metadata incomplete — missing endpoints.",
                    svr_name,
                )
                return False

            # ── Prepare PKCE flow early to learn redirect URI ──────
            from argus_mcp.bridge.auth.pkce import PKCEFlow

            scopes = meta.scopes_supported or []
            flow = PKCEFlow(
                authorization_endpoint=meta.authorization_endpoint,
                token_endpoint=meta.token_endpoint,
                client_id="pending",  # placeholder until DCR completes
                scopes=scopes,
                timeout=600.0,  # 10 minutes for interactive auth
            )

            # Bind the callback server NOW so the exact port is known
            # before Dynamic Client Registration.
            redirect_uri = flow.bind_callback_server()
            logger.info(
                "[%s] PKCE callback server pre-bound: %s",
                svr_name,
                redirect_uri,
            )

            # ── Dynamic Client Registration (if available) ──────────
            client_id = ""
            client_secret = ""

            if meta.supports_dynamic_registration:
                try:
                    client_id, client_secret = await self._dynamic_register(
                        svr_name,
                        meta.registration_endpoint,
                        backend_url,
                        redirect_uri=redirect_uri,
                    )
                except Exception as exc:
                    logger.warning(
                        "[%s] Dynamic client registration failed: %s. Trying without registration.",
                        svr_name,
                        exc,
                    )

            if not client_id:
                logger.warning(
                    "[%s] No client_id available (registration failed or "
                    "not supported). Cannot proceed with PKCE auth.",
                    svr_name,
                )
                return False

            # ── Run PKCE flow ───────────────────────────────────────
            # Patch in the real client_id/secret from DCR
            flow._client_id = client_id  # noqa: SLF001
            flow._client_secret = client_secret  # noqa: SLF001

            if self._progress_cb is not None:
                self._progress_cb(
                    svr_name,
                    "initializing",
                    "Waiting for browser authentication…",
                )

            tokens = await flow.execute()

            # Store tokens persistently
            from argus_mcp.bridge.auth.store import TokenStore

            store = TokenStore()
            store.save(svr_name, tokens)

            # Store discovered auth config for retry
            self._discovered_auth[svr_name] = {
                "type": "pkce",
                "authorization_endpoint": meta.authorization_endpoint,
                "token_endpoint": meta.token_endpoint,
                "client_id": client_id,
                "client_secret": client_secret,
                "scopes": scopes,
            }

            logger.info(
                "[%s] OAuth PKCE auth succeeded — token stored for retry.",
                svr_name,
            )
            return True

        except (Exception, asyncio.CancelledError) as exc:
            logger.warning(
                "[%s] Auth discovery/PKCE flow failed: %s",
                svr_name,
                exc,
            )
            return False

    async def _dynamic_register(
        self,
        svr_name: str,
        registration_endpoint: str,
        backend_url: str,
        redirect_uri: str = "",
    ) -> Tuple[str, str]:
        """Register a dynamic OAuth client (RFC 7591).

        Parameters
        ----------
        redirect_uri:
            The full redirect URI including the ephemeral port, e.g.
            ``http://127.0.0.1:46293/callback``.  When supplied, this
            exact URI is registered so it matches the PKCE callback
            server that is already listening.  If empty, falls back to
            ``http://127.0.0.1/callback`` (legacy behaviour).

        Returns ``(client_id, client_secret)``.
        Raises on failure.
        """
        import httpx  # noqa: PLC0415

        if not redirect_uri:
            redirect_uri = "http://127.0.0.1/callback"

        reg_data = {
            "client_name": f"Argus MCP ({svr_name})",
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
            "application_type": "native",
            "scope": "openid email profile offline_access",
        }

        logger.info(
            "[%s] Dynamic client registration → %s (redirect_uris=%s)",
            svr_name,
            registration_endpoint,
            reg_data["redirect_uris"],
        )

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                registration_endpoint,
                json=reg_data,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()

        payload = resp.json()
        client_id = payload.get("client_id", "")
        client_secret = payload.get("client_secret", "")
        registered_uris = payload.get("redirect_uris", [])
        logger.info(
            "[%s] Dynamic registration succeeded: client_id=%s, registered_redirect_uris=%s",
            svr_name,
            client_id[:12] + "…" if len(client_id) > 12 else client_id,
            registered_uris,
        )
        return client_id, client_secret


# ── Module-level helpers ─────────────────────────────────────────────────


def _looks_like_auth_failure(exc: BaseException) -> bool:
    """Return ``True`` if *exc* appears to be an HTTP authentication error.

    Detects HTTP 401/403 status codes inside:
    - ``httpx.HTTPStatusError`` directly.
    - ``ExceptionGroup`` / ``BaseExceptionGroup`` wrapping one or more
      status errors (as produced by the MCP SDK's internal TaskGroup
      when a server returns 401 Unauthorized).
    - String representations mentioning "401" or "Unauthorized" (broad
      fallback for exception types we don't import).
    """

    def _is_auth_status(e: BaseException) -> bool:
        # Check httpx.HTTPStatusError without importing httpx at module
        # level (it's an optional dependency for some backends).
        type_name = type(e).__name__
        if type_name == "HTTPStatusError":
            status = getattr(getattr(e, "response", None), "status_code", 0)
            return status in (401, 403)
        # Broad text check for wrapped error messages
        msg = str(e).lower()
        return "401" in msg or "unauthorized" in msg or "403" in msg

    if _is_auth_status(exc):
        return True

    # Check sub-exceptions inside ExceptionGroup / BaseExceptionGroup
    sub_exceptions = getattr(exc, "exceptions", None)
    if sub_exceptions:
        return any(_is_auth_status(sub) for sub in sub_exceptions)

    return False


def _merge_headers(
    static: Optional[Dict[str, str]],
    auth: Optional[Dict[str, str]],
) -> Optional[Dict[str, str]]:
    """Merge static config headers with auth-provider headers.

    Auth-provider headers take precedence over static ones (e.g. a
    provider-managed ``Authorization`` header overrides a static one).
    Returns ``None`` when both inputs are ``None``.
    """
    if not static and not auth:
        return None
    merged: Dict[str, str] = {}
    if static:
        merged.update(static)
    if auth:
        merged.update(auth)
    return merged
