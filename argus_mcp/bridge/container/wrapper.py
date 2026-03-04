"""Container wrapper — the main entry point for container isolation.

Replaces the old ``sandbox.py`` with a proper image-building approach:

1. **Already containerised** (command=docker) — pass through unchanged.
2. **Known transport** (uvx, npx) — build a custom image with the
   package pre-installed, then ``docker run`` the pre-built image.
3. **Unknown command** — fall back to bare subprocess with a warning.

This module is called from :meth:`ClientManager._connect_backend` for
every stdio backend.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from mcp import StdioServerParameters

from argus_mcp.bridge.container import runtime as crt
from argus_mcp.bridge.container.image_builder import (
    classify_command,
    ensure_image,
    is_already_containerised,
)
from argus_mcp.bridge.container.network import DEFAULT_NETWORK, effective_network

logger = logging.getLogger(__name__)

# ── Security defaults ────────────────────────────────────────────────────

_DEFAULT_CAP_DROP = ["ALL"]
_DEFAULT_MEMORY = "512m"
_DEFAULT_CPUS = "1"

# Cached runtime health — avoids re-probing Docker on every backend.
# ``None`` = not yet checked, ``True`` = healthy, ``False`` = unhealthy.
_runtime_healthy: Optional[bool] = None


# ── Public API ───────────────────────────────────────────────────────────


async def wrap_backend(
    svr_name: str,
    params: StdioServerParameters,
    *,
    network: Optional[str] = None,
    memory: Optional[str] = None,
    cpus: Optional[str] = None,
    volumes: Optional[List[str]] = None,
    extra_args: Optional[List[str]] = None,
) -> Tuple[StdioServerParameters, bool]:
    """Wrap a stdio backend in a container if possible.

    This is the **main entry point** for container isolation.  It
    replaces the old ``auto_wrap_stdio``.

    Parameters
    ----------
    svr_name:
        Backend name (for logging).
    params:
        Original ``StdioServerParameters`` from the config loader.
    network:
        Override network mode (``"bridge"``, ``"none"``, etc.).
        Defaults to ``"bridge"`` for built images, preserves existing
        settings for already-containerised backends.
    memory:
        Override memory limit (e.g. ``"1g"``).
    cpus:
        Override CPU limit (e.g. ``"2"``).
    volumes:
        Extra volume mounts (``["host:container[:ro]"]``).
    extra_args:
        Additional raw arguments for ``docker run``.

    Returns
    -------
    (wrapped_params, was_isolated)
        New parameters with the command wrapped in a container, and
        a boolean indicating whether isolation was applied.
    """
    # ── Check global disable ─────────────────────────────────────────
    env_val = os.environ.get("ARGUS_CONTAINER_ISOLATION", "").strip().lower()
    if env_val in ("0", "false", "no", "off", "disabled"):
        logger.debug(
            "[%s] Container isolation disabled via ARGUS_CONTAINER_ISOLATION.",
            svr_name,
        )
        return params, False

    # ── Already containerised? ───────────────────────────────────────
    args_list = list(params.args) if params.args else []
    if is_already_containerised(params.command, args_list):
        logger.info(
            "[%s] Backend command is already a container invocation "
            "('%s %s …'). Passing through unchanged.",
            svr_name,
            params.command,
            args_list[0] if args_list else "",
        )
        return params, False

    # ── Detect container runtime ─────────────────────────────────────
    container_runtime = crt.detect_runtime()
    if container_runtime is None:
        logger.warning(
            "[%s] No container runtime (docker/podman) found on $PATH. "
            "Running backend as bare subprocess (less secure).",
            svr_name,
        )
        return params, False

    # ── Runtime health check (cached) ────────────────────────────────
    global _runtime_healthy  # noqa: PLW0603
    if _runtime_healthy is None:
        _runtime_healthy = await crt.check_runtime_health(container_runtime)
    if not _runtime_healthy:
        logger.debug(
            "[%s] Container runtime unhealthy — running as bare subprocess.",
            svr_name,
        )
        return params, False

    # ── Classify command ─────────────────────────────────────────────
    transport = classify_command(params.command)
    if transport is None:
        logger.warning(
            "[%s] Unknown command '%s' — no container image mapping. "
            "Running as bare subprocess.",
            svr_name,
            params.command,
        )
        return params, False

    if transport == "docker":
        # Should have been caught by is_already_containerised above,
        # but handle edge cases (e.g. docker without run subcommand)
        return params, False

    # ── Build or reuse image ─────────────────────────────────────────
    image_tag, _binary, runtime_args = await ensure_image(
        svr_name,
        params.command,
        args_list,
        params.env,
        container_runtime,
    )

    if image_tag is None:
        # Image build failed — fall back to bare subprocess
        logger.warning(
            "[%s] Image build failed. Running '%s' as bare subprocess.",
            svr_name,
            params.command,
        )
        return params, False

    # ── Build docker run flags ───────────────────────────────────────
    net_mode = effective_network(network)
    mem = memory or _DEFAULT_MEMORY
    cpu = cpus or _DEFAULT_CPUS
    run_args = _build_run_args(
        image_tag=image_tag,
        runtime_args=runtime_args,
        env=params.env,
        network=net_mode,
        memory=mem,
        cpus=cpu,
        volumes=volumes,
        extra_args=extra_args,
    )

    logger.info(
        "[%s] Container isolation: wrapping in '%s run' "
        "(image=%s, network=%s, memory=%s, cpus=%s).",
        svr_name,
        container_runtime,
        image_tag,
        net_mode,
        mem,
        cpu,
    )

    wrapped = StdioServerParameters(
        command=container_runtime,
        args=run_args,
        env=None,  # env vars passed via -e inside container
    )
    return wrapped, True


# ── Internal helpers ─────────────────────────────────────────────────────


def _build_run_args(
    *,
    image_tag: str,
    runtime_args: List[str],
    env: Optional[Dict[str, str]],
    network: str,
    memory: str,
    cpus: str,
    volumes: Optional[List[str]] = None,
    extra_args: Optional[List[str]] = None,
) -> List[str]:
    """Build the complete ``docker run`` argument list.

    Returns the list: ``["run", "--rm", "-i", <flags>, <image>, <args>]``
    """
    args: List[str] = [
        "run",
        "--rm",
        "-i",
    ]

    # Network
    args.extend(["--network", network])

    # Resource limits
    args.extend(["--memory", memory])
    args.extend(["--cpus", cpus])

    # Security hardening
    args.append("--read-only")
    for cap in _DEFAULT_CAP_DROP:
        args.extend(["--cap-drop", cap])

    # Writable temp directories (some tools need /tmp)
    args.extend(["--tmpfs", "/tmp:rw,noexec,nosuid,size=64m"])

    # Volume mounts (from per-backend config)
    if volumes:
        for vol in volumes:
            args.extend(["-v", vol])

    # Environment variables — passed via -e flags so they're inside
    # the container.
    if env:
        for key, value in sorted(env.items()):
            args.extend(["-e", f"{key}={value}"])

    # Extra raw arguments from per-backend config
    if extra_args:
        args.extend(extra_args)

    # Image and runtime args
    args.append(image_tag)
    args.extend(runtime_args)

    return args
