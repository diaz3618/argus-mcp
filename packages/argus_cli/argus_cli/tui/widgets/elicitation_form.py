"""Elicitation form widget — renders JSON Schema forms in TUI.

Converts a JSON Schema (from an :class:`ElicitationRequest`) into
Textual input widgets: Input, Switch, Select.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Button, Input, Label, Select, Static, Switch

if TYPE_CHECKING:
    from argus_mcp.bridge.elicitation import ElicitationRequest
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class ElicitationFormWidget(Static):
    """Renders an elicitation form from a JSON Schema.

    Posts :class:`FormSubmitted` when the user clicks Submit,
    and :class:`FormCancelled` on Cancel.
    """

    class FormSubmitted(Message):
        """Posted with the collected form data."""

        def __init__(self, request_id: str, data: dict[str, Any]) -> None:
            super().__init__()
            self.request_id = request_id
            self.data = data

    class FormCancelled(Message):
        """Posted when the user cancels the form."""

        def __init__(self, request_id: str) -> None:
            super().__init__()
            self.request_id = request_id

    def __init__(
        self,
        request: ElicitationRequest,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._request = request
        self._fields = request.fields

    def compose(self) -> ComposeResult:
        with Vertical():
            # Header
            yield Label(f"[b]{self._request.tool_name}[/b]", id="elicit-title")
            if self._request.message:
                yield Label(self._request.message, id="elicit-message")

            # Form fields
            for field_def in self._fields:
                yield Label(
                    f"{'* ' if field_def.required else ''}{field_def.name}",
                    classes="field-label",
                )
                if field_def.description:
                    yield Label(field_def.description, classes="field-desc")

                if field_def.field_type == "boolean":
                    yield Switch(
                        value=bool(field_def.default) if field_def.default else False,
                        id=f"field-{field_def.name}",
                    )
                elif field_def.enum_values:
                    options = [(v, v) for v in field_def.enum_values]
                    yield Select(
                        options,
                        value=field_def.default if field_def.default else Select.BLANK,
                        id=f"field-{field_def.name}",
                    )
                elif field_def.field_type in ("integer", "number"):
                    yield Input(
                        value=str(field_def.default) if field_def.default is not None else "",
                        placeholder=f"Enter {field_def.name} ({field_def.field_type})",
                        type="number",
                        id=f"field-{field_def.name}",
                    )
                else:
                    yield Input(
                        value=str(field_def.default) if field_def.default is not None else "",
                        placeholder=f"Enter {field_def.name}",
                        id=f"field-{field_def.name}",
                    )

            # Action buttons
            with Vertical(id="elicit-actions"):
                yield Button("Submit", variant="primary", id="elicit-submit")
                yield Button("Cancel", variant="error", id="elicit-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "elicit-submit":
            data = self._collect_data()
            self.post_message(self.FormSubmitted(self._request.request_id, data))
        elif event.button.id == "elicit-cancel":
            self.post_message(self.FormCancelled(self._request.request_id))

    def _collect_data(self) -> dict[str, Any]:
        """Collect values from all form fields."""
        data: dict[str, Any] = {}
        for field_def in self._fields:
            widget = self.query_one(f"#field-{field_def.name}")
            if isinstance(widget, Switch):
                data[field_def.name] = widget.value
            elif isinstance(widget, Select):
                data[field_def.name] = widget.value if widget.value != Select.BLANK else None
            elif isinstance(widget, Input):
                raw = widget.value
                if field_def.field_type == "integer":
                    try:
                        data[field_def.name] = int(raw) if raw else None
                    except ValueError:
                        data[field_def.name] = None
                elif field_def.field_type == "number":
                    try:
                        data[field_def.name] = float(raw) if raw else None
                    except ValueError:
                        data[field_def.name] = None
                else:
                    data[field_def.name] = raw
            else:
                data[field_def.name] = None
        return data
