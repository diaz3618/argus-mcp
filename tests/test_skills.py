"""Tests for argus_mcp.skills — manifest parsing and skill manager lifecycle."""

from __future__ import annotations

import json
import os
from typing import Any, Dict

import pytest

from argus_mcp.skills.manager import InstalledSkill, SkillManager, SkillStatus
from argus_mcp.skills.manifest import SkillManifest, SkillManifestError

# SkillManifest ───────────────────────────────────────────────────────


class TestSkillManifest:
    """Tests for manifest parsing, validation, and serialization."""

    def test_from_dict_minimal(self) -> None:
        manifest = SkillManifest.from_dict({"name": "test-skill"})
        assert manifest.name == "test-skill"
        assert manifest.version == "0.0.0"
        assert manifest.tools == []
        assert manifest.dependencies == []

    def test_from_dict_full(self) -> None:
        data: Dict[str, Any] = {
            "name": "full-skill",
            "version": "2.1.0",
            "description": "Full skill",
            "tools": [{"name": "t1", "backend": "b1"}],
            "workflows": [{"name": "w1", "steps": []}],
            "config": {"key": "val"},
            "dependencies": ["dep-a"],
            "author": "tester",
            "license": "MIT",
        }
        manifest = SkillManifest.from_dict(data)
        assert manifest.version == "2.1.0"
        assert len(manifest.tools) == 1
        assert manifest.author == "tester"

    def test_from_dict_missing_name_raises(self) -> None:
        with pytest.raises(SkillManifestError, match="must have a 'name'"):
            SkillManifest.from_dict({"version": "1.0.0"})

    def test_to_dict_roundtrip(self) -> None:
        data: Dict[str, Any] = {
            "name": "rt",
            "version": "1.0.0",
            "description": "Roundtrip",
            "tools": [],
            "workflows": [],
            "config": {},
            "dependencies": [],
            "author": "",
            "license": "",
        }
        m = SkillManifest.from_dict(data)
        assert m.to_dict() == data

    def test_validate_ok(self) -> None:
        m = SkillManifest(name="ok", version="1.0.0")
        assert m.validate() == []

    def test_validate_missing_name(self) -> None:
        m = SkillManifest(name="", version="1.0.0")
        errors = m.validate()
        assert any("name" in e.lower() for e in errors)

    def test_validate_missing_version(self) -> None:
        m = SkillManifest(name="x", version="")
        errors = m.validate()
        assert any("version" in e.lower() for e in errors)

    def test_validate_bad_tool(self) -> None:
        m = SkillManifest(name="x", version="1", tools=["not-a-dict"])  # type: ignore[list-item]
        errors = m.validate()
        assert any("Tool 0" in e for e in errors)

    def test_from_file_valid(self, tmp_path: Any) -> None:
        p = tmp_path / "manifest.json"
        p.write_text(json.dumps({"name": "file-skill", "version": "0.1.0"}))
        m = SkillManifest.from_file(str(p))
        assert m.name == "file-skill"

    def test_from_file_not_found(self, tmp_path: Any) -> None:
        with pytest.raises(SkillManifestError, match="Failed to read"):
            SkillManifest.from_file(str(tmp_path / "nope.json"))

    def test_from_file_not_object(self, tmp_path: Any) -> None:
        p = tmp_path / "manifest.json"
        p.write_text("[]")
        with pytest.raises(SkillManifestError, match="must be a JSON object"):
            SkillManifest.from_file(str(p))


# SkillManager ────────────────────────────────────────────────────────


def _write_manifest(skill_dir: Any, name: str, **extra: Any) -> None:
    """Write a minimal manifest.json into *skill_dir*."""
    os.makedirs(skill_dir, exist_ok=True)
    data: Dict[str, Any] = {"name": name, "version": "1.0.0", **extra}
    with open(os.path.join(str(skill_dir), "manifest.json"), "w") as f:
        json.dump(data, f)


class TestSkillManager:
    """Lifecycle operations: discover, install, enable/disable, uninstall."""

    def test_discover_empty(self, tmp_path: Any) -> None:
        mgr = SkillManager(skills_dir=str(tmp_path / "empty"))
        assert mgr.discover() == []

    def test_discover_finds_skills(self, tmp_path: Any) -> None:
        skills_dir = tmp_path / "skills"
        _write_manifest(skills_dir / "alpha", "alpha")
        _write_manifest(skills_dir / "beta", "beta")
        mgr = SkillManager(skills_dir=str(skills_dir))
        found = mgr.discover()
        assert len(found) == 2
        names = {s.name for s in found}
        assert names == {"alpha", "beta"}

    def test_discover_skips_invalid(self, tmp_path: Any) -> None:
        skills_dir = tmp_path / "skills"
        _write_manifest(skills_dir / "good", "good")
        # Write an invalid manifest (not an object)
        bad_dir = skills_dir / "bad"
        os.makedirs(str(bad_dir), exist_ok=True)
        with open(str(bad_dir / "manifest.json"), "w") as f:
            f.write("[]")
        mgr = SkillManager(skills_dir=str(skills_dir))
        found = mgr.discover()
        assert len(found) == 1
        assert found[0].name == "good"

    def test_install_and_list(self, tmp_path: Any) -> None:
        skills_dir = tmp_path / "skills"
        os.makedirs(str(skills_dir))
        source = tmp_path / "src-skill"
        _write_manifest(source, "installable", description="test")

        mgr = SkillManager(skills_dir=str(skills_dir))
        skill = mgr.install(str(source))
        assert skill.name == "installable"
        assert skill.status == SkillStatus.ENABLED
        assert len(mgr.list_skills()) == 1

    def test_install_no_manifest_raises(self, tmp_path: Any) -> None:
        skills_dir = tmp_path / "skills"
        os.makedirs(str(skills_dir))
        mgr = SkillManager(skills_dir=str(skills_dir))
        with pytest.raises(SkillManifestError, match="No manifest.json"):
            mgr.install(str(tmp_path / "no-manifest"))

    def test_install_invalid_manifest_raises(self, tmp_path: Any) -> None:
        skills_dir = tmp_path / "skills"
        os.makedirs(str(skills_dir))
        source = tmp_path / "bad-skill"
        _write_manifest(source, "")  # empty name
        mgr = SkillManager(skills_dir=str(skills_dir))
        with pytest.raises(SkillManifestError, match="name"):
            mgr.install(str(source))

    def test_enable_disable(self, tmp_path: Any) -> None:
        skills_dir = tmp_path / "skills"
        _write_manifest(skills_dir / "s1", "s1")
        mgr = SkillManager(skills_dir=str(skills_dir))
        mgr.discover()

        mgr.disable("s1")
        assert mgr.get("s1").status == SkillStatus.DISABLED  # type: ignore[union-attr]
        assert mgr.list_enabled() == []

        mgr.enable("s1")
        assert mgr.get("s1").status == SkillStatus.ENABLED  # type: ignore[union-attr]
        assert len(mgr.list_enabled()) == 1

    def test_enable_nonexistent_raises(self, tmp_path: Any) -> None:
        mgr = SkillManager(skills_dir=str(tmp_path))
        with pytest.raises(ValueError, match="not installed"):
            mgr.enable("ghost")

    def test_disable_nonexistent_raises(self, tmp_path: Any) -> None:
        mgr = SkillManager(skills_dir=str(tmp_path))
        with pytest.raises(ValueError, match="not installed"):
            mgr.disable("ghost")

    def test_uninstall(self, tmp_path: Any) -> None:
        skills_dir = tmp_path / "skills"
        _write_manifest(skills_dir / "doomed", "doomed")
        mgr = SkillManager(skills_dir=str(skills_dir))
        mgr.discover()
        assert mgr.get("doomed") is not None

        mgr.uninstall("doomed")
        assert mgr.get("doomed") is None
        assert not os.path.isdir(str(skills_dir / "doomed"))

    def test_uninstall_nonexistent_raises(self, tmp_path: Any) -> None:
        mgr = SkillManager(skills_dir=str(tmp_path))
        with pytest.raises(ValueError, match="not installed"):
            mgr.uninstall("nope")

    def test_get_skill_config(self, tmp_path: Any) -> None:
        skills_dir = tmp_path / "skills"
        _write_manifest(skills_dir / "cfg", "cfg", config={"key": "value"})
        mgr = SkillManager(skills_dir=str(skills_dir))
        mgr.discover()
        assert mgr.get_skill_config("cfg") == {"key": "value"}
        assert mgr.get_skill_config("missing") == {}

    def test_get_all_tools(self, tmp_path: Any) -> None:
        skills_dir = tmp_path / "skills"
        _write_manifest(skills_dir / "t", "t", tools=[{"name": "my-tool", "backend": "srv"}])
        mgr = SkillManager(skills_dir=str(skills_dir))
        mgr.discover()
        tools = mgr.get_all_tools()
        assert len(tools) == 1
        assert tools[0]["_skill"] == "t"
        assert tools[0]["name"] == "my-tool"

    def test_get_all_workflows(self, tmp_path: Any) -> None:
        skills_dir = tmp_path / "skills"
        _write_manifest(skills_dir / "w", "w", workflows=[{"name": "wf1", "steps": []}])
        mgr = SkillManager(skills_dir=str(skills_dir))
        mgr.discover()
        wfs = mgr.get_all_workflows()
        assert len(wfs) == 1
        assert wfs[0]["_skill"] == "w"

    def test_state_persistence(self, tmp_path: Any) -> None:
        """Disabled state survives re-discover."""
        skills_dir = tmp_path / "skills"
        _write_manifest(skills_dir / "persist", "persist")

        mgr = SkillManager(skills_dir=str(skills_dir))
        mgr.discover()
        mgr.disable("persist")

        # Re-discover should pick up persisted state
        mgr2 = SkillManager(skills_dir=str(skills_dir))
        found = mgr2.discover()
        assert found[0].status == SkillStatus.DISABLED


# InstalledSkill ──────────────────────────────────────────────────────


class TestInstalledSkill:
    def test_name_property(self) -> None:
        m = SkillManifest(name="prop-test")
        s = InstalledSkill(manifest=m)
        assert s.name == "prop-test"
