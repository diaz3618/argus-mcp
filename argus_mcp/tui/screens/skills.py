"""Skills management screen — browse, enable/disable, apply, and install skills.

Provides:
* Automatic skill discovery on screen show via :class:`SkillManager`
* Search bar for live filtering by name/description/category
* Detail panel with author, license, dependencies, tools, and workflows
* Apply flow that writes required backend configs and triggers hot-reload
* Enable/disable toggle and uninstall actions
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import yaml  # type: ignore[import-untyped]
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Button,
    DataTable,
    Input,
    Select,
    Static,
)

from argus_mcp._error_utils import safe_query
from argus_mcp.config.loader import find_config_file
from argus_mcp.tui.screens.base import ArgusScreen

logger = logging.getLogger(__name__)

# Default skills directory relative to where the server looks.
_DEFAULT_SKILLS_DIR = "skills"
_EXAMPLE_SKILLS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "examples",
    "skills",
)


class SkillsScreen(ArgusScreen):
    """TUI screen for managing installed skills.

    Presents a searchable/filterable table of installed skills with
    status, version, and description.  Supports enable/disable, apply
    (auto-configure backends), and uninstall.
    """

    BINDINGS = [
        ("escape", "go_back", "Back"),
        ("e", "toggle_skill", "Enable/Disable"),
        ("a", "apply_skill", "Apply"),
        ("u", "uninstall_skill", "Uninstall"),
        ("slash", "focus_search", "Search"),
    ]

    def __init__(self, skill_manager: Optional[object] = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._skills: List[Dict[str, Any]] = []
        self._all_skills: List[Dict[str, Any]] = []  # unfiltered
        self._selected_skill: str | None = None
        self._skill_manager = skill_manager  # SkillManager instance
        self._categories: List[str] = []

    def compose_content(self) -> ComposeResult:
        with Vertical(id="skills-container"):
            yield Static(
                "[b]Skills Management[/b]  •  Browse and apply skill presets",
                id="skills-title",
            )
            with Horizontal(id="skills-filter-bar"):
                yield Input(
                    placeholder="Search skills… (press /)",
                    id="skills-search",
                )
                yield Select[str](
                    [("All Categories", "all")],
                    value="all",
                    id="skills-category-select",
                    allow_blank=False,
                )
            yield Static("", id="skills-status-bar")
            yield DataTable(id="skills-table")
        with Vertical(id="detail-panel"):
            yield Static("Select a skill to view details.", id="skill-detail")
        with Horizontal(id="actions-bar"):
            yield Button("Enable/Disable", id="btn-toggle", variant="primary")
            yield Button("Apply Skill", id="btn-apply", variant="success")
            yield Button("Uninstall", id="btn-uninstall", variant="error")

    def on_mount(self) -> None:
        table = self.query_one("#skills-table", DataTable)
        table.add_columns("Name", "Version", "Status", "Tools", "Description")
        table.cursor_type = "row"

    def on_show(self) -> None:
        """Auto-discover skills when the screen becomes visible."""
        self._ensure_skill_manager()
        self._refresh_from_manager()

    # ── Skill Manager ────────────────────────────────────────────

    def _ensure_skill_manager(self) -> None:
        """Lazily create a SkillManager if none was injected."""
        if self._skill_manager is not None:
            return
        try:
            from argus_mcp.skills.manager import SkillManager

            # Try configured skills dir, then examples
            for path in (_DEFAULT_SKILLS_DIR, _EXAMPLE_SKILLS_DIR):
                if os.path.isdir(path):
                    self._skill_manager = SkillManager(skills_dir=path)
                    break
            else:
                self._skill_manager = SkillManager(skills_dir=_DEFAULT_SKILLS_DIR)
        except (ImportError, OSError) as exc:
            logger.warning("Could not create SkillManager: %s", exc)

    # ── Data Loading ─────────────────────────────────────────────

    def load_skills(self, skills: List[Dict[str, Any]]) -> None:
        """Populate the table from a list of skill dicts."""
        self._all_skills = skills
        self._skills = skills
        self._rebuild_categories()
        self._render_table(skills)

    def _render_table(self, skills: List[Dict[str, Any]]) -> None:
        """Render skills into the DataTable."""
        table = self.query_one("#skills-table", DataTable)
        table.clear()
        for s in skills:
            tools_count = len(s.get("tools", []))
            table.add_row(
                s.get("name", ""),
                s.get("version", ""),
                s.get("status", ""),
                str(tools_count),
                _trunc(s.get("description", ""), 50),
                key=s.get("name", ""),
            )
        status = f"{len(skills)} skill(s) loaded"
        if len(skills) != len(self._all_skills):
            status += f" (filtered from {len(self._all_skills)})"
        self._set_status(status)

    def _rebuild_categories(self) -> None:
        """Rebuild the category dropdown from loaded skills."""
        cats: set[str] = set()
        for s in self._all_skills:
            for dep in s.get("dependencies", []):
                cats.add(dep)
            # Use the first word of the name as a rough category
            name = s.get("name", "")
            if "-" in name:
                cats.add(name.split("-")[0])
        self._categories = sorted(cats)
        options: list[tuple[str, str]] = [("All Categories", "all")]
        for c in self._categories:
            options.append((c.title(), c))
        if sel := safe_query(self, "#skills-category-select", Select):
            sel.set_options(options)

    def _refresh_from_manager(self) -> None:
        """Reload skills list from the manager."""
        if self._skill_manager is None:
            self._set_status("No skill manager — no skills directory found")
            return
        try:
            from argus_mcp.skills.manager import SkillManager

            if isinstance(self._skill_manager, SkillManager):
                self._skill_manager.discover()
                skills: List[Dict[str, Any]] = []
                for sk in self._skill_manager.list_skills():
                    tools = sk.manifest.tools or []
                    skills.append(
                        {
                            "name": sk.name,
                            "version": sk.manifest.version,
                            "status": sk.status.value,
                            "description": sk.manifest.description,
                            "author": sk.manifest.author,
                            "license": sk.manifest.license,
                            "dependencies": sk.manifest.dependencies,
                            "tools": tools,
                            "workflows": sk.manifest.workflows,
                            "config": sk.manifest.config,
                        }
                    )
                self.load_skills(skills)
        except (ImportError, AttributeError, OSError) as exc:
            logger.error("Failed to refresh skills from manager: %s", exc)
            self._set_status(f"Error loading skills: {exc}")

    # ── Search & Filter ──────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        """Live-filter the skills table on search text change."""
        if event.input.id != "skills-search":
            return
        self._apply_filter()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Re-filter when category dropdown changes."""
        if event.select.id != "skills-category-select":
            return
        self._apply_filter()

    def _apply_filter(self) -> None:
        """Filter skills by search text and category."""
        w = safe_query(self, "#skills-search", Input)
        query = w.value.strip().lower() if w else ""
        sel = safe_query(self, "#skills-category-select", Select)
        cat = sel.value if sel else "all"

        filtered = self._all_skills
        if query:
            filtered = [
                s
                for s in filtered
                if query in s.get("name", "").lower()
                or query in s.get("description", "").lower()
                or query in s.get("author", "").lower()
            ]
        if cat and cat != "all" and cat != Select.BLANK:
            filtered = [
                s
                for s in filtered
                if cat in s.get("name", "").lower()
                or cat in [d.lower() for d in s.get("dependencies", [])]
            ]
        self._skills = filtered
        self._render_table(filtered)

    def action_focus_search(self) -> None:
        if w := safe_query(self, "#skills-search", Input):
            w.focus()

    # ── Selection & Detail ───────────────────────────────────────

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        key = str(event.row_key.value) if event.row_key else None
        self._selected_skill = key
        self._update_detail(key)

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        key = str(event.row_key.value) if event.row_key else None
        self._selected_skill = key
        self._update_detail(key)

    def _update_detail(self, skill_name: str | None) -> None:
        detail = self.query_one("#skill-detail", Static)
        if not skill_name:
            detail.update("Select a skill to view details.")
            return

        skill = next((s for s in self._all_skills if s.get("name") == skill_name), None)
        if not skill:
            detail.update(f"Skill '{skill_name}' not found.")
            return

        tools = skill.get("tools", [])
        tool_names = [t.get("name", "?") for t in tools] if tools else []
        workflows = skill.get("workflows", [])
        wf_names = [w.get("name", "?") for w in workflows] if workflows else []
        deps = skill.get("dependencies", [])

        lines = [
            f"[b]{skill.get('name', '')}[/b] v{skill.get('version', '')}",
            f"Status: {skill.get('status', '')}  |  Author: {skill.get('author', 'N/A')}  |  License: {skill.get('license', 'N/A')}",
            "",
            skill.get("description", ""),
            "",
            f"[b]Tools ({len(tools)}):[/b]  {', '.join(tool_names) or 'none'}",
        ]
        if wf_names:
            lines.append(f"[b]Workflows:[/b]  {', '.join(wf_names)}")
        if deps:
            lines.append(f"[b]Dependencies:[/b]  {', '.join(deps)}")
        if skill.get("config"):
            lines.append(f"[b]Config keys:[/b]  {', '.join(skill['config'].keys())}")
        detail.update("\n".join(lines))

    # ── Actions ──────────────────────────────────────────────────

    def action_toggle_skill(self) -> None:
        if not self._selected_skill:
            self.notify("No skill selected", severity="warning")
            return

        if self._skill_manager is not None:
            try:
                from argus_mcp.skills.manager import SkillManager, SkillStatus

                if isinstance(self._skill_manager, SkillManager):
                    skill = self._skill_manager.get(self._selected_skill)
                    if skill:
                        if skill.status == SkillStatus.ENABLED:
                            self._skill_manager.disable(self._selected_skill)
                            self.notify(f"Disabled '{self._selected_skill}'")
                        else:
                            self._skill_manager.enable(self._selected_skill)
                            self.notify(f"Enabled '{self._selected_skill}'")
                        self._refresh_from_manager()
                        return
            except (ImportError, AttributeError) as exc:
                self.notify(f"Error toggling skill: {exc}", severity="error")
                return

        self.notify(
            f"Toggle '{self._selected_skill}' requested (no manager connected)",
            severity="information",
        )

    @staticmethod
    def _collect_skill_backends(tools: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        """Extract unique backend configs from a skill's tool list."""
        backends: Dict[str, Dict[str, Any]] = {}
        for tool in tools:
            backend_name = tool.get("backend", "")
            if backend_name and backend_name not in backends:
                backends[backend_name] = {
                    "command": f"python -m {backend_name.replace('-', '_')}",
                    "transport": "stdio",
                }
        return backends

    def _apply_backends_to_config(
        self, config_path: str, backends_needed: Dict[str, Dict[str, Any]]
    ) -> tuple[List[str], List[str]]:
        """Merge *backends_needed* into the YAML config file.

        Returns ``(added, skipped)`` backend name lists.
        """
        with open(config_path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}

        backends_section: Dict[str, Any] = data.setdefault("backends", {})
        added: List[str] = []
        skipped: List[str] = []

        for name, cfg in backends_needed.items():
            if name in backends_section:
                skipped.append(name)
            else:
                backends_section[name] = cfg
                added.append(name)

        if added:
            with open(config_path, "w", encoding="utf-8") as fh:
                yaml.dump(data, fh, default_flow_style=False, sort_keys=False)

        return added, skipped

    def action_apply_skill(self) -> None:
        """Apply the selected skill — write backend configs and reload."""
        if not self._selected_skill:
            self.notify("No skill selected", severity="warning")
            return

        skill = next(
            (s for s in self._all_skills if s.get("name") == self._selected_skill),
            None,
        )
        if not skill:
            self.notify("Skill data not found", severity="error")
            return

        tools = skill.get("tools", [])
        if not tools:
            self.notify("Skill has no tools to apply", severity="information")
            return

        backends_needed = self._collect_skill_backends(tools)
        if not backends_needed:
            self.notify("No backend requirements found in skill", severity="information")
            return

        config_path = self._resolve_config_path()
        if config_path is None:
            self.notify(
                "Cannot locate config file — configure backends manually",
                severity="warning",
            )
            return

        try:
            added, skipped = self._apply_backends_to_config(config_path, backends_needed)

            msg_parts: List[str] = []
            if added:
                msg_parts.append(f"Added: {', '.join(added)}")
            if skipped:
                msg_parts.append(f"Already existed: {', '.join(skipped)}")

            self.notify(
                " | ".join(msg_parts) or "No changes needed",
                title=f"Applied '{skill.get('name', '')}'",
            )

            if added:
                self._trigger_reload()
                self._set_status(
                    f"Applied skill '{skill.get('name', '')}' — "
                    f"added {len(added)} backend(s), triggering reload…"
                )

        except (OSError, yaml.YAMLError, KeyError) as exc:
            logger.error("Failed to apply skill: %s", exc)
            self.notify(f"Apply failed: {exc}", severity="error")

    def action_uninstall_skill(self) -> None:
        if not self._selected_skill:
            self.notify("No skill selected", severity="warning")
            return

        if self._skill_manager is not None:
            try:
                from argus_mcp.skills.manager import SkillManager

                if isinstance(self._skill_manager, SkillManager):
                    self._skill_manager.uninstall(self._selected_skill)
                    self.notify(f"Uninstalled '{self._selected_skill}'")
                    self._selected_skill = None
                    self._refresh_from_manager()
                    return
            except (ImportError, AttributeError) as exc:
                self.notify(f"Error uninstalling skill: {exc}", severity="error")
                return

        self.notify(
            f"Uninstall '{self._selected_skill}' requested (no manager connected)",
            severity="warning",
        )

    def action_go_back(self) -> None:
        self.app.switch_mode("dashboard")

    # ── Button handler ───────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-toggle":
            self.action_toggle_skill()
        elif event.button.id == "btn-apply":
            self.action_apply_skill()
        elif event.button.id == "btn-uninstall":
            self.action_uninstall_skill()

    # ── Helpers ──────────────────────────────────────────────────

    def _set_status(self, text: str) -> None:
        if w := safe_query(self, "#skills-status-bar", Static):
            w.update(text)

    def _resolve_config_path(self) -> Optional[str]:
        """Find the config file path from server status or defaults."""
        app = self.app
        status = getattr(app, "_last_status", None)
        if status is not None:
            path = getattr(status.config, "file_path", None)
            if path and os.path.isfile(path):
                return path
        path = find_config_file()
        return path if os.path.isfile(path) else None

    def _trigger_reload(self) -> None:
        """Post a config reload request to the server."""
        mgr = getattr(self.app, "_server_manager", None)
        if mgr is None:
            return
        client = getattr(mgr, "active_client", None)
        if client is None:
            return

        async def _do_reload() -> None:
            try:
                result = await client.post_reload()
                if result.reloaded:
                    added = ", ".join(result.backends_added) or "none"
                    self._set_status(f"Reload complete — added: {added}")
                    self.notify("Config reloaded", title="Reload")
                else:
                    errors = "; ".join(result.errors) if result.errors else "unknown"
                    self._set_status(f"Reload failed: {errors}")
            except (OSError, AttributeError) as exc:
                logger.warning("Reload failed: %s", exc)

        self.app.run_worker(_do_reload(), exclusive=True, name="skills-reload")


def _trunc(text: str, max_len: int = 50) -> str:
    """Truncate text for table display."""
    if not text:
        return ""
    if len(text) > max_len:
        return text[: max_len - 1] + "…"
    return text
