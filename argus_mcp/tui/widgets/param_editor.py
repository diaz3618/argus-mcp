"""Parameter default editor widget — edit tool parameter defaults.

Renders input fields for each parameter in a tool's input schema,
allowing the user to set default values that will be applied
automatically when the tool is invoked.
"""

from __future__ import annotations

from typing import Any, Dict

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.widgets import Input, Label, Static, Switch


class ParamEditorWidget(Static):
    """Editor for tool parameter defaults.

    Reads the tool's ``inputSchema`` and creates input fields for each
    property.

    Posts :class:`DefaultsChanged` when values are modified.
    """

    class DefaultsChanged(Message):
        """Posted when a parameter default value changes."""

        def __init__(self, tool_name: str, defaults: Dict[str, Any]) -> None:
            super().__init__()
            self.tool_name = tool_name
            self.defaults = defaults

    def __init__(
        self,
        tool_name: str = "",
        input_schema: Dict[str, Any] | None = None,
        current_defaults: Dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._tool_name = tool_name
        self._schema = input_schema or {}
        self._defaults = current_defaults or {}

    def compose(self) -> ComposeResult:
        properties = self._schema.get("properties", {})
        if not properties:
            yield Label("[dim]No parameters to edit[/]")
            return

        with Vertical():
            yield Label(f"[b]Defaults for {self._tool_name}[/b]")
            for name, prop in properties.items():
                ptype = prop.get("type", "string")
                desc = prop.get("description", "")
                current = self._defaults.get(name)

                label = f"  {name}"
                if desc:
                    label += f" [dim]({desc})[/]"
                yield Label(label)

                if ptype == "boolean":
                    yield Switch(
                        value=bool(current) if current is not None else False,
                        id=f"param-{name}",
                    )
                else:
                    yield Input(
                        value=str(current) if current is not None else "",
                        placeholder=f"Default {ptype}",
                        id=f"param-{name}",
                    )

    def load_schema(
        self,
        input_schema: Dict[str, Any],
        current_defaults: Dict[str, Any] | None = None,
    ) -> None:
        """Reload the editor with a new tool schema and defaults.

        Replaces all child widgets with fresh inputs matching the schema.
        """
        self._schema = input_schema
        self._defaults = current_defaults or {}
        # Re-render children
        self.remove_children()
        properties = input_schema.get("properties", {})
        if not properties:
            self.mount(Label("[dim]No parameters to edit[/]"))
            return
        container = Vertical()
        self.mount(container)
        container.mount(Label(f"[b]Defaults for {self._tool_name}[/b]"))
        for name, prop in properties.items():
            ptype = prop.get("type", "string")
            desc = prop.get("description", "")
            current = self._defaults.get(name)
            label_text = f"  {name}"
            if desc:
                label_text += f" [dim]({desc})[/]"
            container.mount(Label(label_text))
            if ptype == "boolean":
                container.mount(
                    Switch(
                        value=bool(current) if current is not None else False,
                        id=f"param-{name}",
                    )
                )
            else:
                container.mount(
                    Input(
                        value=str(current) if current is not None else "",
                        placeholder=f"Default {ptype}",
                        id=f"param-{name}",
                    )
                )

    def on_input_changed(self, event: Input.Changed) -> None:
        self._emit_defaults()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        self._emit_defaults()

    def _emit_defaults(self) -> None:
        """Collect current values and post DefaultsChanged."""
        defaults = self.collect_defaults()
        self.post_message(self.DefaultsChanged(self._tool_name, defaults))

    def collect_defaults(self) -> Dict[str, Any]:
        """Collect current default values from the form."""
        properties = self._schema.get("properties", {})
        defaults: Dict[str, Any] = {}
        for name, prop in properties.items():
            try:
                widget = self.query_one(f"#param-{name}")
                if isinstance(widget, Switch):
                    defaults[name] = widget.value
                elif isinstance(widget, Input):
                    raw = widget.value
                    if raw:
                        ptype = prop.get("type", "string")
                        if ptype == "integer":
                            defaults[name] = int(raw)
                        elif ptype == "number":
                            defaults[name] = float(raw)
                        else:
                            defaults[name] = raw
            except (NoMatches, ValueError):
                pass
        return defaults
