"""Integration tests for config wiring (Phase 1 → Phase 2).

Verifies that SkillManager, registry, and workflow discovery are
properly wired to the full ArgusConfig model.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

from argus_mcp.config.loader import load_argus_config
from argus_mcp.config.schema import ArgusConfig
from argus_mcp.skills.manager import SkillManager


class TestSkillsConfigWiring:
    """SkillManager reads directory from config."""

    def test_skills_from_config_directory(self, tmp_path: Path) -> None:
        """SkillManager discovers skills when given a directory containing manifests."""
        skill_dir = tmp_path / "my-skills" / "test-skill"
        skill_dir.mkdir(parents=True)
        manifest = {
            "name": "test-skill",
            "version": "1.0.0",
            "description": "A test skill",
            "tools": [],
        }
        (skill_dir / "manifest.json").write_text(
            __import__("json").dumps(manifest), encoding="utf-8"
        )

        mgr = SkillManager(skills_dir=str(tmp_path / "my-skills"))
        mgr.discover()
        skills = mgr.list_skills()
        assert len(skills) >= 1
        names = [s["name"] if isinstance(s, dict) else s.manifest.name for s in skills]
        assert "test-skill" in names

    def test_skills_default_directory(self) -> None:
        """Default skills directory is 'skills'."""
        cfg = ArgusConfig()
        assert cfg.skills.directory == "skills"
        assert cfg.skills.enabled is True

    def test_skills_config_from_yaml(self, tmp_path: Path) -> None:
        """ArgusConfig parses skills section from YAML."""
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(
            textwrap.dedent("""\
                version: "1"
                skills:
                  directory: "examples/skills"
                  enabled: true
                backends: {}
            """),
            encoding="utf-8",
        )
        cfg = load_argus_config(str(config_yaml))
        assert cfg.skills.directory == "examples/skills"
        assert cfg.skills.enabled is True

    def test_examples_skills_discoverable(self) -> None:
        """examples/skills/ directory has at least one valid skill."""
        examples_dir = os.path.join(os.path.dirname(__file__), "..", "examples", "skills")
        if not os.path.isdir(examples_dir):
            pytest.skip("examples/skills not present")
        mgr = SkillManager(skills_dir=examples_dir)
        mgr.discover()
        skills = mgr.list_skills()
        assert len(skills) >= 1, "examples/skills should contain at least one skill"


class TestRegistryConfigWiring:
    """Registry configuration reaches full_config.registries."""

    def test_registries_from_yaml(self, tmp_path: Path) -> None:
        """ArgusConfig parses registries section from YAML."""
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(
            textwrap.dedent("""\
                version: "1"
                registries:
                  - name: glama
                    url: https://glama.ai/api/mcp-servers
                    type: glama
                backends: {}
            """),
            encoding="utf-8",
        )
        cfg = load_argus_config(str(config_yaml))
        assert len(cfg.registries) == 1
        assert cfg.registries[0].name == "glama"
        assert cfg.registries[0].url == "https://glama.ai/api/mcp-servers"

    def test_empty_registries_default(self) -> None:
        """Default ArgusConfig has empty registries list."""
        cfg = ArgusConfig()
        assert cfg.registries == []


class TestWorkflowsConfigWiring:
    """Workflow discovery reads config directory."""

    def test_workflows_config_from_yaml(self, tmp_path: Path) -> None:
        """ArgusConfig parses workflows section from YAML."""
        config_yaml = tmp_path / "config.yaml"
        config_yaml.write_text(
            textwrap.dedent("""\
                version: "1"
                workflows:
                  directory: "custom/workflows"
                  enabled: true
                backends: {}
            """),
            encoding="utf-8",
        )
        cfg = load_argus_config(str(config_yaml))
        assert cfg.workflows.directory == "custom/workflows"
        assert cfg.workflows.enabled is True

    def test_workflow_yaml_discovery(self) -> None:
        """examples/workflows/ contains discoverable YAML workflow files."""
        from argus_mcp.server.lifespan import _discover_workflow_yamls

        # Discovery with the examples/workflows directory included
        wfs = _discover_workflow_yamls(extra_dirs=("examples/workflows",))
        names = [w.get("name", "") for w in wfs]
        assert "data-pipeline" in names, (
            f"Expected 'data-pipeline' in discovered workflows, got: {names}"
        )

    def test_workflow_discovery_deduplicates(self) -> None:
        """Duplicate directories in scan list are de-duplicated."""
        from argus_mcp.server.lifespan import _discover_workflow_yamls

        wfs1 = _discover_workflow_yamls(extra_dirs=("examples/workflows",))
        wfs2 = _discover_workflow_yamls(extra_dirs=("examples/workflows", "examples/workflows"))
        assert len(wfs1) == len(wfs2), "Duplicate dirs should not produce duplicate results"
