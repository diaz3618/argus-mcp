"""Reusable inline filter bar — Input + Switch for toggling filter on/off.

Supports operator-aware filtering for numeric fields:
  ``>=100``, ``<50ms``, ``>200``, ``<=10``

The switch allows disabling the filter without clearing the input text.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Input, Label, Switch

if TYPE_CHECKING:
    from textual.app import ComposeResult

# Regex for operator-prefixed numeric values: >=100, <50ms, >200, <=10, =5
_OP_RE = re.compile(r"^([><=!]+)\s*(\d+(?:\.\d+)?)\s*\w*$")


class FilterBar(Widget):
    """Inline filter bar with text input and enable/disable switch.

    Posts :class:`FilterChanged` whenever the effective filter state changes
    (input text changed while enabled, or switch toggled).
    """

    DEFAULT_CSS = """
    FilterBar {
        height: 3;
        layout: horizontal;
        padding: 0 1;
        background: $surface;
    }
    FilterBar .filter-label {
        width: auto;
        padding: 1 1 0 0;
        color: $text-muted;
    }
    FilterBar .filter-input {
        width: 1fr;
    }
    FilterBar .filter-switch-label {
        width: auto;
        padding: 1 1 0 1;
        color: $text-muted;
    }
    FilterBar Switch {
        width: auto;
    }
    """

    class FilterChanged(Message):
        """Posted when filter state changes (text or enabled toggle)."""

        def __init__(
            self,
            query: str,
            enabled: bool,
            filter_bar: FilterBar,
        ) -> None:
            super().__init__()
            self.query = query
            self.enabled = enabled
            self.filter_bar = filter_bar

    enabled: reactive[bool] = reactive(True)

    def __init__(
        self,
        *,
        placeholder: str = "Filter…",
        label: str = "Filter:",
        initial_enabled: bool = True,
        input_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._placeholder = placeholder
        self._label = label
        self._input_id = input_id or "filter-input"
        self.enabled = initial_enabled

    def compose(self) -> ComposeResult:
        yield Label(self._label, classes="filter-label")
        yield Input(
            placeholder=self._placeholder,
            id=self._input_id,
            classes="filter-input",
        )
        yield Label("Active", classes="filter-switch-label")
        yield Switch(value=self.enabled, id=f"{self._input_id}-switch")

    @property
    def query_text(self) -> str:
        """Return current filter text."""
        try:
            return self.query_one(f"#{self._input_id}", Input).value.strip()
        except Exception:
            return ""

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == self._input_id:
            self._post_change()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id == f"{self._input_id}-switch":
            self.enabled = event.value
            self._post_change()

    def _post_change(self) -> None:
        self.post_message(
            self.FilterChanged(
                query=self.query_text,
                enabled=self.enabled,
                filter_bar=self,
            )
        )

    def focus_input(self) -> None:
        """Focus the filter input."""
        try:
            self.query_one(f"#{self._input_id}", Input).focus()
        except Exception:
            pass

    def clear(self) -> None:
        """Clear the filter text (and post a change)."""
        try:
            self.query_one(f"#{self._input_id}", Input).value = ""
        except Exception:
            pass

    @staticmethod
    def matches_text(value: str, query: str) -> bool:
        """Check if *value* contains *query* (case-insensitive)."""
        return query.lower() in value.lower()

    @staticmethod
    def matches_numeric(value: float | int | None, query: str) -> bool:
        """Check if *value* satisfies an operator-aware numeric query.

        Examples: ``>=100``, ``<50``, ``>200ms``, ``<=10``, ``=5``
        If the query has no operator prefix, does a substring match on ``str(value)``.
        """
        if value is None:
            return False
        m = _OP_RE.match(query.strip())
        if not m:
            # Plain text — substring match on stringified value
            return query.lower() in str(value).lower()
        op, num_str = m.group(1), float(m.group(2))
        if op == ">=":
            return value >= num_str
        if op == "<=":
            return value <= num_str
        if op == ">":
            return value > num_str
        if op == "<":
            return value < num_str
        if op in ("=", "=="):
            return value == num_str
        if op in ("!=", "!"):
            return value != num_str
        return True

    @staticmethod
    def parse_numeric(text: str) -> float | None:
        """Extract a number from text like '42', '3.14ms', '100ms'."""
        m = re.search(r"(\d+(?:\.\d+)?)", text)
        return float(m.group(1)) if m else None
