"""Fuzz / property-based tests for SkillsConfig and WorkflowsConfig.

Uses Hypothesis to generate randomised inputs that exercise the
``directory`` string and ``enabled`` boolean fields on both path-based
configuration models.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from argus_mcp.config.schema import SkillsConfig, WorkflowsConfig

pytestmark = [pytest.mark.fuzz]


class TestSkillsConfigFuzz:
    """Property tests for SkillsConfig fields."""

    @given(
        directory=st.text(min_size=1, max_size=200),
        enabled=st.booleans(),
    )
    @settings(max_examples=200)
    def test_valid_config_accepted(self, directory: str, enabled: bool) -> None:
        cfg = SkillsConfig(directory=directory, enabled=enabled)
        assert cfg.directory == directory
        assert cfg.enabled is enabled

    @given(directory=st.from_regex(r"[a-zA-Z0-9._-]+(/[a-zA-Z0-9._-]+)*", fullmatch=True))
    @settings(max_examples=100)
    def test_path_like_directory_accepted(self, directory: str) -> None:
        cfg = SkillsConfig(directory=directory)
        assert cfg.directory == directory


class TestWorkflowsConfigFuzz:
    """Property tests for WorkflowsConfig fields."""

    @given(
        directory=st.text(min_size=1, max_size=200),
        enabled=st.booleans(),
    )
    @settings(max_examples=200)
    def test_valid_config_accepted(self, directory: str, enabled: bool) -> None:
        cfg = WorkflowsConfig(directory=directory, enabled=enabled)
        assert cfg.directory == directory
        assert cfg.enabled is enabled

    @given(directory=st.from_regex(r"[a-zA-Z0-9._-]+(/[a-zA-Z0-9._-]+)*", fullmatch=True))
    @settings(max_examples=100)
    def test_path_like_directory_accepted(self, directory: str) -> None:
        cfg = WorkflowsConfig(directory=directory)
        assert cfg.directory == directory
