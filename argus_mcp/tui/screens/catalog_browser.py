"""Catalog Browser TUI — parse, stage, and commit catalog entries.

Wraps the Phase 4 ``parse_catalog``, ``stage_catalog``, and
``commit_catalog`` functions in a Textual screen with a YAML editor,
dry-run preview table, and a commit confirmation step.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, List

import yaml
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.widgets import (
    Button,
    Checkbox,
    DataTable,
    Static,
    TextArea,
)

from argus_mcp.config.loader import find_config_file, load_argus_config
from argus_mcp.registry.catalog import (
    CatalogEntry,
    CatalogEntryStatus,
    CatalogResult,
    commit_catalog,
    parse_catalog,
    stage_catalog,
)
from argus_mcp.tui.screens.base import ArgusScreen

logger = logging.getLogger(__name__)

_EXAMPLE_CATALOG = """\
# Example catalog — paste or edit your entries below
servers:
  - name: example-server
    transport: stdio
    command: npx
    args: ["-y", "@example/mcp-server"]
    description: An example MCP server
    groups: [example]
"""


class CatalogBrowserScreen(ArgusScreen):
    """Parse YAML catalogs, preview staged entries, and commit them to config."""

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("s", "stage", "Stage"),
        ("c", "commit", "Commit"),
    ]

    def compose_content(self) -> ComposeResult:
        yield Static("[b]Catalog Browser[/b]  — Batch server onboarding", classes="panel-heading")
        with Horizontal(id="catalog-control-bar"):
            yield Checkbox("Skip existing", id="catalog-skip-existing", value=True)
            yield Button("Parse & Stage", id="btn-catalog-stage", variant="warning")
            yield Button("Commit", id="btn-catalog-commit", variant="success")
            yield Button("Load Example", id="btn-catalog-example", variant="default")

        yield Static("Paste YAML catalog below:", classes="panel-label")
        yield TextArea("", id="catalog-yaml-input", language="yaml")
        yield Static("[b]Staged Results:[/b]", id="catalog-results-heading")
        yield DataTable(id="catalog-results-table")
        with Horizontal(id="catalog-status-bar"):
            yield Static("", id="catalog-stats")

    def on_mount(self) -> None:
        try:
            table = self.query_one("#catalog-results-table", DataTable)
            table.add_columns("Name", "Transport", "Status", "Error")
            table.cursor_type = "row"
        except NoMatches:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-catalog-stage":
            self._run_stage()
        elif event.button.id == "btn-catalog-commit":
            self._run_commit()
        elif event.button.id == "btn-catalog-example":
            self._load_example()

    def action_go_back(self) -> None:
        self.app.switch_mode("dashboard")

    def action_stage(self) -> None:
        self._run_stage()

    def action_commit(self) -> None:
        self._run_commit()

    def _load_config(self) -> Any:
        try:
            path = find_config_file()
            return load_argus_config(path)
        except Exception as exc:
            self.app.notify(f"Cannot load config: {exc}", severity="error", timeout=5)
            return None

    def _get_yaml_text(self) -> str:
        try:
            return self.query_one("#catalog-yaml-input", TextArea).text
        except NoMatches:
            return ""

    def _get_skip_existing(self) -> bool:
        try:
            return self.query_one("#catalog-skip-existing", Checkbox).value
        except NoMatches:
            return True

    def _populate_results(self, result: CatalogResult) -> None:
        try:
            table = self.query_one("#catalog-results-table", DataTable)
            table.clear()
            for item in result.items:
                status_display = item.status.value
                if item.status == CatalogEntryStatus.STAGED:
                    status_display = "[cyan]staged[/cyan]"
                elif item.status == CatalogEntryStatus.ADDED:
                    status_display = "[green]added[/green]"
                elif item.status == CatalogEntryStatus.SKIPPED:
                    status_display = "[dim]skipped[/dim]"
                elif item.status == CatalogEntryStatus.FAILED:
                    status_display = "[red]FAILED[/red]"
                elif item.status == CatalogEntryStatus.HEALTH_OK:
                    status_display = "[green]health ok[/green]"
                elif item.status == CatalogEntryStatus.HEALTH_FAILED:
                    status_display = "[yellow]health fail[/yellow]"
                table.add_row(
                    item.name,
                    item.backend_type or "—",
                    status_display,
                    item.error or "—",
                )
        except NoMatches:
            pass

        try:
            self.query_one("#catalog-stats", Static).update(result.summary())
        except NoMatches:
            pass

    def _load_example(self) -> None:
        try:
            self.query_one("#catalog-yaml-input", TextArea).load_text(_EXAMPLE_CATALOG)
            self.app.notify("Example catalog loaded", timeout=2)
        except NoMatches:
            pass

    def _run_stage(self) -> None:
        """Parse YAML and run stage_catalog (dry-run preview)."""
        raw = self._get_yaml_text()
        if not raw.strip():
            self.app.notify("Paste a YAML catalog first", severity="warning", timeout=3)
            return

        config = self._load_config()
        if config is None:
            return

        try:
            entries: List[CatalogEntry] = parse_catalog(raw)
        except Exception as exc:
            self.app.notify(f"Parse error: {exc}", severity="error", timeout=5)
            return

        result: CatalogResult = stage_catalog(
            entries,
            config,
            skip_existing=self._get_skip_existing(),
        )
        self._last_entries = entries
        self._populate_results(result)
        self.app.notify(f"Staged: {result.summary()}", timeout=3)

    def _run_commit(self) -> None:
        """Run commit_catalog and persist config to disk."""
        entries = getattr(self, "_last_entries", None)
        if not entries:
            self.app.notify("Run Stage first", severity="warning", timeout=3)
            return

        config = self._load_config()
        if config is None:
            return

        result: CatalogResult = commit_catalog(
            entries,
            config,
            skip_existing=self._get_skip_existing(),
        )
        self._populate_results(result)

        if result.failed_count > 0:
            self.app.notify(
                f"{result.failed_count} entries failed — config NOT saved",
                severity="error",
                timeout=5,
            )
            return

        # Persist updated config
        try:
            path = find_config_file()
            cfg_dict = config.model_dump(exclude_none=True, exclude_defaults=False)
            yaml_text = yaml.dump(cfg_dict, default_flow_style=False, sort_keys=False)
            Path(path).write_text(yaml_text)
            self.app.notify(f"Config saved → {path}", timeout=4)
        except OSError as exc:
            self.app.notify(f"Save failed: {exc}", severity="error", timeout=5)
