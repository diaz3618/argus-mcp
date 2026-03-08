"""Skill manifest — parsing and validation of manifest.json.

A skill manifest defines a reusable package that bundles tools,
workflows, and configuration::

    {
        "name": "my-skill",
        "version": "1.0.0",
        "description": "My reusable skill",
        "tools": [
            {"name": "my-tool", "backend": "some-server"}
        ],
        "workflows": [
            {"name": "my-workflow", "steps": [...]}
        ],
        "config": {
            "api_key": "secret:my-skill-key"
        },
        "dependencies": ["other-skill"]
    }
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class SkillManifestError(Exception):
    """Raised when a skill manifest is invalid."""


@dataclass
class SkillManifest:
    """Parsed skill manifest.

    Attributes
    ----------
    name:
        Unique skill identifier.
    version:
        Semantic version string.
    description:
        Human-readable description.
    tools:
        Tool definitions this skill provides.
    workflows:
        Workflow definitions this skill provides.
    config:
        Default configuration for this skill (namespaced).
    dependencies:
        Other skill names this skill depends on.
    author:
        Skill author.
    license:
        License identifier.
    """

    name: str
    version: str = "0.0.0"
    description: str = ""
    tools: List[Dict[str, Any]] = field(default_factory=list)
    workflows: List[Dict[str, Any]] = field(default_factory=list)
    config: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)
    author: str = ""
    license: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SkillManifest:
        """Parse from a dict (loaded from JSON/YAML)."""
        name = data.get("name")
        if not name:
            raise SkillManifestError("Skill manifest must have a 'name' field")

        return cls(
            name=name,
            version=data.get("version", "0.0.0"),
            description=data.get("description", ""),
            tools=data.get("tools", []),
            workflows=data.get("workflows", []),
            config=data.get("config", {}),
            dependencies=data.get("dependencies", []),
            author=data.get("author", ""),
            license=data.get("license", ""),
        )

    @classmethod
    def from_file(cls, path: str) -> SkillManifest:
        """Load a manifest from a JSON file."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise SkillManifestError(f"Failed to read manifest: {path}: {exc}") from exc

        if not isinstance(data, dict):
            raise SkillManifestError(f"Manifest must be a JSON object: {path}")

        return cls.from_dict(data)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a dict."""
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "tools": self.tools,
            "workflows": self.workflows,
            "config": self.config,
            "dependencies": self.dependencies,
            "author": self.author,
            "license": self.license,
        }

    def validate(self) -> List[str]:
        """Validate the manifest and return a list of errors (empty = valid)."""
        errors: List[str] = []
        if not self.name:
            errors.append("Missing 'name'")
        if not self.version:
            errors.append("Missing 'version'")
        for i, tool in enumerate(self.tools):
            if not isinstance(tool, dict) or "name" not in tool:
                errors.append(f"Tool {i}: must be an object with 'name'")
        return errors
