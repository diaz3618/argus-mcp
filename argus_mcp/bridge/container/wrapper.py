"""Container wrapper — the main entry point for container isolation.

Replaces the old ``sandbox.py`` with a proper image-building approach:

1. **Already containerised** (command=docker) — pass through unchanged.
2. **Known transport** (uvx, npx) — build a custom image with the
   package pre-installed, then pre-create the container and use
   ``docker start -ai`` to attach stdio streams.
3. **Unknown command** — fall back to bare subprocess with a warning.

Uses a two-step container lifecycle (``docker create`` + ``docker start -ai``)
instead of ``docker run`` to avoid stdio attach hangs observed on some Docker
daemon + storage-driver + SELinux combinations.

This module is called from :meth:`ClientManager._connect_backend` for
every stdio backend.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable, Dict, List, Optional, Tuple

from mcp import StdioServerParameters

from argus_mcp.bridge.container.image_builder import (
    classify_command,
    ensure_image,
    is_already_containerised,
)
from argus_mcp.bridge.container.network import effective_network
from argus_mcp.bridge.container.runtime import RuntimeFactory
from argus_mcp.bridge.container.templates.models import CONTAINER_HOME

logger = logging.getLogger(__name__)

# ── Security defaults ────────────────────────────────────────────────────

_DEFAULT_CAP_DROP = ["ALL"]
_DEFAULT_MEMORY = "512m"
_DEFAULT_CPUS = "1"

# ── Container tracking ───────────────────────────────────────────────────

#: Maps ``svr_name`` → ``(container_runtime, container_id)`` for cleanup.
_active_containers: Dict[str, Tuple[str, str]] = {}


# ── Public API ───────────────────────────────────────────────────────────


async def wrap_backend(
    svr_name: str,
    params: StdioServerParameters,
    *,
    enabled: bool = True,
    runtime_override: Optional[str] = None,
    network: Optional[str] = None,
    memory: Optional[str] = None,
    cpus: Optional[str] = None,
    volumes: Optional[List[str]] = None,
    extra_args: Optional[List[str]] = None,
    build_if_missing: bool = True,
    system_deps: Optional[List[str]] = None,
    builder_image: Optional[str] = None,
    additional_packages: Optional[List[str]] = None,
    transport_override: Optional[str] = None,
    go_package: Optional[str] = None,
    create_timeout: float = 120.0,
    line_callback: Optional[Callable[[str], None]] = None,
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
    enabled:
        Per-backend container isolation toggle.  When ``False``, the
        backend runs as a bare subprocess regardless of other settings.
        Defaults to ``True`` (container isolation on).
    runtime_override:
        Force a specific container runtime (``"docker"``, ``"podman"``).
        When ``None``, the :class:`RuntimeFactory` auto-detects.
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
    build_if_missing:
        If ``False``, only use cached images — never trigger a build.
        When no cached image exists, falls back to bare subprocess.
        This is used during server startup to avoid blocking on lengthy
        first-run image builds.  Run ``argus-mcp build`` to pre-build.
    create_timeout:
        Timeout in seconds for ``docker create``.  On slower systems
        (e.g. overlayfs, high disk utilisation) a single create can
        take 10–20 s and concurrent creates contest the daemon.
        Defaults to 120 s.

    Returns
    -------
    (wrapped_params, was_isolated)
        New parameters with the command wrapped in a container, and
        a boolean indicating whether isolation was applied.
    """
    # ── Per-backend disable ──────────────────────────────────────────
    if not enabled:
        logger.debug(
            "[%s] Container isolation disabled via per-backend config.",
            svr_name,
        )
        return params, False

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

    # ── Detect container runtime via factory ─────────────────────────
    factory = RuntimeFactory.get()
    runtime = factory.detect(override=runtime_override)
    if runtime is None:
        logger.warning(
            "[%s] No container runtime (docker/podman) found on $PATH. "
            "Running backend as bare subprocess (less secure).",
            svr_name,
        )
        return params, False

    container_runtime = runtime.name  # "docker" or "podman"

    # ── Runtime health check (cached inside the runtime instance) ────
    if not await runtime.is_healthy():
        logger.debug(
            "[%s] Container runtime '%s' unhealthy — running as bare subprocess.",
            svr_name,
            container_runtime,
        )
        return params, False

    # ── Classify command ─────────────────────────────────────────────
    transport = transport_override or classify_command(params.command)
    if transport is None:
        logger.warning(
            "[%s] Unknown command '%s' — no container image mapping. Running as bare subprocess.",
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
        build_if_missing=build_if_missing,
        system_deps=system_deps,
        builder_image=builder_image,
        additional_packages=additional_packages,
        transport_override=transport_override,
        go_package=go_package,
        line_callback=line_callback,
    )

    if image_tag is None:
        # Image build failed — fall back to bare subprocess
        logger.warning(
            "[%s] Image build failed. Running '%s' as bare subprocess.",
            svr_name,
            params.command,
        )
        return params, False

    # ── Pre-create container (docker create) ────────────────────────
    net_mode = effective_network(network)
    mem = memory or _DEFAULT_MEMORY
    cpu = cpus or _DEFAULT_CPUS
    create_args = _build_create_args(
        image_tag=image_tag,
        runtime_args=runtime_args,
        env=params.env,
        network=net_mode,
        memory=mem,
        cpus=cpu,
        volumes=volumes,
        extra_args=extra_args,
    )

    container_id = await _create_container(container_runtime, create_args, timeout=create_timeout)
    if container_id is None:
        logger.warning(
            "[%s] Container pre-creation failed. Running '%s' as bare subprocess.",
            svr_name,
            params.command,
        )
        return params, False

    # Track for cleanup
    _active_containers[svr_name] = (container_runtime, container_id)

    logger.info(
        "[%s] Container isolation: pre-created %s "
        "(image=%s, network=%s, memory=%s, cpus=%s). "
        "Will attach via 'start -ai'.",
        svr_name,
        container_id[:12],
        image_tag,
        net_mode,
        mem,
        cpu,
    )

    wrapped = StdioServerParameters(
        command=container_runtime,
        args=["start", "-ai", container_id],
        env=None,  # env vars baked in via -e at create time
    )
    return wrapped, True


# ── Internal helpers ─────────────────────────────────────────────────────


def _build_create_args(
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
    """Build the complete ``docker create`` argument list.

    Uses a two-step lifecycle: ``create`` + ``start -ai`` instead of
    ``docker run`` to avoid stdio attach hangs observed on certain
    Docker + storage-driver + SELinux combinations.

    Returns the list: ``["create", "--rm", "-i", <flags>, <image>, <args>]``
    """
    args: List[str] = [
        "create",
        "--rm",
        "-i",
    ]

    # Process management — ensure PID 1 is a proper init so signals
    # propagate correctly to child processes inside the container.
    args.append("--init")

    # Network
    args.extend(["--network", network])

    # Resource limits
    args.extend(["--memory", memory])
    args.extend(["--cpus", cpus])

    # Security hardening
    args.append("--read-only")
    for cap in _DEFAULT_CAP_DROP:
        args.extend(["--cap-drop", cap])
    args.extend(["--security-opt", "no-new-privileges"])

    # SELinux — disable label confinement so the container can read
    # mounted volumes and communicate on the stdio pipe.  Without this,
    # Enforcing-mode SELinux (e.g. Fedora) may silently block I/O.
    args.extend(["--security-opt", "label=disable"])

    # Writable directories — images run as a non-root user (UID 65532,
    # the distroless/Chainguard "nonroot" standard).  Read-only root FS
    # means we must provide tmpfs for dirs that tools may need to write
    # to (caches, temp files, .pyc, etc.).
    #
    # We use ``mode=1777`` (world-writable with sticky bit) instead of
    # ``uid=`` / ``gid=`` mount options.  This **decouples** the tmpfs
    # from any specific UID — the mounts work regardless of which user
    # the container process runs as.  This is the standard permission
    # model used by ``/tmp`` on every Linux system.
    args.extend(["--tmpfs", "/tmp:rw,nosuid,size=64m,mode=1777"])
    args.extend(["--tmpfs", f"{CONTAINER_HOME}:rw,nosuid,size=64m,mode=1777"])

    # Ensure HOME and TMPDIR point to writable locations inside the
    # container.  These are injected BEFORE user-supplied env vars so
    # that per-backend config can override them if needed.
    args.extend(["-e", f"HOME={CONTAINER_HOME}"])
    args.extend(["-e", "TMPDIR=/tmp"])

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


async def _create_container(
    runtime: str,
    create_args: List[str],
    timeout: float = 120.0,
) -> Optional[str]:
    """Run ``docker create`` and return the container ID.

    Returns ``None`` on any failure (build/daemon error, timeout, etc.).
    The caller falls back to bare subprocess in that case.

    The default timeout is generous (120 s) because on systems with
    overlayfs, high disk utilisation, or SELinux enforcement a single
    ``docker create`` can take 10–20 s, and concurrent creates contend
    for daemon locks.
    """
    cmd = [runtime] + create_args
    logger.debug("Pre-creating container: %s", " ".join(cmd[:8]) + " …")

    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            ),
            timeout=timeout,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        logger.error("docker create timed out after %.0fs", timeout)
        return None
    except OSError as exc:
        logger.error("docker create exec error: %s", exc)
        return None

    if proc.returncode != 0:
        err_msg = stderr.decode(errors="replace").strip()
        logger.error(
            "docker create failed (rc=%d): %s",
            proc.returncode,
            err_msg[:200],
        )
        return None

    container_id = stdout.decode().strip()
    if not container_id:
        logger.error("docker create returned empty container ID")
        return None

    logger.debug("Pre-created container: %s", container_id[:12])
    return container_id


async def cleanup_container(svr_name: str) -> None:
    """Remove a pre-created container for the given backend.

    Safe to call even if no container exists for *svr_name*.
    """
    entry = _active_containers.pop(svr_name, None)
    if entry is None:
        return

    runtime, cid = entry
    logger.debug("[%s] Cleaning up container %s", svr_name, cid[:12])
    try:
        proc = await asyncio.create_subprocess_exec(
            runtime,
            "rm",
            "-f",
            cid,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), timeout=10.0)
    except Exception:
        logger.debug(
            "[%s] Failed to cleanup container %s (may already be removed)",
            svr_name,
            cid[:12],
        )


async def cleanup_all_containers() -> None:
    """Remove **all** tracked pre-created containers.

    Called during server shutdown to ensure no orphan containers remain.
    """
    names = list(_active_containers.keys())
    if not names:
        return
    logger.info("Cleaning up %d tracked container(s)…", len(names))
    for name in names:
        await cleanup_container(name)


@asynccontextmanager
async def container_cleanup_context(svr_name: str) -> AsyncIterator[None]:
    """Async context manager that cleans up the container on exit.

    Usage::

        async with container_cleanup_context("my-backend"):
            # … use the container …
        # container is removed here
    """
    try:
        yield
    finally:
        await cleanup_container(svr_name)
