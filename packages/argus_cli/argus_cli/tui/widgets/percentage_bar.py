"""Percentage bar — visual ratio indicator with color segments.

Renders a compact horizontal bar where a filled portion represents a
percentage (0-100).  Colors adapt to the active Textual theme through
``$success``, ``$warning``, and ``$error`` design tokens.
"""

from __future__ import annotations

from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label


class PercentageBar(Widget):
    """A horizontal bar showing a filled portion proportional to *value*.

    The bar automatically picks a colour based on the value:
    - >= 80 %  → success (green)
    - >= 50 %  → warning (yellow)
    - <  50 %  → error (red)
    """

    DEFAULT_CSS = """
    PercentageBar {
        height: 1;
        width: 1fr;
        layout: horizontal;
    }

    PercentageBar .pbar-label {
        width: auto;
        min-width: 6;
        text-align: right;
        margin-right: 1;
        color: $text-muted;
    }

    PercentageBar .pbar-track {
        width: 1fr;
        height: 1;
    }
    """

    value: reactive[float] = reactive(0.0)
    label_text: reactive[str] = reactive("")

    def __init__(
        self,
        value: float = 0.0,
        label: str = "",
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        # _bar must exist before setting reactive `value` because
        # Textual fires watch_value() immediately on assignment.
        self._bar = _BarTrack()
        self.value = max(0.0, min(100.0, value))
        self.label_text = label

    def compose(self):
        yield Label(self.label_text, classes="pbar-label")
        yield self._bar

    def watch_value(self, new_value: float) -> None:
        self._bar.percentage = max(0.0, min(100.0, new_value))

    def watch_label_text(self, new_label: str) -> None:
        try:
            lbl = self.query_one(".pbar-label", Label)
            lbl.update(new_label)
        except Exception:
            pass


class _BarTrack(Widget):
    """Inner widget that renders the actual bar."""

    DEFAULT_CSS = """
    _BarTrack {
        height: 1;
        width: 1fr;
    }
    """

    percentage: reactive[float] = reactive(0.0)

    def render(self):
        width = self.size.width
        if width <= 0:
            return ""
        filled = round(width * self.percentage / 100.0)
        empty = width - filled

        if self.percentage >= 80.0:
            style = "green"
        elif self.percentage >= 50.0:
            style = "yellow"
        else:
            style = "red"

        from rich.text import Text

        bar = Text()
        bar.append("\u2588" * filled, style=style)
        bar.append("\u2591" * empty, style="dim")
        return bar

    def watch_percentage(self) -> None:
        self.refresh()
