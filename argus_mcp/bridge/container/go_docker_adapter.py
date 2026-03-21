"""Go Docker adapter integration.

Provides a Python wrapper around the ``docker-adapter`` Go binary for
high-performance Docker operations using the native Engine API instead
of spawning CLI subprocesses.

Falls back to the standard :class:`~argus_mcp.bridge.container.runtime.DockerRuntime`
CLI-based implementation when the Go binary is not available.

The Go binary achieves 5-10x faster operations through connection pooling
and the Docker Engine API (no ``docker`` CLI fork per call).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from argus_mcp.constants import STACK_CLOSE_TIMEOUT

logger = logging.getLogger(__name__)

# Cached binary path (resolved once).
_go_binary: Optional[str] = None
_binary_checked: bool = False


def _find_go_binary() -> Optional[str]:
    """Locate the docker-adapter binary.

    Search order:
    1. ``ARGUS_DOCKER_ADAPTER`` environment variable
    2. ``tools/docker-adapter/docker-adapter`` relative to project root
    3. System PATH
    """
    global _go_binary, _binary_checked  # noqa: PLW0603
    if _binary_checked:
        return _go_binary

    _binary_checked = True

    # 1. Explicit env var (sanitise to prevent path traversal).
    env_path = os.environ.get("ARGUS_DOCKER_ADAPTER")
    if env_path:
        env_path = os.path.realpath(env_path)  # noqa: PTH118 – resolve symlinks/traversal
    if env_path and os.path.isfile(env_path) and os.access(env_path, os.X_OK):
        _go_binary = env_path
        logger.info("Using Go docker adapter from ARGUS_DOCKER_ADAPTER: %s", _go_binary)
        return _go_binary

    # 2. Relative to project root.
    project_root = Path(__file__).resolve().parents[3]
    for name in ("docker-adapter", "docker-adapter.exe"):
        candidate = project_root / "tools" / "docker-adapter" / name
        if candidate.is_file() and os.access(str(candidate), os.X_OK):
            _go_binary = str(candidate)
            logger.info("Using Go docker adapter from project: %s", _go_binary)
            return _go_binary

    # 3. System PATH.
    found = shutil.which("docker-adapter")
    if found:
        _go_binary = found
        logger.info("Using Go docker adapter from PATH: %s", _go_binary)
        return _go_binary

    logger.debug("Go docker adapter not found; using Python fallback")
    return None


def is_available() -> bool:
    """Return True if the Go docker adapter binary is available."""
    return _find_go_binary() is not None


class GoDockerAdapter:
    """Async wrapper for the Go docker-adapter binary.

    Communicates via JSON-over-stdio: one JSON request per line on stdin,
    one JSON response per line on stdout.
    """

    def __init__(self) -> None:
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the Go adapter subprocess."""
        binary = _find_go_binary()
        if binary is None:
            raise RuntimeError("Go docker-adapter binary not found")

        self._proc = await asyncio.create_subprocess_exec(
            binary,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        logger.info("Go docker adapter started (pid=%d)", self._proc.pid)

    async def stop(self) -> None:
        """Stop the Go adapter subprocess."""
        if self._proc and self._proc.returncode is None:
            self._proc.stdin.close()  # type: ignore[union-attr]
            try:
                await asyncio.wait_for(self._proc.wait(), timeout=STACK_CLOSE_TIMEOUT)
            except asyncio.TimeoutError:
                self._proc.kill()
                await self._proc.wait()
            logger.info("Go docker adapter stopped")

    async def _call(self, op: str, args: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Send a request and read the response."""
        if self._proc is None or self._proc.returncode is not None:
            raise RuntimeError("Go docker adapter not running")

        req = json.dumps({"op": op, "args": args or {}}) + "\n"

        async with self._lock:
            self._proc.stdin.write(req.encode())  # type: ignore[union-attr]
            await self._proc.stdin.drain()  # type: ignore[union-attr]

            line = await self._proc.stdout.readline()  # type: ignore[union-attr]
            if not line:
                raise RuntimeError("Go docker adapter closed stdout")

            return json.loads(line)

    async def health(self) -> bool:
        """Check Docker daemon connectivity."""
        resp = await self._call("health")
        return resp.get("ok", False)

    async def image_exists(self, image: str) -> bool:
        """Check if an image exists locally."""
        resp = await self._call("image-exists", {"image": image})
        if not resp.get("ok"):
            return False
        return bool(resp.get("data", False))

    async def pull(self, image: str) -> bool:
        """Pull an image from a registry."""
        resp = await self._call("pull", {"image": image})
        return resp.get("ok", False)

    async def remove_image(self, image: str) -> bool:
        """Remove a local image."""
        resp = await self._call("remove-image", {"image": image})
        return resp.get("ok", False)

    async def create_network(self, name: str, *, internal: bool = False) -> bool:
        """Create a Docker network."""
        resp = await self._call(
            "create-network",
            {
                "name": name,
                "internal": str(internal).lower(),
            },
        )
        return resp.get("ok", False)

    async def remove_network(self, name: str) -> bool:
        """Remove a Docker network."""
        resp = await self._call("remove-network", {"name": name})
        return resp.get("ok", False)

    async def list_images(self, prefix: str = "") -> List[str]:
        """List images matching an optional prefix."""
        resp = await self._call("list-images", {"prefix": prefix})
        if not resp.get("ok"):
            return []
        return resp.get("data", []) or []

    async def build(
        self,
        dockerfile_content: str,
        image_tag: str,
        build_args: Optional[Dict[str, str]] = None,
    ) -> bool:
        """Build an image from a Dockerfile string."""
        args: Dict[str, str] = {
            "dockerfile_content": dockerfile_content,
            "image_tag": image_tag,
        }
        if build_args:
            args["build_args"] = json.dumps(build_args)
        resp = await self._call("build", args)
        return resp.get("ok", False)

    async def create(
        self,
        image: str,
        name: str,
        *,
        cmd: Optional[List[str]] = None,
        entrypoint: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        network: Optional[str] = None,
        memory: int = 0,
        cpus: float = 0.0,
        volumes: Optional[List[str]] = None,
        read_only: bool = False,
        cap_drop: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Create a container and return its ID (or None on failure)."""
        args: Dict[str, str] = {"image": image, "name": name}
        if cmd:
            args["cmd"] = json.dumps(cmd)
        if entrypoint:
            args["entrypoint"] = json.dumps(entrypoint)
        if env:
            args["env"] = json.dumps(env)
        if network:
            args["network"] = network
        if memory:
            args["memory"] = str(memory)
        if cpus:
            args["cpus"] = str(cpus)
        if volumes:
            args["volumes"] = json.dumps(volumes)
        if read_only:
            args["read_only"] = "true"
        if cap_drop:
            args["cap_drop"] = json.dumps(cap_drop)
        resp = await self._call("create", args)
        if not resp.get("ok"):
            logger.error("Go adapter create failed: %s", resp.get("error", "unknown"))
            return None
        data = resp.get("data", {})
        return data.get("container_id") if isinstance(data, dict) else None
