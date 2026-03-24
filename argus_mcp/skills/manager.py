"""Skill manager — lifecycle management for installed skills.

Handles install, enable, disable, uninstall, and configuration
namespacing for skill packages.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from argus_mcp.skills.manifest import SkillManifest, SkillManifestError

logger = logging.getLogger(__name__)


class SkillStatus(Enum):
    """Status of an installed skill."""

    ENABLED = "enabled"
    DISABLED = "disabled"


@dataclass
class InstalledSkill:
    """Metadata for an installed skill."""

    manifest: SkillManifest
    status: SkillStatus = SkillStatus.ENABLED
    install_path: str = ""

    @property
    def name(self) -> str:
        return self.manifest.name


class SkillManager:
    """Manages the lifecycle of skill packages.

    Skills are stored in ``skills_dir`` with the layout::

        skills_dir/
          my-skill/
            manifest.json
            ...

    A ``skills-state.json`` file tracks enabled/disabled status.

    Parameters
    ----------
    skills_dir:
        Directory where skills are installed.
    """

    def __init__(self, skills_dir: str = "skills") -> None:
        self._skills_dir = skills_dir
        self._state_file = os.path.join(skills_dir, "skills-state.json")
        self._skills: Dict[str, InstalledSkill] = {}

    def discover(self) -> List[InstalledSkill]:
        """Scan the skills directory and load all manifests."""
        self._skills.clear()

        if not os.path.isdir(self._skills_dir):
            return []

        state = self._load_state()

        for entry in sorted(os.listdir(self._skills_dir)):
            skill_path = os.path.join(  # nosemgrep: injection-path-traversal-join
                self._skills_dir, entry
            )
            manifest_path = os.path.join(skill_path, "manifest.json")

            if not os.path.isfile(manifest_path):
                continue

            try:
                manifest = SkillManifest.from_file(manifest_path)
                status_str = state.get(manifest.name, "enabled")
                status = SkillStatus.DISABLED if status_str == "disabled" else SkillStatus.ENABLED
                skill = InstalledSkill(
                    manifest=manifest,
                    status=status,
                    install_path=skill_path,
                )
                self._skills[manifest.name] = skill
            except SkillManifestError as exc:
                logger.warning("Skipping invalid skill at %s: %s", skill_path, exc)

        logger.info("Discovered %d skill(s)", len(self._skills))
        return list(self._skills.values())

    def install(self, source_path: str) -> InstalledSkill:
        """Install a skill from a directory path.

        Copies the skill directory into ``skills_dir`` and loads the manifest.
        """
        manifest_path = os.path.join(source_path, "manifest.json")
        if not os.path.isfile(manifest_path):
            raise SkillManifestError(f"No manifest.json found at {source_path}")

        manifest = SkillManifest.from_file(manifest_path)

        errors = manifest.validate()
        if errors:
            raise SkillManifestError(f"Invalid manifest for '{manifest.name}': {'; '.join(errors)}")

        for dep in manifest.dependencies:
            if dep not in self._skills:
                logger.warning(
                    "Skill '%s' depends on '%s' which is not installed",
                    manifest.name,
                    dep,
                )

        dest = os.path.join(  # nosemgrep: injection-path-traversal-join
            self._skills_dir, manifest.name
        )
        os.makedirs(dest, exist_ok=True)
        if os.path.abspath(source_path) != os.path.abspath(dest):
            shutil.copytree(source_path, dest, dirs_exist_ok=True)

        skill = InstalledSkill(
            manifest=manifest,
            status=SkillStatus.ENABLED,
            install_path=dest,
        )
        self._skills[manifest.name] = skill
        self._save_state()

        logger.info("Skill '%s' v%s installed", manifest.name, manifest.version)
        return skill

    def uninstall(self, skill_name: str) -> None:
        """Remove an installed skill."""
        skill = self._skills.get(skill_name)
        if not skill:
            raise ValueError(f"Skill '{skill_name}' is not installed")

        if skill.install_path and os.path.isdir(skill.install_path):
            # Security: validate path is within skills directory
            real_path = os.path.realpath(skill.install_path)
            real_base = os.path.realpath(self._skills_dir)
            if not real_path.startswith(real_base + os.sep):
                raise ValueError(f"Refusing to remove '{real_path}': not within skills directory")
            shutil.rmtree(skill.install_path)

        del self._skills[skill_name]
        self._save_state()
        logger.info("Skill '%s' uninstalled", skill_name)

    def enable(self, skill_name: str) -> None:
        """Enable an installed skill."""
        skill = self._skills.get(skill_name)
        if not skill:
            raise ValueError(f"Skill '{skill_name}' is not installed")
        skill.status = SkillStatus.ENABLED
        self._save_state()
        logger.info("Skill '%s' enabled", skill_name)

    def disable(self, skill_name: str) -> None:
        """Disable an installed skill."""
        skill = self._skills.get(skill_name)
        if not skill:
            raise ValueError(f"Skill '{skill_name}' is not installed")
        skill.status = SkillStatus.DISABLED
        self._save_state()
        logger.info("Skill '%s' disabled", skill_name)

    def get(self, skill_name: str) -> Optional[InstalledSkill]:
        """Get an installed skill by name."""
        return self._skills.get(skill_name)

    def list_skills(self) -> List[InstalledSkill]:
        """Return all installed skills."""
        return list(self._skills.values())

    def list_enabled(self) -> List[InstalledSkill]:
        """Return only enabled skills."""
        return [s for s in self._skills.values() if s.status == SkillStatus.ENABLED]

    def get_skill_config(self, skill_name: str) -> Dict[str, Any]:
        """Get namespaced config for a skill."""
        skill = self._skills.get(skill_name)
        if not skill:
            return {}
        return dict(skill.manifest.config)

    def get_all_tools(self) -> List[Dict[str, Any]]:
        """Get tool definitions from all enabled skills."""
        tools: List[Dict[str, Any]] = []
        for skill in self.list_enabled():
            for tool in skill.manifest.tools:
                tool_copy = dict(tool)
                if "name" in tool_copy:
                    tool_copy["_skill"] = skill.name
                tools.append(tool_copy)
        return tools

    def get_all_workflows(self) -> List[Dict[str, Any]]:
        """Get workflow definitions from all enabled skills."""
        workflows: List[Dict[str, Any]] = []
        for skill in self.list_enabled():
            for wf in skill.manifest.workflows:
                wf_copy = dict(wf)
                wf_copy["_skill"] = skill.name
                workflows.append(wf_copy)
        return workflows

    def _load_state(self) -> Dict[str, str]:
        """Load skill state from the state file."""
        if not os.path.isfile(self._state_file):
            return {}
        try:
            with open(self._state_file, "r", encoding="utf-8") as f:
                loaded: Dict[str, str] = json.load(f)
                return loaded
        except (json.JSONDecodeError, OSError, ValueError):
            return {}

    def _save_state(self) -> None:
        """Persist skill state to the state file."""
        state = {name: skill.status.value for name, skill in self._skills.items()}
        os.makedirs(self._skills_dir, exist_ok=True)
        with open(self._state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
