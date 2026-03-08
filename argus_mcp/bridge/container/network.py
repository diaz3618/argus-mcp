"""Container network policy configuration.

Defines network modes for containerised MCP backends and provides
helpers to build ``docker run`` network flags.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from argus_mcp.bridge.container.runtime import ContainerRuntime

logger = logging.getLogger(__name__)

# ── Network modes ────────────────────────────────────────────────────────
#
# "bridge" — default Docker bridge network.  Allows general outbound
#            (HTTP, DNS, etc.).  Suitable for most MCP servers.
# "none"   — no network at all.  Only for servers that do NOT need any
#            network access (e.g. local filesystem tools, sequential-
#            thinking).
# "host"   — host network stack.  Only for special cases requiring
#            direct host networking (discouraged for isolation).
# "<name>" — a named Docker network (created externally).

DEFAULT_NETWORK = "bridge"  # safe default — most MCP servers need net

# Dedicated Argus network for container-to-container communication.
# Created lazily the first time a backend uses it.
ARGUS_NETWORK = "argus-mcp"


def effective_network(configured: Optional[str]) -> str:
    """Return the effective network mode.

    If *configured* is ``None`` or empty, returns the default (bridge).
    """
    if configured and configured.strip():
        return configured.strip()
    return DEFAULT_NETWORK


def build_network_args(network: str) -> List[str]:
    """Build ``docker run`` flags for the given network mode.

    Returns a list like ``["--network", "bridge"]`` or
    ``["--network", "none"]``.
    """
    return ["--network", network]


async def ensure_managed_network(
    runtime: "ContainerRuntime",
    network_name: str = ARGUS_NETWORK,
) -> bool:
    """Create the managed Argus network if it doesn't already exist.

    Returns ``True`` if the network is ready (already existed or
    was created successfully), ``False`` on failure.
    """
    try:
        return await runtime.create_network(network_name)
    except Exception:
        logger.warning(
            "Failed to create managed network '%s'.",
            network_name,
            exc_info=True,
        )
        return False
