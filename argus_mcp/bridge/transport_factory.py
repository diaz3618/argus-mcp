"""Transport creation for MCP backend connections.

Encapsulates the three supported transport types (stdio, SSE,
streamable-HTTP) and the dispatch logic that selects the correct one
based on backend configuration.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional, TextIO, Tuple

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from argus_mcp.constants import SSE_LOCAL_START_DELAY
from argus_mcp.errors import BackendServerError, ConfigurationError

logger = logging.getLogger(__name__)


# ── Low-level transport initializers ─────────────────────────────────────


async def init_stdio(
    svr_name: str,
    stdio_cfg: StdioServerParameters,
    devnull: TextIO,
    stack: AsyncExitStack,
) -> Tuple[Any, ClientSession]:
    """Create a stdio transport and session on *stack*."""
    logger.debug("[%s] Stdio backend, preparing stdio_client.", svr_name)
    transport_ctx = stdio_client(stdio_cfg, errlog=devnull)
    streams = await stack.enter_async_context(transport_ctx)
    logger.debug("[%s] (stdio) transport streams established.", svr_name)
    session_ctx = ClientSession(*streams)
    session = await stack.enter_async_context(session_ctx)
    return transport_ctx, session


async def init_sse(
    svr_name: str,
    sse_url: str,
    sse_cmd: Optional[str],
    sse_cmd_args: List[str],
    sse_cmd_env: Optional[Dict[str, str]],
    stack: AsyncExitStack,
    *,
    sse_startup_delay: float = SSE_LOCAL_START_DELAY,
    headers: Optional[Dict[str, str]] = None,
    manage_subproc: Any = None,
) -> Tuple[Any, ClientSession]:
    """Create an SSE transport and session on *stack*.

    If *sse_cmd* is set and *manage_subproc* is provided, the subprocess
    is started first.
    """
    if sse_cmd and manage_subproc is not None:
        logger.info(
            "[%s] Local launch command configured, starting SSE subprocess...",
            svr_name,
        )
        await stack.enter_async_context(
            manage_subproc(sse_cmd, sse_cmd_args, sse_cmd_env, svr_name)
        )
        logger.info(
            "[%s] Waiting %ss for local SSE server startup...",
            svr_name,
            sse_startup_delay,
        )
        await asyncio.sleep(sse_startup_delay)

    transport_ctx = sse_client(url=sse_url, headers=headers)
    streams = await stack.enter_async_context(transport_ctx)
    logger.debug("[%s] (sse) transport streams established.", svr_name)
    session_ctx = ClientSession(*streams)
    session = await stack.enter_async_context(session_ctx)
    return transport_ctx, session


async def init_streamablehttp(
    svr_name: str,
    url: str,
    stack: AsyncExitStack,
    *,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[Any, ClientSession]:
    """Create a streamable-HTTP transport and session on *stack*."""
    logger.debug("[%s] Streamable-HTTP backend, url=%s", svr_name, url)
    transport_ctx = streamablehttp_client(url=url, headers=headers)
    read_stream, write_stream, _get_session_id = await stack.enter_async_context(transport_ctx)
    logger.debug("[%s] (streamable-http) transport streams established.", svr_name)
    session_ctx = ClientSession(read_stream, write_stream)
    session = await stack.enter_async_context(session_ctx)
    return transport_ctx, session


# ── Stdio parameter resolution ───────────────────────────────────────────


async def resolve_stdio_params(
    svr_name: str,
    svr_conf: Dict[str, Any],
) -> Tuple[StdioServerParameters, bool]:
    """Resolve stdio parameters, using pre-built or inline container wrapping."""
    stdio_params = svr_conf.get("params")
    if not isinstance(stdio_params, StdioServerParameters):
        raise ConfigurationError(
            f"Invalid stdio config for server '{svr_name}' ('params' type mismatch)."
        )
    prebuild_params = svr_conf.pop("_prebuild_params", None)
    prebuild_isolated = svr_conf.pop("_prebuild_isolated", None)

    if prebuild_params is not None:
        return prebuild_params, prebuild_isolated or False

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


# ── Network environment injection ────────────────────────────────────────


def apply_network_env(
    svr_name: str,
    svr_conf: Dict[str, Any],
    params: StdioServerParameters,
) -> StdioServerParameters:
    """Inject HTTP_PROXY / NO_PROXY env vars from network isolation config."""
    net_cfg = svr_conf.get("network")
    if not isinstance(net_cfg, dict):
        return params

    mode = net_cfg.get("network_mode", "host")
    if mode == "host":
        return params

    env = dict(params.env or {})

    if mode == "none":
        env.setdefault("HTTP_PROXY", "http://0.0.0.0:0")  # noqa: S104
        env.setdefault("HTTPS_PROXY", "http://0.0.0.0:0")  # noqa: S104
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


# ── High-level dispatcher ────────────────────────────────────────────────


def _merge_headers(
    conf_headers: Optional[Dict[str, str]],
    auth_headers: Optional[Dict[str, str]],
) -> Optional[Dict[str, str]]:
    """Merge config-level and auth headers, preferring auth."""
    if not conf_headers and not auth_headers:
        return None
    merged: Dict[str, str] = {}
    if conf_headers:
        merged.update(conf_headers)
    if auth_headers:
        merged.update(auth_headers)
    return merged


async def create_transport_session(
    svr_name: str,
    svr_conf: Dict[str, Any],
    svr_type: Optional[str],
    auth_headers: Optional[Dict[str, str]],
    backend_stack: AsyncExitStack,
    devnull: TextIO,
    *,
    manage_subproc: Any = None,
) -> ClientSession:
    """Dispatch to the correct transport initializer and return the session."""
    if svr_type == "stdio":
        stdio_params, _isolated = await resolve_stdio_params(svr_name, svr_conf)
        if not _isolated:
            stdio_params = apply_network_env(svr_name, svr_conf, stdio_params)
        _, session = await init_stdio(
            svr_name,
            stdio_params,
            devnull,
            backend_stack,
        )

    elif svr_type == "sse":
        sse_url = svr_conf.get("url")
        if not isinstance(sse_url, str) or not sse_url:
            raise ConfigurationError(f"Invalid SSE 'url' configuration for server '{svr_name}'.")
        sse_headers = _merge_headers(svr_conf.get("headers"), auth_headers)
        _, session = await init_sse(
            svr_name,
            sse_url,
            svr_conf.get("command"),
            svr_conf.get("args", []),
            svr_conf.get("env"),
            backend_stack,
            sse_startup_delay=svr_conf.get("sse_startup_delay", SSE_LOCAL_START_DELAY),
            headers=sse_headers,
            manage_subproc=manage_subproc,
        )

    elif svr_type == "streamable-http":
        sh_url = svr_conf.get("url")
        if not isinstance(sh_url, str) or not sh_url:
            raise ConfigurationError(
                f"Invalid streamable-http 'url' configuration for server '{svr_name}'."
            )
        sh_headers = _merge_headers(svr_conf.get("headers"), auth_headers)
        _, session = await init_streamablehttp(
            svr_name,
            sh_url,
            backend_stack,
            headers=sh_headers,
        )

    else:
        raise ConfigurationError(f"Unsupported server type '{svr_type}' for server '{svr_name}'.")

    if not session:
        raise BackendServerError(f"[{svr_name}] ({svr_type}) Session could not be created.")
    return session
