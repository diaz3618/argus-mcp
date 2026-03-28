"""Categorized action toolbar for the TUI."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.widget import Widget
from textual.widgets import Label

if TYPE_CHECKING:
    from textual.app import ComposeResult


class _ToolbarAction(Label):
    """A single clickable action label inside the toolbar."""

    DEFAULT_CSS = """
    _ToolbarAction {
        padding: 0 1;
        color: $text;
    }
    _ToolbarAction:hover {
        background: $accent;
        color: $text;
        text-style: bold;
    }
    """

    def __init__(self, text: str, action: str, **kwargs: object) -> None:
        super().__init__(text, **kwargs)
        self._action_name = action

    async def on_click(self) -> None:
        """Dispatch the bound action on the app."""
        await self.app.run_action(self._action_name)


class _ToolbarSep(Label):
    """Visual separator between toolbar groups."""

    DEFAULT_CSS = """
    _ToolbarSep {
        color: $text-muted;
        padding: 0;
    }
    """

    def __init__(self) -> None:
        super().__init__(" │ ")


class ToolbarWidget(Widget):
    """Horizontal categorized toolbar docked to the top of the app.

    Groups:
    - **Server**: Quit, Details
    - **Navigate**: Tools, Resources, Prompts
    - **Appearance**: Themes, Next Theme
    """

    DEFAULT_CSS = """
    ToolbarWidget {
        dock: top;
        height: 1;
        width: 100%;
        background: $panel;
        layout: horizontal;
        padding: 0 1;
    }
    ToolbarWidget ._cat-label {
        color: $accent;
        text-style: bold;
        padding: 0 0 0 0;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label(" ", classes="_cat-label")
        yield _ToolbarAction("1·Dash", "switch_mode('dashboard')")
        yield _ToolbarAction("2·Tools", "switch_mode('tools')")
        yield _ToolbarAction("3·Reg", "switch_mode('registry')")
        yield _ToolbarAction("4·Set", "switch_mode('settings')")
        yield _ToolbarAction("5·Skills", "switch_mode('skills')")
        yield _ToolbarAction("6·Edit", "switch_mode('editor')")
        yield _ToolbarAction("7·Audit", "switch_mode('audit')")
        yield _ToolbarAction("8·Health", "switch_mode('health')")
        yield _ToolbarAction("9·Sec", "switch_mode('security')")
        yield _ToolbarAction("0·Ops", "switch_mode('operations')")
        yield _ToolbarAction("C·Containers", "switch_mode('containers')")
        yield _ToolbarAction("K·K8s", "switch_mode('kubernetes')")
        yield _ToolbarSep()
        yield _ToolbarAction("Details", "_tb_server_details")
        yield _ToolbarSep()
        yield _ToolbarAction("T", "show_tools")
        yield _ToolbarAction("R", "show_resources")
        yield _ToolbarAction("P", "show_prompts")
        yield _ToolbarSep()

        yield Label("Appearance: ", classes="_cat-label")
        yield _ToolbarAction("Themes", "open_theme_picker")
        yield _ToolbarAction("Next", "next_theme")
