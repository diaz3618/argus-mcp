"""Quick-action bar — horizontal strip of context-aware shortcuts.

Each screen defines a list of ``QuickAction`` tuples.  The bar renders
them as a compact row of ``[key] label`` items and dispatches key
presses to the corresponding callbacks.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Label

if TYPE_CHECKING:
    from textual.app import ComposeResult


@dataclass(frozen=True, slots=True)
class QuickAction:
    """A single quick-action entry."""

    key: str
    label: str
    callback: Callable[[], object]


class QuickActionBar(Widget):
    """Horizontal strip showing available quick actions for the active screen."""

    DEFAULT_CSS = """
    QuickActionBar {
        dock: bottom;
        height: 1;
        background: $surface;
        color: $text-muted;
        padding: 0 1;
    }

    QuickActionBar .qa-item {
        width: auto;
        margin-right: 2;
    }

    QuickActionBar .qa-key {
        color: $accent;
        text-style: bold;
    }
    """

    actions: reactive[list[QuickAction]] = reactive(list, init=False)

    def __init__(
        self,
        actions: list[QuickAction] | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self._actions: list[QuickAction] = list(actions) if actions else []

    def compose(self) -> ComposeResult:
        for qa in self._actions:
            yield Label(
                f"[b]{qa.key}[/b] {qa.label}",
                classes="qa-item",
                markup=True,
            )

    def set_actions(self, actions: list[QuickAction]) -> None:
        """Replace the current action list and re-compose."""
        self._actions = list(actions)
        self.remove_children()
        for qa in self._actions:
            self.mount(
                Label(
                    f"[b]{qa.key}[/b] {qa.label}",
                    classes="qa-item",
                    markup=True,
                )
            )

    def dispatch_key(self, key: str) -> bool:
        """Handle *key* if it matches a quick-action.

        Returns ``True`` if the key was consumed.
        """
        for qa in self._actions:
            if qa.key == key:
                qa.callback()
                return True
        return False
