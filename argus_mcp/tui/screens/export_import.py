"""Export / Import TUI workflow — dry-run preview then commit.

Wraps the ``export_config`` and ``import_config`` functions in
a Textual screen with filter controls, dry-run preview tables, and a
commit confirmation step.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.widgets import (
    Button,
    DataTable,
    Label,
    Select,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)

from argus_mcp.config.export import ExportFilter, ExportResult, SecretHandling, export_config
from argus_mcp.config.import_handler import (
    ConflictStrategy,
    ImportResult,
    import_config,
    parse_import_payload,
)
from argus_mcp.config.loader import find_config_file, load_argus_config
from argus_mcp.tui.screens.base import ArgusScreen

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path.home() / ".config" / "argus-mcp"


class ExportImportScreen(ArgusScreen):
    """Dual-tab screen for config export and import with dry-run previews."""

    BINDINGS = [
        ("e", "focus_export", "Export Tab"),
        ("i", "focus_import", "Import Tab"),
        ("escape", "go_back", "Back"),
    ]

    def compose_content(self) -> ComposeResult:
        with TabbedContent(id="ei-tabs"):
            with TabPane("Export", id="tab-export"):
                yield _ExportPanel(id="export-panel")
            with TabPane("Import", id="tab-import"):
                yield _ImportPanel(id="import-panel")

    def action_focus_export(self) -> None:
        try:
            self.query_one("#ei-tabs", TabbedContent).active = "tab-export"
        except NoMatches:
            pass

    def action_focus_import(self) -> None:
        try:
            self.query_one("#ei-tabs", TabbedContent).active = "tab-import"
        except NoMatches:
            pass

    def action_go_back(self) -> None:
        self.app.switch_mode("dashboard")


class _ExportPanel(Static):
    """Export config to YAML with filtering and secret handling."""

    DEFAULT_CSS = """
    _ExportPanel { height: 1fr; padding: 0 1; }
    """

    def compose(self) -> ComposeResult:
        yield Static("[b]Export Configuration[/b]", classes="panel-heading")
        with Horizontal(id="export-filter-bar"):
            yield Label("Secrets:")
            yield Select(
                [
                    ("Mask", SecretHandling.MASK.value),
                    ("Strip", SecretHandling.STRIP.value),
                    ("Preserve", SecretHandling.PRESERVE.value),
                ],
                value=SecretHandling.MASK.value,
                id="export-secret-mode",
                allow_blank=False,
            )
            yield Label("Entities:")
            yield Select(
                [
                    ("All", "all"),
                    ("Backends only", "backends"),
                    ("Registries only", "registries"),
                ],
                value="all",
                id="export-entity-filter",
                allow_blank=False,
            )
            yield Button("Preview", id="btn-export-preview", variant="primary")
            yield Button("Save YAML", id="btn-export-save", variant="success")

        yield DataTable(id="export-preview-table")
        yield TextArea("", id="export-yaml-output", language="yaml", read_only=True)

    def on_mount(self) -> None:
        try:
            table = self.query_one("#export-preview-table", DataTable)
            table.add_columns("Entity", "Name", "Type", "Groups")
            table.cursor_type = "row"
        except NoMatches:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-export-preview":
            self._run_export_preview()
        elif event.button.id == "btn-export-save":
            self._save_export()

    def _load_config(self) -> Any:
        """Load the current ArgusConfig from disk."""
        try:
            path = find_config_file()
            return load_argus_config(path)
        except Exception as exc:
            self.app.notify(f"Cannot load config: {exc}", severity="error", timeout=5)
            return None

    def _get_secret_handling(self) -> SecretHandling:
        try:
            val = self.query_one("#export-secret-mode", Select).value
            return SecretHandling(val)
        except (NoMatches, ValueError):
            return SecretHandling.MASK

    def _get_export_filter(self) -> ExportFilter | None:
        try:
            val = self.query_one("#export-entity-filter", Select).value
            if val == "all":
                return None
            return ExportFilter(entity_types={val})
        except NoMatches:
            return None

    def _run_export_preview(self) -> None:
        """Run export and populate preview table + YAML."""
        config = self._load_config()
        if config is None:
            return

        result: ExportResult = export_config(
            config,
            secret_handling=self._get_secret_handling(),
            export_filter=self._get_export_filter(),
        )

        try:
            table = self.query_one("#export-preview-table", DataTable)
            table.clear()
            data = result.data

            for name, backend in data.get("backends", {}).items():
                btype = backend.get("type", "?")
                groups = ", ".join(backend.get("groups", []))
                table.add_row("backend", name, btype, groups)

            for name in data.get("registries", {}):
                table.add_row("registry", name, "—", "—")

            for name in data.get("feature_flags", {}):
                table.add_row("feature_flag", name, "—", "—")

            for name in data.get("plugins", {}):
                table.add_row("plugin", name, "—", "—")
        except NoMatches:
            pass

        try:
            yaml_text = yaml.dump(result.data, default_flow_style=False, sort_keys=False)
            self.query_one("#export-yaml-output", TextArea).load_text(yaml_text)
        except NoMatches:
            pass

        self._last_result = result
        self.app.notify(
            f"Export preview: {result.entity_counts}",
            timeout=3,
        )

    def _save_export(self) -> None:
        """Save exported YAML to disk."""
        result = getattr(self, "_last_result", None)
        if result is None:
            self.app.notify("Run Preview first", severity="warning", timeout=3)
            return

        try:
            out = _CONFIG_DIR / "export.yaml"
            out.parent.mkdir(parents=True, exist_ok=True)
            yaml_text = yaml.dump(result.data, default_flow_style=False, sort_keys=False)
            out.write_text(yaml_text)
            self.app.notify(f"Exported → {out}", timeout=4)
        except OSError as exc:
            self.app.notify(f"Save failed: {exc}", severity="error", timeout=5)


class _ImportPanel(Static):
    """Import config from YAML with dry-run preview and conflict strategy."""

    DEFAULT_CSS = """
    _ImportPanel { height: 1fr; padding: 0 1; }
    """

    def compose(self) -> ComposeResult:
        yield Static("[b]Import Configuration[/b]", classes="panel-heading")
        with Horizontal(id="import-control-bar"):
            yield Label("Conflict:")
            yield Select(
                [
                    ("Skip existing", ConflictStrategy.SKIP.value),
                    ("Update existing", ConflictStrategy.UPDATE.value),
                    ("Rename", ConflictStrategy.RENAME.value),
                    ("Fail on conflict", ConflictStrategy.FAIL.value),
                ],
                value=ConflictStrategy.SKIP.value,
                id="import-conflict-strategy",
                allow_blank=False,
            )
            yield Button("Dry Run", id="btn-import-dryrun", variant="warning")
            yield Button("Commit", id="btn-import-commit", variant="success")

        yield Static("Paste or edit YAML below:", classes="panel-label")
        yield TextArea("", id="import-yaml-input", language="yaml")
        yield Static("[b]Dry-Run Results:[/b]", id="import-results-heading")
        yield DataTable(id="import-results-table")

    def on_mount(self) -> None:
        try:
            table = self.query_one("#import-results-table", DataTable)
            table.add_columns("Name", "Entity", "Status", "New Name")
            table.cursor_type = "row"
        except NoMatches:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-import-dryrun":
            self._run_dry_run()
        elif event.button.id == "btn-import-commit":
            self._run_commit()

    def _get_conflict_strategy(self) -> ConflictStrategy:
        try:
            val = self.query_one("#import-conflict-strategy", Select).value
            return ConflictStrategy(val)
        except (NoMatches, ValueError):
            return ConflictStrategy.SKIP

    def _get_yaml_text(self) -> str:
        try:
            return self.query_one("#import-yaml-input", TextArea).text
        except NoMatches:
            return ""

    def _load_config(self) -> Any:
        try:
            path = find_config_file()
            return load_argus_config(path)
        except Exception as exc:
            self.app.notify(f"Cannot load config: {exc}", severity="error", timeout=5)
            return None

    def _populate_results(self, result: ImportResult) -> None:
        """Fill the results table from an ImportResult."""
        try:
            table = self.query_one("#import-results-table", DataTable)
            table.clear()
            for item in result.items:
                status_display = item.status.value
                if item.status.value == "added":
                    status_display = "[green]added[/green]"
                elif item.status.value == "updated":
                    status_display = "[yellow]updated[/yellow]"
                elif item.status.value == "skipped":
                    status_display = "[dim]skipped[/dim]"
                elif item.status.value == "failed":
                    status_display = "[red]FAILED[/red]"
                table.add_row(
                    item.name,
                    item.entity_type,
                    status_display,
                    item.new_name or "—",
                )
        except NoMatches:
            pass

        summary = result.summary()
        self.app.notify(f"Import: {summary}", timeout=4)

    def _run_dry_run(self) -> None:
        """Parse YAML and run import in dry_run mode."""
        raw = self._get_yaml_text()
        if not raw.strip():
            self.app.notify("Paste YAML to import first", severity="warning", timeout=3)
            return

        config = self._load_config()
        if config is None:
            return

        try:
            payload = parse_import_payload(raw)
        except Exception as exc:
            self.app.notify(f"YAML parse error: {exc}", severity="error", timeout=5)
            return

        result = import_config(
            config,
            payload,
            conflict_strategy=self._get_conflict_strategy(),
            dry_run=True,
        )
        self._populate_results(result)

    def _run_commit(self) -> None:
        """Parse YAML, run import with dry_run=False, and save config."""
        raw = self._get_yaml_text()
        if not raw.strip():
            self.app.notify("Paste YAML to import first", severity="warning", timeout=3)
            return

        config = self._load_config()
        if config is None:
            return

        try:
            payload = parse_import_payload(raw)
        except Exception as exc:
            self.app.notify(f"YAML parse error: {exc}", severity="error", timeout=5)
            return

        result = import_config(
            config,
            payload,
            conflict_strategy=self._get_conflict_strategy(),
            dry_run=False,
        )
        self._populate_results(result)

        if result.failed_count > 0:
            self.app.notify(
                f"{result.failed_count} items failed — config NOT saved",
                severity="error",
                timeout=5,
            )
            return

        # Persist updated config to disk
        try:
            path = find_config_file()
            cfg_dict = config.model_dump(exclude_none=True, exclude_defaults=False)
            yaml_text = yaml.dump(cfg_dict, default_flow_style=False, sort_keys=False)
            Path(path).write_text(yaml_text)
            self.app.notify(f"Config saved → {path}", timeout=4)
        except OSError as exc:
            self.app.notify(f"Save failed: {exc}", severity="error", timeout=5)
