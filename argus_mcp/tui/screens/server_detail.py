"""Server detail modal — shows full server info from the registry.

Displays server metadata, tools list, version, categories,
and an install button. Launched from the Registry screen.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Label, Static

from argus_mcp.registry.models import ServerEntry


class ServerDetailModal(ModalScreen[Optional[Dict[str, Any]]]):
    """Modal showing full details for a registry server entry.

    Returns the backend config dict if the user clicks Install,
    or ``None`` if dismissed.
    """

    DEFAULT_CSS = """
    ServerDetailModal {
        align: center middle;
    }
    #server-detail-dialog {
        width: 80;
        max-width: 90%;
        height: auto;
        max-height: 85%;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #server-detail-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    #server-detail-meta {
        margin-bottom: 1;
    }
    #server-detail-description {
        margin-bottom: 1;
    }
    #server-detail-tools-table {
        height: auto;
        max-height: 16;
        margin-bottom: 1;
    }
    #server-detail-categories {
        margin-bottom: 1;
        color: $text-muted;
    }
    #server-detail-actions {
        height: 3;
        align: right middle;
    }
    #server-detail-actions Button {
        margin-left: 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("i", "install", "Install"),
    ]

    def __init__(self, entry: ServerEntry, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._entry = entry

    def compose(self) -> ComposeResult:
        entry = self._entry
        with Vertical(id="server-detail-dialog"):
            yield Label(
                (
                    f"[b]{entry.name}[/b]  v{entry.version}"
                    if entry.version
                    else f"[b]{entry.name}[/b]"
                ),
                id="server-detail-title",
            )

            # Metadata
            transport_color = {
                "stdio": "cyan",
                "sse": "yellow",
                "streamable-http": "green",
            }.get(entry.transport, "white")
            meta_lines = [
                f"Transport: [{transport_color}]{entry.transport}[/{transport_color}]",
                f"Tools: [b]{len(entry.tools)}[/b]",
            ]
            if entry.url:
                meta_lines.append(f"URL: {entry.url}")
            if entry.command:
                cmd = entry.command
                if entry.args:
                    cmd += " " + " ".join(entry.args)
                meta_lines.append(f"Command: [dim]{cmd}[/]")
            yield Static("\n".join(meta_lines), id="server-detail-meta")

            # Description
            if entry.description:
                yield Static(entry.description, id="server-detail-description")

            # Tools table
            if entry.tools:
                yield Label("[b]Tools[/b]")
                with VerticalScroll():
                    yield DataTable(id="server-detail-tools-table")

            # Categories
            if entry.categories:
                cats = ", ".join(entry.categories)
                yield Static(f"Categories: {cats}", id="server-detail-categories")

            # Extra metadata from registry
            if entry.extra:
                extras = []
                for k, v in entry.extra.items():
                    if isinstance(v, (str, int, float, bool)):
                        extras.append(f"{k}: {v}")
                if extras:
                    yield Static(
                        "[dim]" + " │ ".join(extras) + "[/]",
                        id="server-detail-extra",
                    )

            # Action buttons
            with Horizontal(id="server-detail-actions"):
                yield Button("Install", variant="success", id="btn-detail-install")
                yield Button("Close", variant="default", id="btn-detail-close")

    def on_mount(self) -> None:
        """Populate the tools table after mount."""
        if not self._entry.tools:
            return
        try:
            table = self.query_one("#server-detail-tools-table", DataTable)
            table.add_columns("Name", "Description")
            table.cursor_type = "row"
            for tool in self._entry.tools:
                desc = (
                    tool.description[:60] + "…" if len(tool.description) > 60 else tool.description
                )
                table.add_row(tool.name, desc, key=tool.name)
        except NoMatches:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-detail-install":
            self.action_install()
        elif event.button.id == "btn-detail-close":
            self.action_cancel()

    def action_install(self) -> None:
        """Dismiss with the backend config for installation."""
        self.dismiss(self._entry.to_backend_config())

    def action_cancel(self) -> None:
        """Dismiss without installing."""
        self.dismiss(None)
