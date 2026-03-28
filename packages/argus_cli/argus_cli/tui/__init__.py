"""TUI subpackage - Textual-based terminal user interface."""

import argparse

from argus_cli.tui.app import ArgusApp

__all__ = ["ArgusApp", "launch"]


def launch() -> None:
    """Convenience entry point for ``argus-tui`` console script."""
    parser = argparse.ArgumentParser(
        prog="argus-tui",
        description="Argus MCP TUI dashboard",
    )
    parser.add_argument("--server", default=None, help="Server URL (e.g. http://127.0.0.1:9000)")
    parser.add_argument("--token", default=None, help="Authentication token")
    args = parser.parse_args()
    ArgusApp(server_url=args.server, token=args.token).run()
