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
import contextlib
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator, Callable, Dict, List, Optional, Tuple

from mcp import StdioServerParameters

from argus_mcp.bridge.container.go_docker_adapter import (
    GoDockerAdapter,
)
from argus_mcp.bridge.container.go_docker_adapter import (
    is_available as _go_adapter_available,
)
from argus_mcp.bridge.container.image_builder import (
    classify_command,
    ensure_image,
    is_already_containerised,
)
from argus_mcp.bridge.container.network import effective_network
from argus_mcp.bridge.container.runtime import RuntimeFactory
from argus_mcp.bridge.container.templates.models import CONTAINER_HOME
from argus_mcp.constants import EXIT_STACK_CLOSE_TIMEOUT

logger = logging.getLogger(__name__)

_DEFAULT_CAP_DROP = ["ALL"]
_DEFAULT_MEMORY = "512m"
_DEFAULT_CPUS = "1"

#: Maps ``svr_name`` → ``(container_runtime, container_id)`` for cleanup.
_active_containers: Dict[str, Tuple[str, str]] = {}

_MEM_SUFFIXES = {"k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}

_PATH_TRAVERSAL_PATTERN = ".."


def _validate_volume_sources(svr_name: str, volumes: Optional[List[str]]) -> Optional[List[str]]:
    """Validate volume mount source paths exist on the host.

    Returns the validated list (unchanged) or ``None`` if the input was
    ``None``.  Logs a warning for each source path that is missing so
    operators can diagnose "Connection closed" errors caused by bind
    mounts to non-existent directories.
    """
    if not volumes:
        return volumes
    for vol in volumes:
        parts = vol.split(":")
        if len(parts) >= 2:
            src = parts[0]
            if _PATH_TRAVERSAL_PATTERN in src:
                logger.warning(
                    "[%s] Volume source path contains '..': '%s' — "
                    "use absolute paths to avoid path traversal.",
                    svr_name,
                    src,
                )
            elif not os.path.exists(src):
                logger.warning(
                    "[%s] Volume source path does not exist: '%s'. "
                    "The backend may fail to start. Create the directory "
                    "before starting the server.",
                    svr_name,
                    src,
                )
    return volumes


def _parse_memory_string(mem: str) -> int:
    """Parse a Docker-style memory string (e.g. ``512m``) to bytes."""
    mem = mem.strip().lower()
    if not mem:
        return 0
    suffix = mem[-1]
    if suffix in _MEM_SUFFIXES:
        return int(mem[:-1]) * _MEM_SUFFIXES[suffix]
    return int(mem)


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
    build_system_deps: Optional[List[str]] = None,
    builder_image: Optional[str] = None,
    additional_packages: Optional[List[str]] = None,
    transport_override: Optional[str] = None,
    go_package: Optional[str] = None,
    source_url: Optional[str] = None,
    build_steps: Optional[List[str]] = None,
    entrypoint: Optional[List[str]] = None,
    build_env: Optional[Dict[str, str]] = None,
    source_ref: Optional[str] = None,
    dockerfile: Optional[str] = None,
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

    if not enabled:
        logger.debug(
            "[%s] Container isolation disabled via per-backend config.",
            svr_name,
        )
        return params, False

    env_val = os.environ.get("ARGUS_CONTAINER_ISOLATION", "").strip().lower()
    if env_val in ("0", "false", "no", "off", "disabled"):
        logger.debug(
            "[%s] Container isolation disabled via ARGUS_CONTAINER_ISOLATION.",
            svr_name,
        )
        return params, False

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

    if not await runtime.is_healthy():
        logger.debug(
            "[%s] Container runtime '%s' unhealthy — running as bare subprocess.",
            svr_name,
            container_runtime,
        )
        return params, False

    # Source-build and custom dockerfile skip normal transport classification.
    if not (source_url or dockerfile):
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

    image_tag, _binary, runtime_args = await ensure_image(
        svr_name,
        params.command,
        args_list,
        params.env,
        container_runtime,
        build_if_missing=build_if_missing,
        system_deps=system_deps,
        build_system_deps=build_system_deps,
        builder_image=builder_image,
        additional_packages=additional_packages,
        transport_override=transport_override,
        go_package=go_package,
        source_url=source_url,
        build_steps=build_steps,
        entrypoint=entrypoint,
        build_env=build_env,
        source_ref=source_ref,
        dockerfile=dockerfile,
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

    # Clean up any existing container for this backend (e.g. from a
    # previous failed attempt) before creating a new one.
    if svr_name in _active_containers:
        await cleanup_container(svr_name)

    # Also remove any leftover Docker container with the same --name from a
    # previous server session (not tracked in _active_containers).
    await _remove_stale_named_container(container_runtime, svr_name)

    net_mode = effective_network(network)
    mem = memory or _DEFAULT_MEMORY
    cpu = cpus or _DEFAULT_CPUS

    # Validate volume mount source paths exist on the host.
    volumes = _validate_volume_sources(svr_name, volumes)

    # Try Go adapter first for container creation, fall back to subprocess.
    container_id: Optional[str] = None
    if _go_adapter_available():
        container_id = await _go_adapter_create(
            image_tag=image_tag,
            svr_name=svr_name,
            runtime_args=runtime_args,
            env=params.env,
            network=net_mode,
            memory=mem,
            cpus=cpu,
            volumes=volumes,
        )

    if container_id is None:
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
        container_id = await _create_container(
            container_runtime, create_args, timeout=create_timeout
        )
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


async def _go_adapter_create(
    *,
    image_tag: str,
    svr_name: str,
    runtime_args: List[str],
    env: Optional[Dict[str, str]],
    network: str,
    memory: str,
    cpus: str,
    volumes: Optional[List[str]] = None,
) -> Optional[str]:
    """Try creating a container via the Go adapter.

    Returns the container ID on success, ``None`` on any failure so
    the caller can fall back to the subprocess path.
    """
    # Merge writable-dir env vars with user env
    full_env: Dict[str, str] = {
        "HOME": CONTAINER_HOME,
        "TMPDIR": "/tmp",  # noqa: S108 — container-internal tmpfs, not host /tmp
    }
    if env:
        full_env.update(env)

    # Prepend tmpfs-style writable volume mounts
    all_volumes = [
        "/tmp:/tmp:rw",  # noqa: S108 — container-internal tmpfs mount
        f"{CONTAINER_HOME}:{CONTAINER_HOME}:rw",
    ]
    if volumes:
        all_volumes.extend(volumes)

    adapter = GoDockerAdapter()
    try:
        await adapter.start()
        cid = await adapter.create(
            image=image_tag,
            name=svr_name,
            cmd=runtime_args or None,
            env=full_env,
            network=network,
            memory=_parse_memory_string(memory),
            cpus=float(cpus),
            volumes=all_volumes,
            read_only=True,
            cap_drop=_DEFAULT_CAP_DROP,
        )
        return cid
    except Exception:  # noqa: BLE001
        logger.debug(
            "[%s] Go adapter create failed, will fall back to subprocess.",
            svr_name,
            exc_info=True,
        )
        return None
    finally:
        await adapter.stop()


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


async def _remove_stale_named_container(runtime: str, name: str) -> None:
    """Remove a leftover Docker container by *name* if it exists.

    This handles containers left behind from a previous server session
    that are not tracked in ``_active_containers``.  Safe to call even
    when no container with the given name exists.

    Uses ``docker rm -f`` with a generous timeout.  If the first attempt
    times out (can happen under Docker daemon load), a second attempt is
    made after a short backoff.
    """
    for attempt in range(2):
        try:
            proc = await asyncio.create_subprocess_exec(
                runtime,
                "rm",
                "-f",
                name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=30.0)
            return  # success (or container didn't exist — both fine)
        except asyncio.TimeoutError:
            # Kill the hung process before retrying.
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            if attempt == 0:
                logger.debug(
                    "[%s] docker rm -f timed out, retrying after 2 s…",
                    name,
                )
                await asyncio.sleep(2)
        except Exception:  # noqa: BLE001
            logger.debug(
                "[%s] Failed to remove stale container (attempt %d).",
                name,
                attempt + 1,
                exc_info=True,
            )
            return  # non-timeout error — no point retrying


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
        await asyncio.wait_for(proc.wait(), timeout=EXIT_STACK_CLOSE_TIMEOUT)
    except Exception:  # noqa: BLE001
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
