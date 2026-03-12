"""Go MCP stdio wrapper integration.

Provides a Python wrapper around the ``mcp-stdio-wrapper`` Go binary
for high-performance subprocess management.  Falls back to the pure-Python
:func:`~argus_mcp.bridge.subprocess_utils.manage_subproc` when the Go
binary is not available.

The Go binary achieves 3-5× throughput via 256 KB buffered I/O and
goroutine-based concurrent stream processing.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional

logger = logging.getLogger(__name__)

# Cached binary path (resolved once).
_go_binary: Optional[str] = None
_binary_checked: bool = False


def _find_go_binary() -> Optional[str]:
    """Locate the mcp-stdio-wrapper binary.

    Search order:
    1. ``ARGUS_STDIO_WRAPPER`` environment variable
    2. ``tools/mcp-stdio-wrapper/mcp-stdio-wrapper`` relative to project root
    3. System PATH
    """
    global _go_binary, _binary_checked  # noqa: PLW0603
    if _binary_checked:
        return _go_binary

    _binary_checked = True

    # 1. Explicit env var (sanitise to prevent path traversal).
    env_path = os.environ.get("ARGUS_STDIO_WRAPPER")
    if env_path:
        env_path = os.path.realpath(env_path)  # noqa: PTH118 – resolve symlinks/traversal
    if env_path and os.path.isfile(env_path) and os.access(env_path, os.X_OK):
        _go_binary = env_path
        logger.info("Using Go stdio wrapper from ARGUS_STDIO_WRAPPER: %s", _go_binary)
        return _go_binary

    # 2. Relative to project root.
    project_root = Path(__file__).resolve().parents[2]
    for name in ("mcp-stdio-wrapper", "mcp-stdio-wrapper.exe"):
        candidate = project_root / "tools" / "mcp-stdio-wrapper" / name
        if candidate.is_file() and os.access(str(candidate), os.X_OK):
            _go_binary = str(candidate)
            logger.info("Using Go stdio wrapper from project: %s", _go_binary)
            return _go_binary

    # 3. System PATH.
    found = shutil.which("mcp-stdio-wrapper")
    if found:
        _go_binary = found
        logger.info("Using Go stdio wrapper from PATH: %s", _go_binary)
        return _go_binary

    logger.debug("Go stdio wrapper not found; using Python fallback")
    return None


def is_available() -> bool:
    """Return True if the Go stdio wrapper binary is available."""
    return _find_go_binary() is not None


@asynccontextmanager
async def manage_subproc_go(
    server_name: str,
    command: List[str],
    env: Optional[Dict[str, str]] = None,
    *,
    kill_timeout: float = 3.0,
    buf_size: int = 256 * 1024,
) -> AsyncGenerator[asyncio.subprocess.Process, None]:
    """Spawn an MCP backend via the Go stdio wrapper.

    If the Go binary is not available, this falls back to the standard
    :func:`~argus_mcp.bridge.subprocess_utils.manage_subproc`.

    Parameters
    ----------
    server_name:
        Human-readable name for logging.
    command:
        The MCP backend command and arguments.
    env:
        Environment variables for the child process.
    kill_timeout:
        Seconds to wait after SIGTERM before SIGKILL.
    buf_size:
        I/O buffer size in bytes.
    """
    binary = _find_go_binary()
    if binary is None:
        # Fallback to pure-Python implementation.
        from argus_mcp.bridge.subprocess_utils import manage_subproc

        async with manage_subproc(server_name, command, env) as proc:
            yield proc
        return

    # Build the Go wrapper command.
    wrapper_cmd = [
        binary,
        "--kill-timeout",
        f"{kill_timeout}s",
        "--log-prefix",
        server_name,
        "--buf-size",
        str(buf_size),
        "--",
    ] + command

    merged_env = {**os.environ, **(env or {})}

    proc = await asyncio.create_subprocess_exec(
        *wrapper_cmd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=merged_env,
    )

    logger.info(
        "[%s] Started via Go stdio wrapper (PID %d): %s",
        server_name,
        proc.pid,
        " ".join(command),
    )

    try:
        yield proc
    finally:
        if proc.returncode is None:
            try:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=kill_timeout)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
            except ProcessLookupError:
                pass
            logger.info("[%s] Go stdio wrapper stopped (PID %d)", server_name, proc.pid)
