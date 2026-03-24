"""Base screen with shared chrome for all Argus MCP modes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.screen import Screen
from textual.widgets import Footer, Header

from argus_cli.tui._error_utils import safe_query
from argus_cli.tui.widgets.toolbar import ToolbarWidget

if TYPE_CHECKING:
    from textual.app import ComposeResult


class ArgusScreen(Screen):
    """Base screen providing shared chrome (Header, Toolbar, Footer).

    Subclasses override :meth:`compose_content` to supply mode-specific
    widgets.  The chrome is rendered automatically.

    Subclasses that want a non-Input widget to receive initial focus
    should set ``INITIAL_FOCUS`` to a CSS selector string.
    """

    INITIAL_FOCUS: str | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ToolbarWidget()
        yield from self.compose_content()
        yield Footer()

    def compose_content(self) -> ComposeResult:
        """Override in subclasses to add mode-specific content."""
        yield from ()

    def on_screen_resume(self) -> None:
        """Focus the widget specified by INITIAL_FOCUS after the screen
        is fully displayed.  This runs *after* Textual's built-in
        auto-focus and avoids the bug where AUTO_FOCUS is not picked up.
        """
        selector = self.INITIAL_FOCUS
        if selector is not None:
            self.call_after_refresh(self._apply_initial_focus)

    def _apply_initial_focus(self) -> None:
        """Deferred focus to INITIAL_FOCUS widget."""
        selector = self.INITIAL_FOCUS
        if selector is None:
            return
        widget = safe_query(self, selector)
        if widget is not None:
            widget.focus()
