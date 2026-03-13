"""Per-backend connection lifecycle: spawn, init session, error handling.

Extracted from ``ClientManager`` to isolate the per-backend connect /
pre-build / error-handling logic from the orchestration facade.
"""

import asyncio
import logging
import os
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    import httpx

from mcp import ClientSession, StdioServerParameters

from argus_mcp.bridge import auth_discovery as ad
from argus_mcp.bridge import transport_factory as tf
from argus_mcp.bridge.subprocess_utils import (
    log_backend_fail as _log_backend_fail,
)
from argus_mcp.bridge.subprocess_utils import (
    manage_subproc as _manage_subproc,
)
from argus_mcp.constants import (
    MCP_INIT_TIMEOUT,
    SSE_LOCAL_START_DELAY,
    STARTUP_TIMEOUT,
    STDIO_MCP_INIT_TIMEOUT,
)
from argus_mcp.errors import BackendServerError

logger = logging.getLogger(__name__)

_looks_like_auth_failure = ad.looks_like_auth_failure


def ensure_status_record(
    svr_name: str,
    status_records: Dict[str, Any],
) -> Any:
    """Return (or create) the status record for *svr_name*."""
    from argus_mcp.runtime.models import BackendStatusRecord

    record = status_records.get(svr_name)
    if record is None:
        record = BackendStatusRecord(name=svr_name)
        status_records[svr_name] = record
    return record


def record_failure(
    svr_name: str,
    record: Any,
    msg: str,
    progress_cb: Optional[Callable[..., None]],
) -> None:
    """Transition a status record to FAILED and notify progress display."""
    from argus_mcp.runtime.models import BackendPhase

    try:
        record.transition(BackendPhase.FAILED, msg)
    except ValueError:
        pass
    if progress_cb is not None:
        progress_cb(svr_name, "failed", msg)


def record_auth_pending_or_failure(
    svr_name: str,
    record: Any,
    msg: str,
    auth_discovery_tasks: Dict[str, "asyncio.Task[Any]"],
    progress_cb: Optional[Callable[..., None]],
) -> None:
    """Keep INITIALIZING when auth discovery is running, else mark FAILED.

    When a PKCE browser flow is in progress, the backend should show a
    spinner (INITIALIZING) rather than collapsing to a permanent ``\u2717``
    line.  The retry loop will wait for the auth task and produce the
    real ``\u2713`` / ``\u2717`` once the outcome is known.
    """
    auth_task = auth_discovery_tasks.get(svr_name)
    if auth_task is not None and not auth_task.done():
        from argus_mcp.runtime.models import BackendPhase

        try:
            record.transition(BackendPhase.INITIALIZING, msg)
        except ValueError:
            pass
        if progress_cb is not None:
            progress_cb(svr_name, "initializing", msg)
    else:
        record_failure(svr_name, record, msg, progress_cb)


async def handle_cancelled_error(
    svr_name: str,
    svr_conf: Dict[str, Any],
    svr_type: Optional[str],
    shutdown_requested: bool,
    auth_discovery_tasks: Dict[str, "asyncio.Task[Any]"],
    discovered_auth: Dict[str, Dict[str, Any]],
    progress_cb: Optional[Callable[..., None]],
) -> str:
    """Determine the failure reason for a CancelledError."""
    if shutdown_requested:
        logger.info(
            "[%s] (%s) startup cancelled (shutdown requested).",
            svr_name,
            svr_type or "unknown type",
        )
        return "Startup cancelled (shutdown requested)"

    cancel_reason = (
        "Connection rejected — possible auth failure (OAuth/API key). Attempting auto-discovery…"
    )
    logger.warning(
        "[%s] (%s) startup task cancelled — possible auth "
        "failure. Will attempt OAuth auto-discovery.",
        svr_name,
        svr_type or "unknown type",
    )
    return await ad.attempt_auth_discovery(
        svr_name,
        svr_conf,
        svr_type,
        cancel_reason,
        auth_discovery_tasks,
        discovered_auth,
        progress_cb,
    )


async def handle_base_exception(
    svr_name: str,
    svr_conf: Dict[str, Any],
    svr_type: Optional[str],
    e_start: BaseException,
    shutdown_requested: bool,
    auth_discovery_tasks: Dict[str, "asyncio.Task[Any]"],
    discovered_auth: Dict[str, Dict[str, Any]],
    progress_cb: Optional[Callable[..., None]],
) -> str:
    """Determine the failure reason for a BaseException (incl. ExceptionGroup)."""
    fail_reason = str(e_start)
    is_auth_failure = _looks_like_auth_failure(e_start)

    if is_auth_failure and not shutdown_requested:
        logger.warning(
            "[%s] (%s) connection failed with auth-related error: "
            "%s. Attempting OAuth auto-discovery.",
            svr_name,
            svr_type or "unknown type",
            type(e_start).__name__,
        )
        return await ad.attempt_auth_discovery(
            svr_name,
            svr_conf,
            svr_type,
            fail_reason,
            auth_discovery_tasks,
            discovered_auth,
            progress_cb,
        )

    _log_backend_fail(
        svr_name,
        svr_type,
        e_start,
        context="connect/initialize",
    )
    return fail_reason


def apply_network_env(
    svr_name: str,
    svr_conf: Dict[str, Any],
    params: StdioServerParameters,
) -> StdioServerParameters:
    """Inject HTTP_PROXY / NO_PROXY env vars from network isolation config."""
    return tf.apply_network_env(svr_name, svr_conf, params)


async def init_stdio_backend(
    svr_name: str,
    stdio_cfg: StdioServerParameters,
    devnull: Any,
    stack: AsyncExitStack,
) -> Tuple[Any, ClientSession]:
    """Initialize and connect to a stdio backend server."""
    return await tf.init_stdio(svr_name, stdio_cfg, devnull, stack)


async def init_sse_backend(
    svr_name: str,
    sse_url: str,
    sse_cmd: Optional[str],
    sse_cmd_args: List[str],
    sse_cmd_env: Optional[Dict[str, str]],
    stack: AsyncExitStack,
    sse_startup_delay: float = SSE_LOCAL_START_DELAY,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[Any, ClientSession]:
    """Initialize and connect to an SSE backend."""
    return await tf.init_sse(
        svr_name,
        sse_url,
        sse_cmd,
        sse_cmd_args,
        sse_cmd_env,
        stack,
        sse_startup_delay=sse_startup_delay,
        headers=headers,
        manage_subproc=_manage_subproc,
    )


async def init_streamablehttp_backend(
    svr_name: str,
    url: str,
    stack: AsyncExitStack,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[Any, ClientSession]:
    """Initialize and connect to a streamable-http backend server."""
    return await tf.init_streamablehttp(svr_name, url, stack, headers=headers)


async def pre_build_container_image(
    svr_name: str,
    svr_conf: Dict[str, Any],
    progress_cb: Optional[Callable[..., None]],
) -> None:
    """Pre-build the container image for a stdio backend.

    Runs OUTSIDE the startup timeout; the result is stashed in
    *svr_conf* so that ``connect_backend`` skips the build.
    """
    stdio_params = svr_conf.get("params")
    if not isinstance(stdio_params, StdioServerParameters):
        return

    if progress_cb is not None:
        progress_cb(svr_name, "building", "Building container image…")

    from argus_mcp.bridge.container import wrap_backend

    container_cfg = svr_conf.get("container") or {}
    net_override = container_cfg.get("network") or (
        (svr_conf.get("network") or {}).get("network_mode")
    )

    env_build = os.environ.get("ARGUS_BUILD_ON_STARTUP", "").strip().lower()
    if env_build:
        build_if_missing = env_build in ("1", "true", "yes", "on", "enabled")
    else:
        build_if_missing = True

    def _build_line_cb(line: str) -> None:
        if progress_cb is not None:
            progress_cb(svr_name, "building", line)

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
        line_callback=_build_line_cb,
    )

    svr_conf["_prebuild_params"] = wrapped_params
    svr_conf["_prebuild_isolated"] = was_isolated


async def prepare_backend_stack(
    svr_name: str,
    backend_stacks: Dict[str, AsyncExitStack],
) -> AsyncExitStack:
    """Create a per-backend exit stack, closing any previous one first."""
    old_stack = backend_stacks.pop(svr_name, None)
    if old_stack is not None:
        try:
            await asyncio.wait_for(old_stack.aclose(), timeout=5.0)
        except Exception:  # noqa: BLE001
            logger.debug(
                "[%s] Error closing previous backend stack (benign).",
                svr_name,
                exc_info=True,
            )
    backend_stack = AsyncExitStack()
    backend_stacks[svr_name] = backend_stack
    return backend_stack


async def connect_backend(
    svr_name: str,
    svr_conf: Dict[str, Any],
    svr_type: Optional[str],
    record: Any,
    sessions: Dict[str, ClientSession],
    backend_stacks: Dict[str, AsyncExitStack],
    devnull: Any,
    discovered_auth: Dict[str, Dict[str, Any]],
    progress_cb: Optional[Callable[..., None]],
    auth_providers: Optional[Dict[str, Any]] = None,
) -> None:
    """Inner connection logic (spawn transport + MCP init).

    For remote backends, the caller wraps this in ``asyncio.wait_for``
    with the overall ``startup_timeout``.
    """
    from argus_mcp.runtime.models import BackendPhase

    provider = await ad.resolve_auth_provider(svr_name, svr_conf, discovered_auth)

    # Store auth provider for background refresh.
    if provider is not None and auth_providers is not None:
        auth_providers[svr_name] = provider

    # Build httpx.Auth wrapper when the backend has an auth provider.
    auth: "httpx.Auth | None" = None
    if provider is not None:
        from argus_mcp.bridge.auth.httpx_auth import McpBearerAuth

        auth_cfg = svr_conf.get("auth")
        retry_on_401 = (
            auth_cfg.get("auth_retry_on_401", True) if isinstance(auth_cfg, dict) else True
        )
        auth = McpBearerAuth(provider, retry_on_401=retry_on_401)

    # Static / config-level headers still flow through the headers channel.
    auth_headers = (await provider.get_headers()) if provider is not None else None

    backend_stack = await prepare_backend_stack(svr_name, backend_stacks)

    session = await tf.create_transport_session(
        svr_name,
        svr_conf,
        svr_type,
        auth_headers,
        backend_stack,
        devnull,
        manage_subproc=_manage_subproc,
        auth=auth,
    )

    # Initialize MCP session with appropriate timeout
    if svr_type == "stdio":
        init_timeout = svr_conf.get("init_timeout", STDIO_MCP_INIT_TIMEOUT)
        suffix = " (post-build)"
    else:
        init_timeout = svr_conf.get("init_timeout", MCP_INIT_TIMEOUT)
        suffix = ""
    logger.info("[%s] Initializing MCP connection (timeout: %ss)...", svr_name, init_timeout)
    try:
        await asyncio.wait_for(session.initialize(), timeout=init_timeout)
    except asyncio.TimeoutError:
        raise BackendServerError(
            f"[{svr_name}] MCP initialization timed out after {init_timeout}s{suffix}"
        ) from None

    sessions[svr_name] = session
    logger.info(
        "\u2705 MCP connection initialized for server '%s' (%s).",
        svr_name,
        svr_type,
    )
    try:
        record.transition(BackendPhase.READY, "Connection established")
    except ValueError:
        pass
    if progress_cb is not None:
        progress_cb(svr_name, "ready")


async def start_backend_svr(
    svr_name: str,
    svr_conf: Dict[str, Any],
    sessions: Dict[str, ClientSession],
    backend_stacks: Dict[str, AsyncExitStack],
    devnull: Any,
    status_records: Dict[str, Any],
    discovered_auth: Dict[str, Dict[str, Any]],
    auth_discovery_tasks: Dict[str, "asyncio.Task[Any]"],
    progress_cb: Optional[Callable[..., None]],
    shutdown_requested: bool,
    auth_providers: Optional[Dict[str, Any]] = None,
) -> bool:
    """Start and initialize a single backend server connection."""
    svr_type = svr_conf.get("type")
    logger.info("[%s] Attempting connection, type: %s...", svr_name, svr_type)

    startup_timeout: Optional[float] = None
    if svr_type != "stdio":
        startup_timeout = svr_conf.get("startup_timeout", STARTUP_TIMEOUT)

    record = ensure_status_record(svr_name, status_records)

    from argus_mcp.runtime.models import BackendPhase

    try:
        record.transition(BackendPhase.INITIALIZING, f"Connecting ({svr_type})")
    except ValueError:
        pass
    if progress_cb is not None:
        progress_cb(svr_name, "initializing", f"Connecting ({svr_type})")

    # Pre-build container image (outside startup timeout)
    if svr_type == "stdio" and "_prebuild_params" not in svr_conf:
        try:
            await pre_build_container_image(svr_name, svr_conf, progress_cb)
        except Exception as exc:  # noqa: BLE001
            msg = f"Container image pre-build failed: {exc}"
            logger.error("[%s] %s", svr_name, msg, exc_info=True)
            record_failure(svr_name, record, msg, progress_cb)
            return False

    try:
        if svr_type == "stdio":
            await connect_backend(
                svr_name,
                svr_conf,
                svr_type,
                record,
                sessions,
                backend_stacks,
                devnull,
                discovered_auth,
                progress_cb,
                auth_providers=auth_providers,
            )
        else:
            await asyncio.wait_for(
                connect_backend(
                    svr_name,
                    svr_conf,
                    svr_type,
                    record,
                    sessions,
                    backend_stacks,
                    devnull,
                    discovered_auth,
                    progress_cb,
                    auth_providers=auth_providers,
                ),
                timeout=startup_timeout,
            )
        return True

    except asyncio.TimeoutError:
        msg = f"Overall startup timed out after {startup_timeout}s (subprocess spawn + MCP init)"
        logger.error("[%s] (%s) %s", svr_name, svr_type or "unknown", msg)
        record_failure(svr_name, record, msg, progress_cb)
        return False

    except asyncio.CancelledError:
        reason = await handle_cancelled_error(
            svr_name,
            svr_conf,
            svr_type,
            shutdown_requested,
            auth_discovery_tasks,
            discovered_auth,
            progress_cb,
        )
        record_auth_pending_or_failure(
            svr_name,
            record,
            reason,
            auth_discovery_tasks,
            progress_cb,
        )
        return False

    except BaseException as e_start:  # noqa: BLE001
        reason = await handle_base_exception(
            svr_name,
            svr_conf,
            svr_type,
            e_start,
            shutdown_requested,
            auth_discovery_tasks,
            discovered_auth,
            progress_cb,
        )
        record_auth_pending_or_failure(
            svr_name,
            record,
            reason,
            auth_discovery_tasks,
            progress_cb,
        )
        return False
