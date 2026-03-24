"""Theme picker modal screen."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

if TYPE_CHECKING:
    from textual.app import ComposeResult


class ThemeScreen(ModalScreen[str | None]):
    """Modal screen for selecting a TUI theme.

    Displays all available Textual themes in an ``OptionList``.
    Selecting a theme applies it immediately and persists the choice.
    Press ``Escape`` to cancel without changes.
    """

    DEFAULT_CSS = """
    ThemeScreen {
        align: center middle;
    }

    ThemeScreen #theme-dialog {
        width: 50;
        max-width: 80%;
        height: auto;
        max-height: 80%;
        border: tall $accent;
        background: $surface;
        padding: 1 2;
    }

    ThemeScreen #theme-title {
        text-align: center;
        text-style: bold;
        color: $text;
        margin-bottom: 1;
        width: 100%;
    }

    ThemeScreen #theme-hint {
        text-align: center;
        color: $text-muted;
        margin-top: 1;
        width: 100%;
    }

    ThemeScreen OptionList {
        height: auto;
        max-height: 20;
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._original_theme: str = ""

    def compose(self) -> ComposeResult:
        available = sorted(self.app.available_themes)
        current = self.app.theme or "textual-dark"
        self._original_theme = current

        options = [
            Option(
                f"  {'●' if name == current else '○'}  {name}",
                id=name,
            )
            for name in available
        ]

        with Vertical(id="theme-dialog"):
            yield Label("🎨  Select Theme", id="theme-title")
            ol = OptionList(*options, id="theme-list")
            yield ol
            yield Label("[dim]↑↓ Navigate  ·  Enter Select  ·  Esc Cancel[/dim]", id="theme-hint")

    def on_mount(self) -> None:
        """Highlight the current theme on mount."""
        ol = self.query_one("#theme-list", OptionList)
        current = self._original_theme
        try:
            idx = ol.get_option_index(current)
            ol.highlighted = idx
        except OptionList.OptionDoesNotExist:
            pass

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        """Live-preview themes as the user navigates."""
        if event.option.id and event.option.id in self.app.available_themes:
            self.app.theme = event.option.id

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Apply the selected theme and dismiss."""
        theme_name = event.option.id
        if theme_name and theme_name in self.app.available_themes:
            self.app.theme = theme_name
            self.dismiss(theme_name)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        """Restore original theme and dismiss."""
        self.app.theme = self._original_theme
        self.dismiss(None)
