"""Shared constants and logger for the CLI package."""

from __future__ import annotations

import logging
import os

module_logger = logging.getLogger("argus_mcp.cli")

# Legacy PID file location (kept for backward-compat cleanup)
_PID_FILE = os.path.join(
    os.path.expanduser("~"),
    ".argus",
    "argus-mcp.pid",
)
