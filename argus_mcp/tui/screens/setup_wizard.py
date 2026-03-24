"""Setup Wizard screen — guided configuration editor with import/export.

Provides a full configuration editor for creating and modifying all
Argus MCP config files.  Features:

- YAML editor for ``config.yaml`` with live syntax validation
- Import / Export / Save / Save As buttons
- Quick-add backend templates (stdio, sse, streamable-http)
- Section navigation for large configs
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Label,
    Select,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)

from argus_mcp._error_utils import safe_query
from argus_mcp.config.loader import find_config_file
from argus_mcp.tui.screens.base import ArgusScreen

logger = logging.getLogger(__name__)

_STDIO_TEMPLATE = """\
  {name}:
    type: stdio
    command: {command}
    args:
      - "{arg}"
    timeouts:
      init: 60
      cap_fetch: 30
"""

_SSE_TEMPLATE = """\
  {name}:
    type: sse
    url: "{url}"
    headers:
      Authorization: "Bearer ${{API_TOKEN}}"
    timeouts:
      init: 60
      cap_fetch: 30
"""

_HTTP_TEMPLATE = """\
  {name}:
    type: streamable-http
    url: "{url}"
    headers:
      Authorization: "Bearer ${{API_TOKEN}}"
    timeouts:
      init: 60
      cap_fetch: 30
"""

_MINIMAL_CONFIG = """\
# Argus MCP Configuration
# Documentation: docs/configuration.md

version: "1"

server:
  host: "127.0.0.1"
  port: 9000
  transport: streamable-http
  management:
    enabled: true

backends:
  # Add your MCP server backends below.
  # Use the "Add Backend" tab for quick templates.
  {}

conflict_resolution:
  strategy: first-wins

audit:
  enabled: true
  file: "logs/audit.jsonl"

feature_flags:
  hot_reload: true
"""

# Project root detection
_PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _find_config_path() -> Path:
    """Return the path to the config file (YAML only).

    Argus MCP uses YAML configuration exclusively.  JSON config
    files are not supported.
    """
    resolved = Path(find_config_file())
    if resolved.is_file():
        return resolved
    return _PROJECT_ROOT / "config.yaml"


def _load_config_text() -> str:
    """Read the current config file as raw text."""
    path = _find_config_path()
    if path.is_file():
        return path.read_text(encoding="utf-8")
    return _MINIMAL_CONFIG


def _validate_yaml(text: str) -> str | None:
    """Return an error message if the YAML is invalid, else None."""
    try:
        import yaml  # type: ignore[import-untyped]

        data = yaml.safe_load(text)
        if not isinstance(data, dict):
            return "Config must be a YAML mapping (dict) at the top level."
        if "version" not in data:
            return "Missing required field: 'version'"
        return None
    except ImportError:
        return None  # Can't validate without pyyaml
    except yaml.YAMLError as exc:
        return f"YAML parse error: {exc}"


class SetupWizardScreen(ArgusScreen):
    """Configuration setup wizard with editor, templates, and import/export."""

    def compose_content(self) -> ComposeResult:
        with TabbedContent(id="wizard-tabs"):
            with TabPane("Config Editor", id="tab-wizard-editor"):
                yield _ConfigEditorPanel(id="wizard-editor-panel")
            with TabPane("Add Backend", id="tab-wizard-backend"):
                yield _BackendBuilderPanel(id="wizard-backend-panel")
            with TabPane("Quick Start", id="tab-wizard-quickstart"):
                yield _QuickStartPanel(id="wizard-quickstart-panel")


class _ConfigEditorPanel(Static):
    """Full YAML editor with import/export/save/save-as."""

    DEFAULT_CSS = """
    _ConfigEditorPanel {
        height: 1fr;
        padding: 0 1;
    }
    #wizard-editor-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 0;
    }
    #wizard-editor-path {
        height: 1;
        color: $text-muted;
        margin-bottom: 1;
    }
    #wizard-editor-area {
        height: 1fr;
        min-height: 15;
    }
    #wizard-editor-buttons {
        height: 3;
        padding-top: 1;
    }
    #wizard-editor-buttons Button {
        margin-right: 1;
    }
    #wizard-validation {
        height: 1;
        padding: 0 1;
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._current_path: Path = _find_config_path()

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Configuration Editor[/b]", id="wizard-editor-title")
            yield Static(f"File: {self._current_path}", id="wizard-editor-path")
            yield TextArea(
                _load_config_text(),
                language="yaml",
                id="wizard-editor-area",
                show_line_numbers=True,
            )
            yield Static("", id="wizard-validation")
            with Horizontal(id="wizard-editor-buttons"):
                yield Button("Save", id="btn-wizard-save", variant="primary")
                yield Button("Save As…", id="btn-wizard-saveas", variant="default")
                yield Button("Import…", id="btn-wizard-import", variant="default")
                yield Button("Export…", id="btn-wizard-export", variant="default")
                yield Button("Validate", id="btn-wizard-validate", variant="warning")
                yield Button("Reset", id="btn-wizard-reset", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn = event.button.id
        if btn == "btn-wizard-save":
            self._save()
        elif btn == "btn-wizard-saveas":
            self._save_as()
        elif btn == "btn-wizard-import":
            self._import_config()
        elif btn == "btn-wizard-export":
            self._export_config()
        elif btn == "btn-wizard-validate":
            self._validate()
        elif btn == "btn-wizard-reset":
            self._reset()

    def _get_editor_text(self) -> str:
        w = safe_query(self, "#wizard-editor-area", TextArea)
        return w.text if w else ""

    def _set_validation(self, msg: str) -> None:
        if w := safe_query(self, "#wizard-validation", Static):
            w.update(msg)

    def _set_path_label(self) -> None:
        if w := safe_query(self, "#wizard-editor-path", Static):
            w.update(f"File: {self._current_path}")

    def _validate(self) -> None:
        text = self._get_editor_text()
        err = _validate_yaml(text)
        if err:
            self._set_validation(f"[red]✕ {err}[/red]")
            self.app.notify(f"Validation failed: {err}", severity="error")
        else:
            self._set_validation("[green]✓ Valid YAML configuration[/green]")
            self.app.notify("Configuration is valid.", severity="information")

    def _save(self) -> None:
        text = self._get_editor_text()
        err = _validate_yaml(text)
        if err:
            self._set_validation(f"[red]✕ {err}[/red]")
            self.app.notify(f"Cannot save — invalid YAML: {err}", severity="error")
            return

        try:
            self._current_path.parent.mkdir(parents=True, exist_ok=True)
            self._current_path.write_text(text, encoding="utf-8")
            self._set_validation(f"[green]✓ Saved to {self._current_path.name}[/green]")
            self.app.notify(
                f"Configuration saved to {self._current_path}",
                severity="information",
            )
        except OSError as exc:
            self._set_validation(f"[red]✕ Save failed: {exc}[/red]")
            self.app.notify(f"Save failed: {exc}", severity="error")

    def _save_as(self) -> None:
        """Open a modal to enter a new file path, then save."""

        def _on_path(path_str: str | None) -> None:
            if not path_str:
                return
            text = self._get_editor_text()
            err = _validate_yaml(text)
            if err:
                self.app.notify(f"Invalid YAML: {err}", severity="error")
                return
            dest = Path(path_str).expanduser()
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text, encoding="utf-8")
                self._current_path = dest
                self._set_path_label()
                self._set_validation(f"[green]✓ Saved to {dest.name}[/green]")
                self.app.notify(f"Saved to {dest}", severity="information")
            except OSError as exc:
                self.app.notify(f"Save failed: {exc}", severity="error")

        self.app.push_screen(
            _FilePathModal(
                title="Save As",
                prompt="Enter file path:",
                default=str(self._current_path),
            ),
            _on_path,
        )

    def _import_config(self) -> None:
        """Open a modal to enter an import file path."""

        def _on_path(path_str: str | None) -> None:
            if not path_str:
                return
            src = Path(path_str).expanduser()
            if not src.is_file():
                self.app.notify(f"File not found: {src}", severity="error")
                return
            try:
                text = src.read_text(encoding="utf-8")
                err = _validate_yaml(text)
                if err:
                    self.app.notify(f"Imported file has errors: {err}", severity="warning")
                self.query_one("#wizard-editor-area", TextArea).load_text(text)
                self._current_path = src
                self._set_path_label()
                self._set_validation(f"[green]✓ Imported from {src.name}[/green]")
                self.app.notify(f"Imported: {src}", severity="information")
            except OSError as exc:
                self.app.notify(f"Import failed: {exc}", severity="error")

        self.app.push_screen(
            _FilePathModal(
                title="Import Config",
                prompt="Enter file path to import:",
                default=str(_PROJECT_ROOT / "example_config.yaml"),
            ),
            _on_path,
        )

    def _export_config(self) -> None:
        """Export current editor content to a file."""

        def _on_path(path_str: str | None) -> None:
            if not path_str:
                return
            text = self._get_editor_text()
            dest = Path(path_str).expanduser()
            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(text, encoding="utf-8")
                self.app.notify(f"Exported to {dest}", severity="information")
            except OSError as exc:
                self.app.notify(f"Export failed: {exc}", severity="error")

        self.app.push_screen(
            _FilePathModal(
                title="Export Config",
                prompt="Enter export file path:",
                default=str(_PROJECT_ROOT / "config_export.yaml"),
            ),
            _on_path,
        )

    def _reset(self) -> None:
        """Reload from disk, discarding editor changes."""
        text = _load_config_text()
        if w := safe_query(self, "#wizard-editor-area", TextArea):
            w.load_text(text)
            self._current_path = _find_config_path()
            self._set_path_label()
            self._set_validation("[dim]Reset to saved version[/dim]")
            self.app.notify("Editor reset to saved config.", severity="information")


class _BackendBuilderPanel(Static):
    """Quick-add backend templates by filling in a few fields."""

    DEFAULT_CSS = """
    _BackendBuilderPanel {
        height: auto;
        padding: 0 1;
    }
    #bb-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    .bb-row {
        height: 3;
        margin-bottom: 0;
    }
    .bb-label {
        width: 20;
        padding-top: 1;
    }
    .bb-input {
        width: 1fr;
    }
    #bb-preview {
        height: auto;
        max-height: 10;
        margin-top: 1;
        border: round $secondary;
        padding: 0 1;
    }
    #bb-buttons {
        height: 3;
        padding-top: 1;
    }
    #bb-buttons Button {
        margin-right: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Add Backend — Quick Template[/b]", id="bb-title")
            yield Static(
                "Fill in the fields below and click 'Generate' to produce a "
                "YAML snippet. Copy it into the Config Editor tab.",
                classes="dim",
            )

            with Horizontal(classes="bb-row"):
                yield Label("Backend Name:", classes="bb-label")
                yield Input(
                    placeholder="my-server",
                    id="bb-name",
                    classes="bb-input",
                )

            with Horizontal(classes="bb-row"):
                yield Label("Type:", classes="bb-label")
                yield Select(
                    [
                        ("stdio", "stdio"),
                        ("sse", "sse"),
                        ("streamable-http", "streamable-http"),
                    ],
                    value="stdio",
                    id="bb-type",
                    allow_blank=False,
                )

            with Horizontal(classes="bb-row"):
                yield Label("Command / URL:", classes="bb-label")
                yield Input(
                    placeholder="npx -y @org/mcp-server  or  http://host:port/mcp",
                    id="bb-command",
                    classes="bb-input",
                )

            yield Label("[b]Preview:[/b]")
            yield TextArea("", language="yaml", id="bb-preview", read_only=True)

            with Horizontal(id="bb-buttons"):
                yield Button("Generate", id="btn-bb-generate", variant="primary")
                yield Button(
                    "Copy to Editor",
                    id="btn-bb-copy",
                    variant="success",
                )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-bb-generate":
            self._generate_snippet()
        elif event.button.id == "btn-bb-copy":
            self._copy_to_editor()

    def _generate_snippet(self) -> None:
        name = self._val("bb-name") or "my-server"
        btype = self._select_val("bb-type") or "stdio"
        cmd_or_url = self._val("bb-command") or ""

        if btype == "stdio":
            parts = cmd_or_url.split(None, 1) if cmd_or_url else ["python", "server.py"]
            command = parts[0]
            arg = parts[1] if len(parts) > 1 else "server.py"
            snippet = _STDIO_TEMPLATE.format(name=name, command=command, arg=arg)
        elif btype == "sse":
            url = cmd_or_url or "http://127.0.0.1:8000/mcp_sse"
            snippet = _SSE_TEMPLATE.format(name=name, url=url)
        else:  # streamable-http
            url = cmd_or_url or "http://127.0.0.1:8000/mcp"
            snippet = _HTTP_TEMPLATE.format(name=name, url=url)

        if w := safe_query(self, "#bb-preview", TextArea):
            w.load_text(snippet)

    def _copy_to_editor(self) -> None:
        """Append the generated snippet to the config editor's backends section."""
        w = safe_query(self, "#bb-preview", TextArea)
        if not w:
            return
        preview = w.text

        if not preview.strip():
            self.app.notify("Generate a snippet first.", severity="warning")
            return

        # Try to find the config editor and append
        try:
            editor_panel = self.screen.query_one(_ConfigEditorPanel)
            editor = editor_panel.query_one("#wizard-editor-area", TextArea)
            current = editor.text
            if "backends:" in current:
                # Find the backends line and append after it
                lines = current.split("\n")
                insert_idx = None
                for i, line in enumerate(lines):
                    if line.strip().startswith("backends:"):
                        insert_idx = i + 1
                        break
                if insert_idx is not None:
                    # Find the end of the backends section (next top-level key)
                    end_idx = insert_idx
                    for j in range(insert_idx, len(lines)):
                        stripped = lines[j].strip()
                        if (
                            stripped
                            and not stripped.startswith("#")
                            and not stripped.startswith(" ")
                            and ":" in stripped
                        ):
                            end_idx = j
                            break
                    else:
                        end_idx = len(lines)
                    lines.insert(end_idx, preview)
                    editor.load_text("\n".join(lines))
                else:
                    editor.load_text(current + "\n" + preview)
            else:
                editor.load_text(current + "\nbackends:\n" + preview)

            self.app.notify("Snippet added to Config Editor.", severity="information")
        except (NoMatches, AttributeError) as exc:
            self.app.notify(
                f"Could not copy — switch to Config Editor tab first. ({exc})",
                severity="warning",
            )

    def _val(self, widget_id: str) -> str:
        w = safe_query(self, f"#{widget_id}", Input)
        return w.value.strip() if w else ""

    def _select_val(self, widget_id: str) -> str:
        w = safe_query(self, f"#{widget_id}", Select)
        if not w:
            return ""
        v = w.value
        return str(v) if v is not None and v != Select.BLANK else ""


class _QuickStartPanel(Static):
    """Quick-start guides and common config snippets."""

    DEFAULT_CSS = """
    _QuickStartPanel {
        height: auto;
        padding: 1 2;
    }
    #qs-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    #qs-templates {
        height: auto;
        max-height: 12;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Quick Start Templates[/b]", id="qs-title")
            yield Static(
                "Select a template to load into the Config Editor.\n"
                "These are starting points — customize to your needs.",
            )
            yield DataTable(id="qs-templates")
            with Horizontal():
                yield Button(
                    "Load Selected",
                    id="btn-qs-load",
                    variant="primary",
                )
                yield Button(
                    "Load Minimal Config",
                    id="btn-qs-minimal",
                    variant="default",
                )
                yield Button(
                    "Load Example Config",
                    id="btn-qs-example",
                    variant="default",
                )

    def on_mount(self) -> None:
        table = safe_query(self, "#qs-templates", DataTable)
        if table:
            table.add_columns("Template", "Description", "Backends")
            table.cursor_type = "row"
            table.zebra_stripes = True

            table.add_row("Minimal", "Bare minimum config — 0 backends", "0")
            table.add_row("Example", "Full example with all sections documented", "2")
            table.add_row("Current", "Currently active config.yaml", "varies")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn = event.button.id
        if btn == "btn-qs-minimal":
            self._load_template(_MINIMAL_CONFIG, "Minimal")
        elif btn == "btn-qs-example":
            self._load_template_from_file(_PROJECT_ROOT / "example_config.yaml", "Example")
        elif btn == "btn-qs-load":
            self._load_selected()

    def _load_selected(self) -> None:
        table = safe_query(self, "#qs-templates", DataTable)
        if not table:
            return
        idx = table.cursor_row
        if idx == 0:
            self._load_template(_MINIMAL_CONFIG, "Minimal")
        elif idx == 1:
            self._load_template_from_file(_PROJECT_ROOT / "example_config.yaml", "Example")
        elif idx == 2:
            text = _load_config_text()
            self._load_template(text, "Current")

    def _load_template(self, text: str, name: str) -> None:
        try:
            editor_panel = self.screen.query_one(_ConfigEditorPanel)
            editor = editor_panel.query_one("#wizard-editor-area", TextArea)
            editor.load_text(text)
            self.app.notify(
                f"Loaded '{name}' template into editor.",
                severity="information",
            )
        except (NoMatches, AttributeError) as exc:
            self.app.notify(
                f"Switch to Config Editor tab first. ({exc})",
                severity="warning",
            )

    def _load_template_from_file(self, path: Path, name: str) -> None:
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            self._load_template(text, name)
        else:
            self.app.notify(f"File not found: {path}", severity="error")


class _FilePathModal(ModalScreen[Optional[str]]):
    """Simple modal asking the user for a file path."""

    DEFAULT_CSS = """
    _FilePathModal {
        align: center middle;
    }
    #fpm-container {
        width: 70%;
        max-width: 80;
        height: auto;
        background: $surface;
        border: round $accent;
        padding: 1 2;
    }
    #fpm-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #fpm-input {
        width: 100%;
        margin-bottom: 1;
    }
    #fpm-buttons {
        height: 3;
        align: right middle;
    }
    #fpm-buttons Button {
        margin-left: 1;
    }
    """

    def __init__(
        self,
        title: str = "File Path",
        prompt: str = "Enter path:",
        default: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._title_text = title
        self._prompt_text = prompt
        self._default = default

    def compose(self) -> ComposeResult:
        with Vertical(id="fpm-container"):
            yield Label(f"[b]{self._title_text}[/b]", id="fpm-title")
            yield Label(self._prompt_text)
            yield Input(value=self._default, id="fpm-input")
            with Horizontal(id="fpm-buttons"):
                yield Button("Cancel", id="btn-fpm-cancel", variant="default")
                yield Button("OK", id="btn-fpm-ok", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-fpm-ok":
            val = self.query_one("#fpm-input", Input).value.strip()
            self.dismiss(val if val else None)
        elif event.button.id == "btn-fpm-cancel":
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        val = event.value.strip()
        self.dismiss(val if val else None)
