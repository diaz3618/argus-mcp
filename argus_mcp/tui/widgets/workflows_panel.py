"""Composite workflows widget — multi-step tool chain builder and viewer.

Displays registered composite workflows (multi-step tool chains),
their execution status, a simple builder interface, and a live
output log that streams step-by-step progress during execution.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Button, DataTable, Label, RichLog, Static, TextArea

from argus_mcp._error_utils import safe_query

logger = logging.getLogger(__name__)

_YAML_EXTS = (".yaml", ".yml")
_SEARCH_DIRS = ("workflows", "examples/workflows")

_NEW_WORKFLOW_TEMPLATE = """\
name: my-workflow
description: Describe what this workflow does

inputs:
  param1:
    type: string
    description: First parameter

steps:
  - id: step-1
    tool: backend.tool_name
    description: First step
    args:
      key: "${inputs.param1}"

  - id: step-2
    tool: backend.another_tool
    description: Second step (depends on step-1)
    depends_on: [step-1]
    args:
      data: "${step-1.output}"

output: "${step-2.output}"
"""


def _discover_yaml_workflows() -> List[Dict[str, Any]]:
    """Scan known directories for workflow YAML files and return parsed dicts."""
    results: List[Dict[str, Any]] = []
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        logger.debug("pyyaml not installed — skipping YAML workflow discovery")
        return results

    for rel_dir in _SEARCH_DIRS:
        d = Path(rel_dir)
        if not d.is_dir():
            # Also check relative to project root (two levels up from this file)
            d = Path(__file__).resolve().parents[3] / rel_dir
        if not d.is_dir():
            continue
        for fpath in sorted(d.iterdir()):
            if fpath.suffix in _YAML_EXTS and fpath.is_file():
                try:
                    data = yaml.safe_load(fpath.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and data.get("name"):
                        data.setdefault("_source", str(fpath))
                        results.append(data)
                except (yaml.YAMLError, OSError):
                    logger.debug("Failed to parse workflow YAML: %s", fpath, exc_info=True)
    return results


def _discover_skill_workflows() -> List[Dict[str, Any]]:
    """Try to load workflow definitions from the SkillManager."""
    try:
        from argus_mcp.skills import SkillManager

        for search in ("skills", "examples/skills"):
            p = Path(search)
            if not p.is_dir():
                p = Path(__file__).resolve().parents[3] / search
            if p.is_dir():
                mgr = SkillManager(skills_dir=str(p))
                mgr.discover()
                return mgr.get_all_workflows()
    except (ImportError, OSError, ValueError):
        logger.debug("Skill workflow discovery failed", exc_info=True)
    return []


class WorkflowsPanel(Widget):
    """Composite workflows display and management widget."""

    DEFAULT_CSS = """
    WorkflowsPanel {
        height: auto;
        max-height: 30;
        border: round $accent;
        padding: 0 1;
    }
    #wf-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 0;
    }
    #wf-status {
        height: 1;
        color: $text-muted;
    }
    #wf-table {
        height: auto;
        max-height: 8;
    }
    #wf-detail {
        height: auto;
        max-height: 4;
        padding: 0 1;
        margin-top: 1;
    }
    #wf-actions-bar {
        height: 3;
        padding: 0 1;
    }
    #wf-actions-bar Button {
        margin-right: 1;
    }
    #wf-output-log {
        height: auto;
        max-height: 10;
        border: round $secondary;
        margin-top: 1;
        padding: 0 1;
    }
    #wf-output-title {
        text-style: bold;
        color: $secondary;
        margin-bottom: 0;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._workflows: List[Dict[str, Any]] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Composite Workflows[/b]", id="wf-title")
            yield Static("Workflows: 0  │  Running: 0  │  Completed: 0", id="wf-status")
            yield DataTable(id="wf-table")
            yield Static("Select a workflow to see details", id="wf-detail")
            with Horizontal(id="wf-actions-bar"):
                yield Button("New Workflow", id="btn-wf-new", variant="primary")
                yield Button("Run", id="btn-wf-run", variant="success")
                yield Button("Delete", id="btn-wf-delete", variant="error")
            yield Label("[b]Execution Output[/b]", id="wf-output-title")
            yield RichLog(
                highlight=True,
                markup=True,
                wrap=True,
                auto_scroll=True,
                id="wf-output-log",
            )

    def on_mount(self) -> None:
        table = safe_query(self, "#wf-table", DataTable)
        if table:
            table.add_columns("Name", "Steps", "Last Run", "Status")
            table.cursor_type = "row"
            table.zebra_stripes = True

        # Auto-discover workflows from YAML files and skills
        self.call_later(self._load_discovered_workflows)

    def _load_discovered_workflows(self) -> None:
        """Discover and load workflows from all known sources."""
        all_wf: List[Dict[str, Any]] = []
        all_wf.extend(_discover_yaml_workflows())
        all_wf.extend(_discover_skill_workflows())

        # Deduplicate by name (YAML takes precedence)
        seen: set[str] = set()
        deduped: List[Dict[str, Any]] = []
        for wf in all_wf:
            name = wf.get("name", "")
            if name and name not in seen:
                seen.add(name)
                deduped.append(wf)
        if deduped:
            self.update_workflows(deduped)

    def update_workflows(self, workflows: List[Dict[str, Any]]) -> None:
        """Refresh the workflows table."""
        self._workflows = workflows
        table = safe_query(self, "#wf-table", DataTable)
        if not table:
            return
        table.clear()

        running = 0
        completed = 0

        for wf in workflows:
            name = wf.get("name", "?")
            steps = wf.get("steps", [])
            step_count = len(steps) if isinstance(steps, list) else steps
            last_run = wf.get("last_run", "—")
            status = wf.get("status", "idle")

            if status == "running":
                running += 1
                status_display = "[green]⟳ running[/green]"
            elif status == "completed":
                completed += 1
                status_display = "[green]✓ completed[/green]"
            elif status == "failed":
                status_display = "[red]✕ failed[/red]"
            else:
                status_display = "[dim]idle[/dim]"

            if isinstance(last_run, str) and "T" in last_run:
                last_run = last_run.split("T")[1][:8]

            table.add_row(name, str(step_count), str(last_run), status_display)

        summary = f"Workflows: {len(workflows)}  │  Running: {running}  │  Completed: {completed}"
        if status_w := safe_query(self, "#wf-status", Static):
            status_w.update(summary)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Show workflow detail when a row is selected."""
        idx = event.cursor_row
        if not (0 <= idx < len(self._workflows)):
            return
        wf = self._workflows[idx]
        steps = wf.get("steps", [])
        name = wf.get("name", "?")
        description = wf.get("description", "")

        lines = [f"[b]{name}[/b]"]
        if description:
            lines.append(f"  {description}")
        lines.append("")
        for i, step in enumerate(steps, 1):
            if isinstance(step, dict):
                tool = step.get("tool", "?")
                server = step.get("server", step.get("backend", "?"))
                lines.append(f"  {i}. {tool} → {server}")
            else:
                lines.append(f"  {i}. {step}")

        if detail := safe_query(self, "#wf-detail", Static):
            detail.update("\n".join(lines))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle New / Run / Delete button presses."""
        btn_id = event.button.id
        if btn_id == "btn-wf-new":
            self._action_new_workflow()
        elif btn_id == "btn-wf-run":
            self._action_run_workflow()
        elif btn_id == "btn-wf-delete":
            self._action_delete_workflow()

    def _log_output(self, text: str | Text) -> None:
        """Write a line to the execution output log."""
        if log_widget := safe_query(self, "#wf-output-log", RichLog):
            log_widget.write(text)

    def _log_step(
        self,
        step_id: str,
        message: str,
        *,
        style: str = "bold",
        prefix: str = "►",
    ) -> None:
        """Write a formatted step entry to the execution output log."""
        ts = datetime.now().strftime("%H:%M:%S")
        line = Text.assemble(
            (f"[{ts}] ", "dim"),
            (f"{prefix} ", style),
            (f"{step_id}: ", "bold"),
            (message, ""),
        )
        self._log_output(line)

    def _log_header(self, text: str) -> None:
        """Write a section header to the output log."""
        self._log_output(Text(f"{'─' * 50}", style="dim"))
        self._log_output(Text(text, style="bold bright_cyan"))
        self._log_output(Text(f"{'─' * 50}", style="dim"))

    def _action_new_workflow(self) -> None:
        """Open the workflow editor modal with a starter template."""

        def _on_save(yaml_text: str | None) -> None:
            if yaml_text is None:
                return
            self._save_and_reload(yaml_text)

        self.app.push_screen(WorkflowEditorModal(yaml_text=_NEW_WORKFLOW_TEMPLATE), _on_save)

    def _save_and_reload(self, yaml_text: str) -> None:
        """Validate, save the YAML to disk, and refresh the table."""
        try:
            import yaml  # type: ignore[import-untyped]

            data = yaml.safe_load(yaml_text)
            if not isinstance(data, dict) or not data.get("name"):
                self.app.notify("Invalid workflow: must have a 'name' field.", severity="error")
                return

            # Validate the DAG structure
            from argus_mcp.workflows.dsl import WorkflowValidationError, parse_workflow

            try:
                parse_workflow(data)
            except WorkflowValidationError as exc:
                self.app.notify(f"Validation failed: {exc}", severity="error")
                return

            # Write to the first writable search directory
            save_dir = Path(_SEARCH_DIRS[0])
            if not save_dir.is_dir():
                save_dir = Path(__file__).resolve().parents[3] / _SEARCH_DIRS[0]
            save_dir.mkdir(parents=True, exist_ok=True)

            safe_name = data["name"].replace(" ", "-").lower()
            dest = save_dir / f"{safe_name}.yaml"
            dest.write_text(yaml_text, encoding="utf-8")

            self.app.notify(f"Workflow saved: {dest.name}", severity="information")
            self._load_discovered_workflows()

        except (OSError, yaml.YAMLError) as exc:
            logger.debug("Failed to save workflow", exc_info=True)
            self.app.notify(f"Save failed: {exc}", severity="error")

    def _get_selected_index(self) -> Optional[int]:
        """Return the currently highlighted row index, or None."""
        table = safe_query(self, "#wf-table", DataTable)
        if table:
            idx = table.cursor_row
            if 0 <= idx < len(self._workflows):
                return idx
        return None

    def _action_run_workflow(self) -> None:
        """Execute the selected workflow in a background worker with live output."""
        idx = self._get_selected_index()
        if idx is None:
            self.app.notify("Select a workflow first.", severity="warning")
            return

        wf_data = self._workflows[idx]
        name = wf_data.get("name", "?")
        self.app.notify(f"Running workflow '{name}'…")

        # Clear previous output
        if log_widget := safe_query(self, "#wf-output-log", RichLog):
            log_widget.clear()

        panel = self  # capture for closure

        async def _run() -> None:
            import time

            from argus_mcp.workflows.dsl import parse_workflow
            from argus_mcp.workflows.executor import WorkflowExecutor

            wf = parse_workflow(wf_data)
            steps = wf.steps

            panel._log_header(f"Workflow: {name}")
            panel._log_output(
                Text(
                    f"  Steps: {len(steps)}  |  Mode: dry-run  |  "
                    f"Started: {datetime.now().strftime('%H:%M:%S')}",
                    style="dim",
                )
            )
            panel._log_output(Text(""))

            # Build a logging invoker that reports each step to the output panel
            call_count = 0

            async def _logging_invoke(tool_name: str, arguments: dict) -> Any:
                """Invoker that logs to the output panel and returns a dry-run result."""
                nonlocal call_count
                call_count += 1
                panel._log_step(
                    tool_name,
                    f"Calling with {len(arguments)} arg(s)…",
                    prefix="⚡",
                    style="bright_yellow",
                )
                # Show arguments (truncated)
                for k, v in arguments.items():
                    val_str = str(v)
                    if len(val_str) > 80:
                        val_str = val_str[:77] + "…"
                    panel._log_output(Text(f"    {k}: {val_str}", style="dim"))

                # Simulate a brief delay for visual feedback
                await asyncio.sleep(0.1)

                result = {
                    "status": "ok",
                    "note": "TUI dry-run (no server context)",
                    "_tool": tool_name,
                    "_call": call_count,
                }
                panel._log_step(
                    tool_name,
                    "Returned (dry-run) ✓",
                    prefix="✓",
                    style="green",
                )
                return result

            import asyncio  # noqa: F811

            executor = WorkflowExecutor(_logging_invoke)

            panel._log_output(Text(""))
            panel._log_step("executor", "Starting execution…", prefix="▶", style="bright_cyan")

            start_time = time.monotonic()
            try:
                results = await executor.execute(wf, inputs={})
            except (RuntimeError, ValueError, OSError) as exc:
                panel._log_step(
                    "executor",
                    f"FAILED: {exc}",
                    prefix="✕",
                    style="red",
                )
                self.app.notify(f"Workflow '{name}' failed: {exc}", severity="error")
                wf_data["status"] = "failed"
                wf_data["last_run"] = datetime.now(timezone.utc).isoformat()
                self.update_workflows(self._workflows)
                return

            elapsed = (time.monotonic() - start_time) * 1000

            # Summary
            panel._log_output(Text(""))
            panel._log_header(f"Results — {name}")

            completed = failed = skipped = 0
            for step_id, res in results.items():
                status = res.status.value
                dur = f" ({res.duration_ms:.0f}ms)" if res.duration_ms else ""
                if status == "completed":
                    completed += 1
                    panel._log_step(step_id, f"completed{dur}", prefix="✓", style="green")
                elif status == "failed":
                    failed += 1
                    err = res.error or "unknown"
                    panel._log_step(step_id, f"FAILED: {err}{dur}", prefix="✕", style="red")
                elif status == "skipped":
                    skipped += 1
                    panel._log_step(step_id, "skipped", prefix="⊘", style="dim")
                else:
                    panel._log_step(step_id, f"{status}{dur}", prefix="?", style="yellow")

            panel._log_output(Text(""))
            panel._log_output(
                Text(
                    f"  Total: {len(results)} steps  |  "
                    f"✓ {completed}  ✕ {failed}  ⊘ {skipped}  |  "
                    f"{elapsed:.0f}ms",
                    style="bold",
                )
            )

            severity = "information" if failed == 0 else "warning"
            self.app.notify(
                f"Workflow '{name}' finished — {completed} ok, {failed} failed, {skipped} skipped",
                severity=severity,
            )

            # Mark in the table
            wf_data["status"] = "completed" if failed == 0 else "failed"
            wf_data["last_run"] = datetime.now(timezone.utc).isoformat()
            self.update_workflows(self._workflows)

        self.app.run_worker(_run(), name=f"wf-run-{name}", exclusive=True)

    def _action_delete_workflow(self) -> None:
        """Remove the selected workflow (from memory; optionally from disk)."""
        idx = self._get_selected_index()
        if idx is None:
            self.app.notify("Select a workflow first.", severity="warning")
            return

        wf = self._workflows[idx]
        name = wf.get("name", "?")

        # Remove the backing YAML file if it exists
        source = wf.get("_source", "")
        if source:
            try:
                p = Path(source)
                if p.is_file():
                    p.unlink()
                    logger.info("Deleted workflow file: %s", p)
            except OSError:
                logger.debug("Could not delete source file: %s", source, exc_info=True)

        self._workflows.pop(idx)
        self.update_workflows(self._workflows)
        self.app.notify(f"Workflow '{name}' removed.", severity="information")


class WorkflowEditorModal(ModalScreen[Optional[str]]):
    """Full-screen YAML editor for creating / editing a workflow."""

    DEFAULT_CSS = """
    WorkflowEditorModal {
        align: center middle;
    }
    #wf-editor-container {
        width: 80%;
        max-width: 100;
        height: 80%;
        background: $surface;
        border: round $accent;
        padding: 1 2;
    }
    #wf-editor-title {
        text-style: bold;
        margin-bottom: 1;
    }
    #wf-yaml-editor {
        height: 1fr;
    }
    #wf-editor-buttons {
        height: 3;
        align: right middle;
        padding-top: 1;
    }
    #wf-editor-buttons Button {
        margin-left: 1;
    }
    """

    def __init__(self, yaml_text: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._initial_yaml = yaml_text

    def compose(self) -> ComposeResult:
        with Vertical(id="wf-editor-container"):
            yield Label("[b]Workflow Editor[/b]  (YAML)", id="wf-editor-title")
            yield TextArea(self._initial_yaml, language="yaml", id="wf-yaml-editor")
            with Horizontal(id="wf-editor-buttons"):
                yield Button("Cancel", id="btn-wf-cancel", variant="default")
                yield Button("Save", id="btn-wf-save", variant="primary")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-wf-save":
            editor = self.query_one("#wf-yaml-editor", TextArea)
            self.dismiss(editor.text)
        elif event.button.id == "btn-wf-cancel":
            self.dismiss(None)
