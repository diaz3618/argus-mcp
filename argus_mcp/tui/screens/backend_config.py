"""Backend configuration modal — transport-specific options for installing backends.

Supports configuring stdio, sse, and streamable-http backends with
all relevant options. Used both for registry installs (pre-filled)
and custom backend add (empty form).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static, Switch

from argus_mcp._error_utils import safe_query
from argus_mcp.registry.models import ServerEntry

logger = logging.getLogger(__name__)

# Transport types
_TRANSPORTS = [
    ("stdio", "stdio — Local subprocess"),
    ("sse", "sse — Server-Sent Events"),
    ("streamable-http", "streamable-http — HTTP streaming"),
]


class BackendConfigModal(ModalScreen[Optional[Tuple[str, Dict[str, Any]]]]):
    """Modal for configuring a backend before installation.

    Returns ``(name, config_dict)`` on install, or ``None`` on cancel.

    Parameters
    ----------
    entry : ServerEntry | None
        If provided, pre-fills fields from the registry entry.
    """

    DEFAULT_CSS = """
    BackendConfigModal {
        align: center middle;
    }
    #bcm-dialog {
        width: 80;
        max-width: 90%;
        height: auto;
        max-height: 90%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #bcm-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    #bcm-scroll {
        height: auto;
        max-height: 50;
    }
    .bcm-section {
        margin-top: 1;
        margin-bottom: 0;
        text-style: bold;
        color: $accent;
    }
    .bcm-field-label {
        margin-top: 1;
        color: $text;
    }
    .bcm-field-hint {
        color: $text-muted;
        text-style: italic;
    }
    #bcm-type-fields {
        height: auto;
    }
    #bcm-actions {
        height: 3;
        align: right middle;
        margin-top: 1;
    }
    #bcm-actions Button {
        margin-left: 1;
    }
    #bcm-preview {
        margin-top: 1;
        color: $text-muted;
        height: auto;
        max-height: 8;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("ctrl+s", "install", "Install"),
    ]

    def __init__(self, entry: Optional[ServerEntry] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._entry = entry
        self._mode = "registry" if entry else "custom"

    def compose(self) -> ComposeResult:
        entry = self._entry
        title = f"Configure: {entry.name}" if entry else "Add New Backend"

        with Vertical(id="bcm-dialog"):
            yield Label(f"[b]{title}[/b]", id="bcm-title")

            with VerticalScroll(id="bcm-scroll"):
                # Common fields
                yield Label("General", classes="bcm-section")

                yield Label("Backend Name", classes="bcm-field-label")
                yield Input(
                    value=entry.name if entry else "",
                    placeholder="e.g., my-mcp-server",
                    id="bcm-name",
                )

                yield Label("Transport Type", classes="bcm-field-label")
                transport_val = entry.transport if entry else Select.BLANK
                yield Select(
                    [(label, val) for val, label in _TRANSPORTS],
                    value=transport_val,
                    id="bcm-transport",
                    allow_blank=not bool(entry),
                )

                yield Label("Group", classes="bcm-field-label")
                yield Label("Assign to a server group (optional)", classes="bcm-field-hint")
                yield Input(
                    value="",
                    placeholder="default",
                    id="bcm-group",
                )

                yield Label("Enabled", classes="bcm-field-label")
                yield Switch(value=True, id="bcm-enabled")

                # Type-specific fields
                yield Label("Transport Options", classes="bcm-section")
                with Vertical(id="bcm-type-fields"):
                    # stdio fields
                    yield Label("Command", classes="bcm-field-label", id="lbl-command")
                    yield Input(
                        value=entry.command if entry and entry.command else "",
                        placeholder="e.g., npx -y @org/mcp-server",
                        id="bcm-command",
                    )

                    yield Label(
                        "Arguments (space-separated)",
                        classes="bcm-field-label",
                        id="lbl-args",
                    )
                    args_str = " ".join(entry.args) if entry and entry.args else ""
                    yield Input(
                        value=args_str,
                        placeholder="e.g., --port 8080 --verbose",
                        id="bcm-args",
                    )

                    yield Label(
                        "Environment Variables (KEY=VALUE, one per line)",
                        classes="bcm-field-label",
                        id="lbl-env",
                    )
                    yield Label(
                        "e.g., API_KEY=secret123",
                        classes="bcm-field-hint",
                        id="hint-env",
                    )
                    yield Input(
                        value="",
                        placeholder="KEY=VALUE (comma-separated for multiple)",
                        id="bcm-env",
                    )

                    # URL fields (sse / streamable-http)
                    yield Label("URL", classes="bcm-field-label", id="lbl-url")
                    yield Input(
                        value=entry.url if entry and entry.url else "",
                        placeholder="e.g., https://mcp.example.com/sse",
                        id="bcm-url",
                    )

                    yield Label(
                        "Headers (KEY:VALUE, comma-separated)",
                        classes="bcm-field-label",
                        id="lbl-headers",
                    )
                    yield Input(
                        value="",
                        placeholder="Authorization:Bearer xxx, X-Custom:val",
                        id="bcm-headers",
                    )

                # Advanced
                yield Label("Advanced", classes="bcm-section")

                yield Label("Timeout (seconds)", classes="bcm-field-label")
                yield Input(
                    value="",
                    placeholder="30",
                    id="bcm-timeout",
                    type="number",
                )

                yield Label(
                    "Filters (tool name patterns, comma-separated)", classes="bcm-field-label"
                )
                yield Label(
                    "Include/exclude tools: +pattern or -pattern",
                    classes="bcm-field-hint",
                )
                yield Input(
                    value="",
                    placeholder="+useful_tool, -debug_*",
                    id="bcm-filters",
                )

                # Preview
                yield Static("", id="bcm-preview")

            # Actions
            with Horizontal(id="bcm-actions"):
                yield Button(
                    "Install" if self._mode == "registry" else "Add Backend",
                    variant="success",
                    id="btn-bcm-install",
                )
                yield Button("Cancel", variant="default", id="btn-bcm-cancel")

    def on_mount(self) -> None:
        """Set initial field visibility based on transport type."""
        self._update_type_fields()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Update visible fields when transport type changes."""
        if event.select.id == "bcm-transport":
            self._update_type_fields()
            self._update_preview()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Update config preview when any field changes."""
        self._update_preview()

    def _update_type_fields(self) -> None:
        """Show/hide fields based on the selected transport type."""
        transport_sel = self.query_one("#bcm-transport", Select)
        transport = transport_sel.value if transport_sel.value != Select.BLANK else None

        is_stdio = transport == "stdio"
        is_url = transport in ("sse", "streamable-http")

        # stdio fields
        for widget_id in (
            "lbl-command",
            "bcm-command",
            "lbl-args",
            "bcm-args",
            "lbl-env",
            "hint-env",
            "bcm-env",
        ):
            w = safe_query(self, f"#{widget_id}")
            if w is not None:
                w.display = is_stdio

        # URL fields
        for widget_id in ("lbl-url", "bcm-url", "lbl-headers", "bcm-headers"):
            w = safe_query(self, f"#{widget_id}")
            if w is not None:
                w.display = is_url

    def _update_preview(self) -> None:
        """Update the config preview text."""
        config = self._build_config()
        name = self._get_name()
        if config and name:
            import json

            preview_text = (
                f"[dim]Config preview for '{name}':[/dim]\n{json.dumps(config, indent=2)}"
            )
        else:
            preview_text = "[dim]Fill in required fields to see config preview[/dim]"

        preview = safe_query(self, "#bcm-preview", Static)
        if preview is not None:
            preview.update(preview_text)

    def _get_name(self) -> str:
        """Get the backend name from the input."""
        name_input = safe_query(self, "#bcm-name", Input)
        return name_input.value.strip() if name_input is not None else ""

    @staticmethod
    def _parse_kv_string(text: str, sep: str) -> Dict[str, str]:
        """Parse comma-separated key/value pairs (e.g. ``k=v, k2=v2``)."""
        result: Dict[str, str] = {}
        for pair in text.split(","):
            pair = pair.strip()
            if sep in pair:
                k, v = pair.split(sep, 1)
                result[k.strip()] = v.strip()
        return result

    def _build_stdio_fields(self, config: Dict[str, Any]) -> bool:
        """Populate *config* with stdio-specific fields. Returns *False* if required fields are missing."""
        command = self.query_one("#bcm-command", Input).value.strip()
        if not command:
            return False
        config["command"] = command

        args = self.query_one("#bcm-args", Input).value.strip()
        if args:
            config["args"] = args.split()

        env_str = self.query_one("#bcm-env", Input).value.strip()
        if env_str:
            env = self._parse_kv_string(env_str, "=")
            if env:
                config["env"] = env
        return True

    def _build_remote_fields(self, config: Dict[str, Any]) -> bool:
        """Populate *config* with sse / streamable-http fields. Returns *False* if URL is missing."""
        url = self.query_one("#bcm-url", Input).value.strip()
        if not url:
            return False
        config["url"] = url

        headers_str = self.query_one("#bcm-headers", Input).value.strip()
        if headers_str:
            headers = self._parse_kv_string(headers_str, ":")
            if headers:
                config["headers"] = headers
        return True

    @staticmethod
    def _parse_filter_patterns(text: str) -> Optional[Dict[str, Any]]:
        """Parse ``+include,-exclude`` filter text into a filters dict."""
        include: list[str] = []
        exclude: list[str] = []
        for pat in text.split(","):
            pat = pat.strip()
            if pat.startswith("-"):
                exclude.append(pat[1:])
            elif pat.startswith("+"):
                include.append(pat[1:])
            else:
                include.append(pat)
        if not include and not exclude:
            return None
        f: Dict[str, Any] = {}
        if include:
            f["include"] = include
        if exclude:
            f["exclude"] = exclude
        return f

    def _apply_common_fields(self, config: Dict[str, Any]) -> None:
        """Apply transport-independent optional fields to *config*."""
        timeout_str = self.query_one("#bcm-timeout", Input).value.strip()
        if timeout_str:
            try:
                config["timeout"] = int(timeout_str)
            except ValueError:
                pass

        filters_str = self.query_one("#bcm-filters", Input).value.strip()
        if filters_str:
            parsed = self._parse_filter_patterns(filters_str)
            if parsed:
                config["filters"] = parsed

        enabled = self.query_one("#bcm-enabled", Switch).value
        if not enabled:
            config["enabled"] = False

        group = self.query_one("#bcm-group", Input).value.strip()
        if group:
            config["group"] = group

    def _build_config(self) -> Optional[Dict[str, Any]]:
        """Build the backend config dict from current form values."""
        transport_sel = safe_query(self, "#bcm-transport", Select)
        if transport_sel is None:
            return None
        transport = transport_sel.value
        if transport == Select.BLANK:
            return None

        config: Dict[str, Any] = {"type": transport}

        if transport == "stdio":
            if not self._build_stdio_fields(config):
                return None
        elif transport in ("sse", "streamable-http"):
            if not self._build_remote_fields(config):
                return None

        self._apply_common_fields(config)
        return config

    def _validate(self) -> Optional[str]:
        """Validate form and return error message or None if valid."""
        name = self._get_name()
        if not name:
            return "Backend name is required"
        if " " in name:
            return "Backend name must not contain spaces"

        transport_sel = self.query_one("#bcm-transport", Select)
        if transport_sel.value == Select.BLANK:
            return "Transport type is required"

        transport = transport_sel.value

        if transport == "stdio":
            command = self.query_one("#bcm-command", Input).value.strip()
            if not command:
                return "Command is required for stdio backends"
        elif transport in ("sse", "streamable-http"):
            url = self.query_one("#bcm-url", Input).value.strip()
            if not url:
                return "URL is required for remote backends"

        return None

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-bcm-install":
            self.action_install()
        elif event.button.id == "btn-bcm-cancel":
            self.action_cancel()

    def action_install(self) -> None:
        """Validate and dismiss with (name, config) tuple."""
        error = self._validate()
        if error:
            self.app.notify(error, severity="error")
            return

        name = self._get_name()
        config = self._build_config()
        if config is None:
            self.app.notify("Cannot build config — fill required fields", severity="error")
            return

        self.dismiss((name, config))

    def action_cancel(self) -> None:
        """Dismiss without installing."""
        self.dismiss(None)
