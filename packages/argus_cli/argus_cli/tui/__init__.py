"""TUI subpackage - Textual-based terminal user interface."""

from argus_cli.tui.app import ArgusApp

__all__ = ["ArgusApp", "launch"]


def launch() -> None:
    """Convenience entry point for ``argus-tui`` console script."""
    ArgusApp().run()
