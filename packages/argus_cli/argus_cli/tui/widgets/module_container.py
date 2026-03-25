"""Bordered container with title and keybind hints.

Wraps a section of the TUI in a rounded border with ``border_title``
(section name) and ``border_subtitle`` (keybind hint).  Gains an
accent border on focus, providing clear spatial orientation.
"""

from __future__ import annotations

from textual.containers import Vertical


class ModuleContainer(Vertical):
    """A bordered container with title/subtitle and focus highlighting.

    Parameters
    ----------
    title:
        Text shown at the top-left of the border (e.g. ``"Backends"``).
    subtitle:
        Text shown at the bottom-right of the border, typically a
        keybind hint (e.g. ``"[b]ackends"``).
    """

    DEFAULT_CSS = """\
    ModuleContainer {
        border: round $panel-lighten-2;
        padding: 0 1;
        height: auto;
    }

    ModuleContainer:focus-within {
        border: round $accent;
    }
    """

    def __init__(
        self,
        *children,
        title: str = "",
        subtitle: str = "",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(
            *children,
            name=name,
            id=id,
            classes=classes,
            disabled=disabled,
        )
        if title:
            self.border_title = title
        if subtitle:
            self.border_subtitle = subtitle
