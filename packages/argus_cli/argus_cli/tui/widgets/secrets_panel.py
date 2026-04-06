"""Secret management widget — encrypted secret store UI.

Displays stored secrets with masked values, reference syntax,
and provides CRUD operations for the secret store.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from textual import on
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Input, Label, Select, Static

from argus_cli.tui._error_utils import safe_query

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class SecretsPanel(Widget):
    """Secrets management panel for settings."""

    DEFAULT_CSS = """
    SecretsPanel {
        height: auto;
        max-height: 20;
        border: round $accent;
        padding: 0 1;
    }
    #secrets-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 0;
    }
    #secrets-store-info {
        height: 1;
        color: $text-muted;
    }
    #secrets-table {
        height: auto;
        max-height: 10;
    }
    #secrets-ref-hint {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        margin-top: 1;
    }
    #secrets-actions {
        height: 3;
        padding: 0 1;
    }
    #secrets-actions Button {
        margin-right: 1;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._secrets: list[dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Secrets Manager[/b]", id="secrets-title")
            yield Static("Store: AES-256-GCM (local)    [Unlock 🔓]", id="secrets-store-info")
            yield DataTable(id="secrets-table")
            yield Static(
                "Config reference syntax:  {{ secrets.name }}",
                id="secrets-ref-hint",
            )
            with Horizontal(id="secrets-actions"):
                yield Button("New Secret", id="btn-secret-new", variant="primary")
                yield Button("Edit", id="btn-secret-edit", variant="default")
                yield Button("Delete", id="btn-secret-delete", variant="error")
                yield Button("Rotate", id="btn-secret-rotate", variant="warning")

    def on_mount(self) -> None:
        if table := safe_query(self, "#secrets-table", DataTable):
            table.add_columns("Name", "Source", "Used By", "Last Set")
            table.cursor_type = "row"
            table.zebra_stripes = True

    def update_secrets(self, secrets: list[dict[str, Any]]) -> None:
        """Refresh the secrets table."""
        self._secrets = secrets
        table = safe_query(self, "#secrets-table", DataTable)
        if table is None:
            return
        table.clear()
        for s in secrets:
            name = s.get("name", "?")
            source = s.get("source", "encrypted")
            used_by = s.get("used_by", "—")
            last_set = s.get("last_set", "—")
            table.add_row(name, source, used_by, str(last_set))

    def _get_selected_secret(self) -> dict[str, Any] | None:
        """Return the secret dict for the currently selected table row."""
        table = safe_query(self, "#secrets-table", DataTable)
        if table is None or table.cursor_row is None:
            return None
        try:
            idx = table.cursor_row
            if 0 <= idx < len(self._secrets):
                return self._secrets[idx]
        except (IndexError, TypeError):
            pass
        return None

    @on(Button.Pressed, "#btn-secret-new")
    def _handle_new(self, event: Button.Pressed) -> None:
        def _on_result(result: dict[str, str] | None) -> None:
            if result:
                self._secrets.append(result)
                self.update_secrets(self._secrets)
                self.notify(f"Added secret '{result['name']}'")

        self.app.push_screen(SecretEditorModal(), _on_result)

    @on(Button.Pressed, "#btn-secret-edit")
    def _handle_edit(self, event: Button.Pressed) -> None:
        secret = self._get_selected_secret()
        if secret is None:
            self.notify("Select a secret to edit", severity="warning")
            return

        def _on_result(result: dict[str, str] | None) -> None:
            if result:
                idx = self._secrets.index(secret)
                self._secrets[idx] = result
                self.update_secrets(self._secrets)
                self.notify(f"Updated secret '{result['name']}'")

        self.app.push_screen(SecretEditorModal(existing=secret), _on_result)

    @on(Button.Pressed, "#btn-secret-delete")
    def _handle_delete(self, event: Button.Pressed) -> None:
        secret = self._get_selected_secret()
        if secret is None:
            self.notify("Select a secret to delete", severity="warning")
            return
        name = secret.get("name", "?")
        self._secrets.remove(secret)
        self.update_secrets(self._secrets)
        self.notify(f"Deleted secret '{name}'")

    @on(Button.Pressed, "#btn-secret-rotate")
    def _handle_rotate(self, event: Button.Pressed) -> None:
        secret = self._get_selected_secret()
        if secret is None:
            self.notify("Select a secret to rotate", severity="warning")
            return
        self.notify(
            f"Rotation for '{secret.get('name', '?')}' — "
            f"update the secret value and re-save to rotate",
            severity="information",
        )


class SecretEditorModal(ModalScreen[Optional[dict[str, str]]]):
    """Modal for creating or editing a secret."""

    DEFAULT_CSS = """
    SecretEditorModal {
        align: center middle;
    }
    #secret-editor-dialog {
        width: 60;
        height: auto;
        max-height: 20;
        border: thick $primary;
        background: $surface;
        padding: 1 2;
    }
    #se-title {
        text-style: bold;
        text-align: center;
        margin-bottom: 1;
    }
    .se-row {
        height: 3;
        align: left middle;
        margin-bottom: 1;
    }
    .se-label {
        width: 14;
        content-align: left middle;
        color: $text-muted;
    }
    .se-row Input {
        width: 1fr;
    }
    .se-row Select {
        width: 1fr;
    }
    #se-actions {
        height: 3;
        align: center middle;
    }
    #se-actions Button {
        margin: 0 1;
    }
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, existing: dict[str, str] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._existing = existing

    def compose(self) -> ComposeResult:
        title = "Edit Secret" if self._existing else "New Secret"
        with Vertical(id="secret-editor-dialog"):
            yield Label(f"[b]{title}[/b]", id="se-title")

            with Horizontal(classes="se-row"):
                yield Label("Name:", classes="se-label")
                yield Input(
                    value=self._existing.get("name", "") if self._existing else "",
                    id="se-name-input",
                    placeholder="secret_name",
                )
            with Horizontal(classes="se-row"):
                yield Label("Value:", classes="se-label")
                yield Input(
                    value="",
                    id="se-value-input",
                    password=True,
                    placeholder="secret value",
                )
            with Horizontal(classes="se-row"):
                yield Label("Source:", classes="se-label")
                yield Select(
                    [
                        ("encrypted", "encrypted"),
                        ("keyring", "keyring"),
                        ("env", "env"),
                        ("1password", "1password"),
                    ],
                    value=(
                        self._existing.get("source", "encrypted") if self._existing else "encrypted"
                    ),
                    id="se-source-select",
                    allow_blank=False,
                )

            with Horizontal(id="se-actions"):
                yield Button("Save", variant="primary", id="btn-se-save")
                yield Button("Cancel", variant="default", id="btn-se-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-se-save":
            name_input = safe_query(self, "#se-name-input", Input)
            value_input = safe_query(self, "#se-value-input", Input)
            source_select = safe_query(self, "#se-source-select", Select)
            if name_input is None or value_input is None or source_select is None:
                self.dismiss(None)
                return
            name = name_input.value.strip()
            value = value_input.value
            source = source_select.value
            if not name:
                self.notify("Secret name is required", severity="warning")
                return
            self.dismiss({"name": name, "value": value, "source": str(source)})
        elif event.button.id == "btn-se-cancel":
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
