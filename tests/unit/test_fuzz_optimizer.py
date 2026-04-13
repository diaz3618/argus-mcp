"""Fuzz / property-based tests for OptimizerConfig.

Uses Hypothesis to generate randomised inputs that exercise the
``enabled`` boolean and ``keep_tools`` list fields on OptimizerConfig.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from argus_mcp.config.schema import OptimizerConfig

pytestmark = [pytest.mark.fuzz]


class TestOptimizerConfigFuzz:
    """Property tests for OptimizerConfig fields."""

    @given(
        enabled=st.booleans(),
        keep_tools=st.lists(st.text(min_size=1, max_size=50), max_size=20),
    )
    @settings(max_examples=200)
    def test_valid_config_accepted(self, enabled: bool, keep_tools: list[str]) -> None:
        cfg = OptimizerConfig(enabled=enabled, keep_tools=keep_tools)
        assert cfg.enabled is enabled
        assert cfg.keep_tools == keep_tools

    @given(keep_tools=st.lists(st.text(max_size=100), max_size=50))
    @settings(max_examples=100)
    def test_keep_tools_accepts_arbitrary_strings(self, keep_tools: list[str]) -> None:
        cfg = OptimizerConfig(keep_tools=keep_tools)
        assert len(cfg.keep_tools) == len(keep_tools)

    @given(enabled=st.sampled_from([[], {}, "maybe", "truthy", 0.5, [1], {"k": "v"}]))
    @settings(max_examples=30)
    def test_invalid_enabled_type_rejected(self, enabled: object) -> None:
        """Pydantic bool coercion accepts 'yes'/'no'/int — only truly invalid types should raise."""
        with pytest.raises(ValidationError):
            OptimizerConfig(enabled=enabled)
