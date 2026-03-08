"""Container isolation for MCP backend servers.

This package provides automatic, per-server container isolation for
stdio-based MCP backends. The approach mirrors production container
managers: custom OCI images are **built once** (with the MCP package
pre-installed via multi-stage Dockerfiles) and then run repeatedly
without needing to reinstall on every startup.

Architecture
------------
1. **Runtime detection** — discovers Docker or Podman on ``$PATH``
   via the :class:`RuntimeFactory`.
2. **Command parsing** — extracts the package name and runtime args
   from the backend's ``command`` + ``args``.
3. **Image building** — generates a Dockerfile from a template for the
   detected transport type (``uvx``, ``npx``, etc.), builds the image,
   and caches it locally.
4. **Command wrapping** — rewrites the ``StdioServerParameters`` so the
   MCP SDK spawns the container instead of the bare command.

The public entry point is :func:`wrap_backend` which replaces the old
``auto_wrap_stdio``.

Supported server types
~~~~~~~~~~~~~~~~~~~~~~
- **uvx / uv / pip / pipx** — Python packages via ``uv tool install``
- **npx / node / tsx** — Node.js packages via ``npm install``
- **docker** — already containerised; passed through unchanged
- **Remote (SSE / streamable-http)** — no container, transparent proxy

Network policy
~~~~~~~~~~~~~~
Servers that need internet access (most of them) run with
``--network bridge``.  Only explicitly offline-capable tools get
``--network none``.  Fine-grained egress control can be added via
an optional ``network`` section in the backend config.
"""

from argus_mcp.bridge.container.runtime import (
    ContainerRuntime,
    DockerRuntime,
    RuntimeFactory,
    RuntimeType,
)
from argus_mcp.bridge.container.wrapper import (
    cleanup_all_containers,
    cleanup_container,
    container_cleanup_context,
    wrap_backend,
)

__all__ = [
    "ContainerRuntime",
    "DockerRuntime",
    "RuntimeFactory",
    "RuntimeType",
    "cleanup_all_containers",
    "cleanup_container",
    "container_cleanup_context",
    "wrap_backend",
]


def _reset_health_cache() -> None:
    """Reset the cached runtime health check result (for testing)."""
    RuntimeFactory.get().reset()
