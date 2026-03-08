"""Base screen with shared chrome for all Argus MCP modes."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Footer, Header

from argus_mcp.tui.widgets.toolbar import ToolbarWidget


class ArgusScreen(Screen):
    """Base screen providing shared chrome (Header, Toolbar, Footer).

    Subclasses override :meth:`compose_content` to supply mode-specific
    widgets.  The chrome is rendered automatically.
    """

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ToolbarWidget()
        yield from self.compose_content()
        yield Footer()

    def compose_content(self) -> ComposeResult:
        """Override in subclasses to add mode-specific content."""
        yield from ()
