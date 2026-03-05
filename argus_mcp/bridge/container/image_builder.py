"""Image builder — generates Dockerfiles and builds OCI images.

This module handles the entire image lifecycle:

1. Parse the backend command and args to determine the transport type.
2. Generate a Dockerfile from the appropriate template.
3. Compute a content-hash-based image tag for caching.
4. Build the image if it is not already available locally.
5. Return the image tag for use by the container wrapper.

Images are cached locally by content-hash tag — they only rebuild
when the Dockerfile changes (e.g. package version bump).
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Dict, List, Optional, Tuple

from argus_mcp.bridge.container import runtime as crt
from argus_mcp.bridge.container.templates import (
    compute_image_tag,
    generate_npx_dockerfile,
    generate_uvx_dockerfile,
    parse_npx_args,
    parse_uvx_args,
)

logger = logging.getLogger(__name__)

# ── Transport type from command ──────────────────────────────────────────

# Maps command basenames to the transport type used for Dockerfile selection.
_COMMAND_TRANSPORT: Dict[str, str] = {
    "uvx": "uvx",
    "uv": "uvx",
    "pip": "uvx",
    "pipx": "uvx",
    "python": "uvx",
    "python3": "uvx",
    "npx": "npx",
    "node": "npx",
    "tsx": "npx",
}


def classify_command(command: str) -> Optional[str]:
    """Classify a command as a known transport type.

    Returns ``"uvx"``, ``"npx"``, ``"docker"``, or ``None`` for
    unrecognised commands.
    """
    basename = command.rsplit("/", 1)[-1].strip().lower()
    if basename == "docker":
        return "docker"
    return _COMMAND_TRANSPORT.get(basename)


def is_already_containerised(command: str, args: List[str]) -> bool:
    """Detect if the command is already a ``docker run`` invocation.

    This handles the pattern in config.yaml where a backend is::

        command: docker
        args: ["run", "-i", "--rm", ...]

    Such backends are already containerised and should NOT be wrapped.
    """
    basename = command.rsplit("/", 1)[-1].strip().lower()
    if basename in ("docker", "podman"):
        # Check if the first arg is a docker subcommand that runs containers
        if args and args[0] in ("run", "exec", "start", "compose"):
            return True
    return False


# ── Image building ───────────────────────────────────────────────────────


async def ensure_image(
    svr_name: str,
    command: str,
    args: List[str],
    env: Optional[Dict[str, str]],
    container_runtime: str,
    *,
    build_if_missing: bool = True,
) -> Tuple[Optional[str], str, List[str]]:
    """Ensure an OCI image exists for the backend and return build info.

    Parameters
    ----------
    svr_name:
        Backend name (for logging).
    command:
        The backend command (``uvx``, ``npx``, etc.).
    args:
        The backend args list.
    env:
        Backend environment variables (may contain build-relevant values).
    container_runtime:
        ``"docker"`` or ``"podman"``.
    build_if_missing:
        If ``False``, only return a cached image — never trigger a build.
        This is used during server startup to avoid blocking on lengthy
        first-run image builds.  Run ``argus-mcp build`` to pre-build
        images offline.

    Returns
    -------
    (image_tag, entrypoint_binary, runtime_args)
        The image tag (or ``None`` if building failed), the binary that
        the container will run as its entrypoint, and the remaining
        arguments that should be passed at ``docker run`` time.
    """
    transport = classify_command(command)
    if not transport or transport == "docker":
        return None, command, list(args)

    if transport == "uvx":
        return await _ensure_uvx_image(
            svr_name, args, env, container_runtime,
            build_if_missing=build_if_missing,
        )
    elif transport == "npx":
        return await _ensure_npx_image(
            svr_name, args, env, container_runtime,
            build_if_missing=build_if_missing,
        )

    return None, command, list(args)


async def _ensure_uvx_image(
    svr_name: str,
    args: List[str],
    env: Optional[Dict[str, str]],
    container_runtime: str,
    *,
    build_if_missing: bool = True,
) -> Tuple[Optional[str], str, List[str]]:
    """Build (or reuse) a uvx image."""
    package, binary, runtime_args = parse_uvx_args(args)

    dockerfile = generate_uvx_dockerfile(package, binary)
    image_tag = compute_image_tag("uvx", package, dockerfile)

    # Check if image already exists
    if await crt.image_exists(container_runtime, image_tag):
        logger.info(
            "[%s] Reusing cached image '%s' for uvx package '%s'.",
            svr_name, image_tag, package,
        )
        return image_tag, binary, runtime_args

    if not build_if_missing:
        logger.info(
            "[%s] Image '%s' not cached for uvx package '%s'. "
            "Skipping build — running as bare subprocess. "
            "Run 'argus-mcp build' to pre-build container images.",
            svr_name, image_tag, package,
        )
        return None, "uvx", list(args)

    # Build the image
    logger.info(
        "[%s] Building image for uvx package '%s' → '%s'…",
        svr_name, package, image_tag,
    )
    success = await _build_from_string(container_runtime, image_tag, dockerfile)
    if not success:
        logger.error(
            "[%s] Failed to build image for uvx package '%s'. "
            "Will fall back to bare subprocess.",
            svr_name, package,
        )
        return None, "uvx", list(args)

    return image_tag, binary, runtime_args


async def _ensure_npx_image(
    svr_name: str,
    args: List[str],
    env: Optional[Dict[str, str]],
    container_runtime: str,
    *,
    build_if_missing: bool = True,
) -> Tuple[Optional[str], str, List[str]]:
    """Build (or reuse) an npx image."""
    package, runtime_args = parse_npx_args(args)

    dockerfile = generate_npx_dockerfile(package)
    image_tag = compute_image_tag("npx", package, dockerfile)

    # Check if image already exists
    if await crt.image_exists(container_runtime, image_tag):
        logger.info(
            "[%s] Reusing cached image '%s' for npx package '%s'.",
            svr_name, image_tag, package,
        )
        return image_tag, package, runtime_args

    if not build_if_missing:
        logger.info(
            "[%s] Image '%s' not cached for npx package '%s'. "
            "Skipping build — running as bare subprocess. "
            "Run 'argus-mcp build' to pre-build container images.",
            svr_name, image_tag, package,
        )
        return None, "npx", list(args)

    # Build the image
    logger.info(
        "[%s] Building image for npx package '%s' → '%s'…",
        svr_name, package, image_tag,
    )
    success = await _build_from_string(container_runtime, image_tag, dockerfile)
    if not success:
        logger.error(
            "[%s] Failed to build image for npx package '%s'. "
            "Will fall back to bare subprocess.",
            svr_name, package,
        )
        return None, "npx", list(args)

    return image_tag, package, runtime_args


async def _build_from_string(
    container_runtime: str,
    image_tag: str,
    dockerfile_content: str,
) -> bool:
    """Write a Dockerfile string to a temp directory and build it."""
    with tempfile.TemporaryDirectory(prefix="argus_build_") as tmpdir:
        df_path = os.path.join(tmpdir, "Dockerfile")
        with open(df_path, "w", encoding="utf-8") as f:
            f.write(dockerfile_content)

        return await crt.build_image(
            container_runtime,
            tmpdir,
            image_tag,
            dockerfile=df_path,
        )
