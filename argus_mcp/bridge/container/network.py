"""Container network policy configuration.

Defines network modes for containerised MCP backends and provides
helpers to build ``docker run`` network flags.
"""

from __future__ import annotations

import logging
from typing import List, Optional

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
