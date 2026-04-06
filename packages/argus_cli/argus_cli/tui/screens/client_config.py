"""Client auto-configuration export modal.

Detects MCP clients (VS Code, Cursor, Claude, etc.) and generates
the appropriate configuration snippet pointing to this Argus instance.
"""

from __future__ import annotations

import contextlib
import json as _json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Label, OptionList, Static, TextArea

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)

# Known MCP client config locations
_CLIENT_CONFIGS: list[dict[str, str]] = [
    {
        "name": "VS Code (GitHub Copilot)",
        "path": "~/.vscode/settings.json",
        "key": "mcpServers",
    },
    {
        "name": "Cursor",
        "path": "~/.cursor/mcp.json",
        "key": "mcpServers",
    },
    {
        "name": "Claude Code",
        "path": "~/.claude/claude_desktop_config.json",
        "key": "mcpServers",
    },
    {
        "name": "Claude Desktop",
        "path": "~/Library/Application Support/Claude/claude_desktop_config.json",
        "key": "mcpServers",
    },
    {
        "name": "Windsurf",
        "path": "~/.codeium/windsurf/mcp.json",
        "key": "mcpServers",
    },
]


class ClientConfigModal(ModalScreen[Optional[str]]):
    """Modal to export Argus MCP config for detected clients."""

    DEFAULT_CSS = """
    ClientConfigModal {
        align: center middle;
    }
    #client-config-dialog {
        width: 80;
        max-width: 90%;
        height: auto;
        max-height: 80%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #client-config-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    #client-list {
        height: auto;
        max-height: 8;
        margin-bottom: 1;
    }
    #client-preview {
        height: 12;
        margin-bottom: 1;
    }
    #client-config-actions {
        height: 3;
        align: right middle;
    }
    #client-config-actions Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("w", "write_config", "Write"),
        ("c", "copy_config", "Copy"),
    ]

    def __init__(self, server_url: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._server_url = server_url
        self._detected: list[dict[str, Any]] = []
        self._selected_index: int = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="client-config-dialog"):
            yield Label("[b]Export Client Configuration[/b]", id="client-config-title")
            yield Static(f"Argus MCP endpoint: {self._server_url}", id="client-endpoint")

            yield Label("[b]Detected Clients:[/b]")
            yield OptionList(id="client-list")

            yield Label("[b]Preview:[/b]")
            yield TextArea("", id="client-preview", read_only=True, language="json")

            with Horizontal(id="client-config-actions"):
                yield Button("Write to File", variant="primary", id="btn-client-write")
                yield Button("Copy", variant="default", id="btn-client-copy")
                yield Button("Close", variant="default", id="btn-client-close")

    def on_mount(self) -> None:
        """Detect installed clients and populate list."""
        self._detect_clients()
        try:
            option_list = self.query_one("#client-list", OptionList)
            for client in self._detected:
                status = "●" if client["exists"] else "○"
                option_list.add_option(f"{status} {client['name']}  {client['path']}")
            if self._detected:
                self._update_preview(0)
        except NoMatches:
            pass

    def _detect_clients(self) -> None:
        """Check which client config files exist."""
        self._detected = []
        for cfg in _CLIENT_CONFIGS:
            expanded = os.path.expanduser(cfg["path"])
            self._detected.append(
                {
                    "name": cfg["name"],
                    "path": cfg["path"],
                    "expanded_path": expanded,
                    "key": cfg["key"],
                    "exists": Path(expanded).exists(),
                }
            )

    def _generate_config(self, client: dict[str, Any]) -> str:
        """Generate the MCP config snippet for a client."""
        config = {
            client["key"]: {
                "argus-mcp": {
                    "url": self._server_url,
                    "transport": "sse",
                }
            }
        }
        return _json.dumps(config, indent=2)

    def _update_preview(self, index: int) -> None:
        """Update the preview pane for the selected client."""
        if 0 <= index < len(self._detected):
            self._selected_index = index
            client = self._detected[index]
            snippet = self._generate_config(client)
            with contextlib.suppress(NoMatches):
                self.query_one("#client-preview", TextArea).load_text(snippet)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        """Update preview when a different client is highlighted."""
        if event.option_list.id == "client-list":
            self._update_preview(event.option_index)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-client-write":
            self.action_write_config()
        elif event.button.id == "btn-client-copy":
            self.action_copy_config()
        elif event.button.id == "btn-client-close":
            self.action_cancel()

    def action_write_config(self) -> None:
        """Write config snippet to the selected client's config file."""
        if not self._detected:
            return
        client = self._detected[self._selected_index]
        path = client["expanded_path"]

        try:
            existing = {}
            if Path(path).exists():
                with open(path) as f:
                    existing = _json.load(f)

            # Merge the mcpServers section
            key = client["key"]
            if key not in existing:
                existing[key] = {}
            existing[key]["argus-mcp"] = {
                "url": self._server_url,
                "transport": "sse",
            }

            Path(path).parent.mkdir(parents=True, exist_ok=True)
            with open(path, "w") as f:
                _json.dump(existing, f, indent=2)

            self.notify(
                f"Written to {client['path']}",
                title="Config Exported",
                severity="information",
            )
            self.dismiss("written")
        except OSError as exc:
            self.notify(f"Write failed: {exc}", title="Error", severity="error")

    def action_copy_config(self) -> None:
        """Copy config snippet to clipboard (via notify as fallback)."""
        if not self._detected:
            return
        client = self._detected[self._selected_index]
        snippet = self._generate_config(client)
        # Textual doesn't have native clipboard; copy via app
        try:
            import subprocess

            proc = subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=snippet.encode(),
                capture_output=True,
                timeout=2,
            )
            if proc.returncode == 0:
                self.notify("Copied to clipboard!", title="Copy", severity="information")
            else:
                self.notify("Copy to clipboard failed — xclip not available", severity="warning")
        except (FileNotFoundError, subprocess.SubprocessError, OSError):
            self.notify("Clipboard not available. Config shown in preview.", severity="warning")

    def action_cancel(self) -> None:
        self.dismiss(None)
