"""Container runtime detection and management.

Discovers Docker or Podman on ``$PATH`` and provides helpers for
interacting with the container runtime CLI (build, inspect, run).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from typing import Optional

logger = logging.getLogger(__name__)

# ── Health-check timeout ─────────────────────────────────────────────────
# How long to wait for ``<runtime> version`` before declaring the
# runtime unhealthy.  This catches cases where the daemon is installed
# but unresponsive (e.g. resource contention, broken socket).
_HEALTH_CHECK_TIMEOUT: float = 10.0


def detect_runtime() -> Optional[str]:
    """Detect a supported container runtime on ``$PATH``.

    Returns ``"docker"``, ``"podman"``, or ``None``.
    Docker is preferred when both are available.
    """
    for runtime in ("docker", "podman"):
        if shutil.which(runtime):
            return runtime
    return None


async def check_runtime_health(runtime: str) -> bool:
    """Quick health probe — can the daemon respond within timeout?

    Runs ``<runtime> version`` and returns ``True`` only if the
    command completes successfully within ``_HEALTH_CHECK_TIMEOUT``
    seconds.  This prevents the server from hanging when the Docker
    daemon is installed but broken or extremely slow.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            runtime, "version",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        rc = await asyncio.wait_for(proc.wait(), timeout=_HEALTH_CHECK_TIMEOUT)
        return rc == 0
    except asyncio.TimeoutError:
        logger.warning(
            "Container runtime '%s' health check timed out after %.0fs. "
            "The daemon may be unresponsive.  Falling back to bare "
            "subprocess for all backends.",
            runtime,
            _HEALTH_CHECK_TIMEOUT,
        )
        # Kill the hung process
        try:
            proc.kill()  # type: ignore[possibly-undefined]
        except Exception:
            pass
        return False
    except Exception as exc:
        logger.warning(
            "Container runtime '%s' health check failed: %s. "
            "Falling back to bare subprocess.",
            runtime,
            exc,
        )
        return False


async def image_exists(runtime: str, image_tag: str) -> bool:
    """Check whether *image_tag* exists in the local image store.

    Uses ``<runtime> image inspect`` which only checks locally and
    does not pull from a remote registry.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            runtime, "image", "inspect", image_tag,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        rc = await proc.wait()
        return rc == 0
    except Exception:
        return False


async def pull_image(runtime: str, image: str) -> bool:
    """Pull *image* from a remote registry.

    Returns ``True`` on success.
    """
    logger.info("Pulling image '%s' via %s…", image, runtime)
    try:
        proc = await asyncio.create_subprocess_exec(
            runtime, "pull", image,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            logger.error(
                "Failed to pull image '%s': %s",
                image,
                stderr.decode(errors="replace").strip(),
            )
            return False
        return True
    except Exception as exc:
        logger.error("Error pulling image '%s': %s", image, exc)
        return False


async def build_image(
    runtime: str,
    context_dir: str,
    image_tag: str,
    *,
    dockerfile: str = "Dockerfile",
) -> bool:
    """Build a container image from *context_dir*.

    Uses ``<runtime> build -t <image_tag> -f <dockerfile> <context_dir>``.
    Stdout is discarded (build progress can be enormous with buildkit).
    Stderr is captured only for error diagnosis.
    Returns ``True`` on success.
    """
    logger.info("Building image '%s' from '%s'…", image_tag, context_dir)
    try:
        proc = await asyncio.create_subprocess_exec(
            runtime, "build",
            "--progress=plain",
            "-t", image_tag,
            "-f", dockerfile,
            context_dir,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode != 0:
            err_text = stderr.decode(errors="replace").strip() if stderr else ""
            logger.error("Image build failed for '%s': %s", image_tag, err_text[-2000:])
            return False
        logger.info("Image '%s' built successfully.", image_tag)
        return True
    except Exception as exc:
        logger.error("Error building image '%s': %s", image_tag, exc)
        return False


async def remove_image(runtime: str, image_tag: str) -> None:
    """Remove a local image (best-effort, errors are logged)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            runtime, "rmi", "-f", image_tag,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
    except Exception:
        pass
