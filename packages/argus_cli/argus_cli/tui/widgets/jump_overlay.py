"""Jump-mode overlay for quick spatial navigation.

Press the jump hotkey to display single-letter labels at each focusable
panel/widget position.  Pressing a letter instantly focuses that section.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple, Protocol, runtime_checkable

from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Label

if TYPE_CHECKING:
    from collections.abc import Mapping

    from textual.geometry import Offset
    from textual.screen import Screen


# Protocol


@runtime_checkable
class Jumpable(Protocol):
    """A widget that declares itself as a jump target."""

    jump_key: str


# Data types


class JumpInfo(NamedTuple):
    """Information about a single jump target."""

    key: str
    """The key which should trigger the jump."""

    widget: str | Widget
    """Either the widget ID or a direct widget reference."""


# Jumper engine


class Jumper:
    """Walk the screen's widget tree and collect jump targets."""

    def __init__(
        self,
        ids_to_keys: Mapping[str, str],
        screen: Screen[Any],
    ) -> None:
        self.ids_to_keys = ids_to_keys
        self.keys_to_ids = {v: k for k, v in ids_to_keys.items()}
        self.screen = screen

    def get_overlays(self) -> dict[Offset, JumpInfo]:
        """Return jump-target positions mapped to their label info."""
        from textual.errors import NoWidget

        screen = self.screen
        children: list[Widget] = screen.walk_children(Widget)
        overlays: dict[Offset, JumpInfo] = {}

        for child in children:
            try:
                widget_offset = screen.get_offset(child)
            except NoWidget:
                continue

            if child.id and child.id in self.ids_to_keys:
                overlays[widget_offset] = JumpInfo(
                    self.ids_to_keys[child.id],
                    child.id,
                )
            elif isinstance(child, Jumpable):
                overlays[widget_offset] = JumpInfo(
                    child.jump_key,
                    child,
                )

        return overlays


# Overlay modal


class JumpOverlay(ModalScreen[str | Widget | None]):
    """Modal overlay showing single-letter jump labels.

    Dismissed with the widget ID (or widget reference) when a jump key
    is pressed, or ``None`` when the user presses Escape.
    """

    DEFAULT_CSS = """\
    JumpOverlay {
        background: $background 50%;
    }

    .textual-jump-label {
        layer: textual-jump;
        dock: top;
        text-style: bold;
        color: $text;
        background: $accent;
        border: round $accent;
        padding: 0 1;
    }

    #textual-jump-info {
        dock: bottom;
        height: 1;
        background: $accent;
        color: $text;
        text-align: center;
    }

    #textual-jump-dismiss {
        dock: bottom;
        height: 1;
        background: $panel;
        color: $text-muted;
        text-align: center;
    }
    """

    BINDINGS = [
        Binding("escape", "dismiss_overlay", "Dismiss", show=False),
    ]

    def __init__(
        self,
        jumper: Jumper,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.jumper = jumper
        self.keys_to_widgets: dict[str, Widget | str] = {}

    def on_key(self, key_event: events.Key) -> None:
        """Intercept key presses — jump to target or ignore."""
        # Prevent Tab/Shift+Tab from leaking through the overlay.
        if key_event.key in ("tab", "shift+tab"):
            key_event.stop()
            key_event.prevent_default()
            return

        if self.is_active:
            target = self.keys_to_widgets.get(key_event.key)
            if target is not None:
                self.dismiss(target)

    def action_dismiss_overlay(self) -> None:
        self.dismiss(None)

    def _sync(self) -> None:
        self.overlays = self.jumper.get_overlays()
        self.keys_to_widgets = {v.key: v.widget for v in self.overlays.values()}

    def compose(self) -> ComposeResult:
        self._sync()
        for offset, jump_info in self.overlays.items():
            key, _widget = jump_info
            label = Label(f" {key.upper()} ", classes="textual-jump-label")
            label.styles.offset = offset
            yield label
        with Center(id="textual-jump-info"):
            yield Label("Press a key to jump")
        with Center(id="textual-jump-dismiss"):
            yield Label("[b]ESC[/] to dismiss")
