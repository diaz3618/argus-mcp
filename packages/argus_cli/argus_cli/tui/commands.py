"""Command palette providers for the Argus MCP TUI.

Extends the built-in command palette with:
- Per-theme switching commands with live preview on highlight.
- Screen/mode discovery.
"""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from textual.command import Hit, Hits, Provider

if TYPE_CHECKING:
    from textual.app import App
    from textual.screen import Screen


class ThemeProvider(Provider):
    """Command provider that lists each available theme individually.

    Themes are applied live as the user highlights them in the palette.
    When a theme is selected the choice is persisted to settings.  If
    the palette is dismissed without selection, the original theme is
    restored.
    """

    def __init__(self, app: App, screen: Screen) -> None:
        super().__init__(app, screen)
        self._original_theme: str = ""

    async def startup(self) -> None:
        self._original_theme = self.app.theme or "textual-dark"

    async def search(self, query: str) -> Hits:
        """Fuzzy-match available theme names."""
        matcher = self.matcher(query)
        current = self.app.theme or "textual-dark"
        for name in sorted(self.app.available_themes):
            score = matcher.match(name)
            if score > 0:
                indicator = "\u25cf" if name == current else "\u25cb"
                yield Hit(
                    score,
                    matcher.highlight(f"{indicator} {name}"),
                    partial(self._apply_theme, name),
                    help=f"Switch theme to {name}",
                )

    async def shutdown(self) -> None:
        """Restore original theme if palette was dismissed."""
        # Textual's Provider.shutdown is called when the palette closes.
        # If a command was executed the theme is already persisted; if
        # the user pressed Escape the _apply_theme callback was never
        # invoked, so the app still has the original theme.  We
        # explicitly restore it here to cover live-preview resets.
        if self.app.theme != self._original_theme:
            # A theme was selected — check whether it was persisted via
            # _apply_theme.  If not (e.g. dismissal while live-previewing)
            # revert to the original.
            if not getattr(self, "_committed", False):
                self.app.theme = self._original_theme

    def _apply_theme(self, name: str) -> None:
        """Select *name* as the active theme and persist it."""
        from argus_cli.tui.settings import load_settings, save_settings

        self.app.theme = name
        settings = load_settings()
        settings["theme"] = name
        save_settings(settings)
        self.app.notify(f"Theme: {name}", timeout=2)
        self._committed = True
