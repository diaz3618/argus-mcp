"""Launcher script for Textual MCP headless testing of Argus TUI."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from argus_mcp.tui.app import ArgusApp
from argus_mcp.tui.server_manager import ServerManager

mgr = ServerManager.from_config()
if mgr.count == 0:
    mgr.add("default", "http://127.0.0.1:9000", None, set_active=True)


def app():
    return ArgusApp(
        server_url="http://127.0.0.1:9000",
        token=None,
        server_manager=mgr,
    )
