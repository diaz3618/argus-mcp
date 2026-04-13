"""Fuzz / property-based tests for ConflictResolutionConfig.

Uses Hypothesis to generate randomised inputs that exercise the
``strategy`` Literal constraint, ``separator`` string field, and
``order`` list field on ConflictResolutionConfig.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from argus_mcp.config.schema import ConflictResolutionConfig

pytestmark = [pytest.mark.fuzz]

_valid_strategies = st.sampled_from(["first-wins", "prefix", "priority", "error"])


class TestConflictResolutionConfigFuzz:
    """Property tests for ConflictResolutionConfig fields."""

    @given(
        strategy=_valid_strategies,
        separator=st.text(min_size=1, max_size=10),
        order=st.lists(st.text(min_size=1, max_size=30), max_size=10),
    )
    @settings(max_examples=200)
    def test_valid_strategy_values_accepted(
        self, strategy: str, separator: str, order: list[str]
    ) -> None:
        cfg = ConflictResolutionConfig(strategy=strategy, separator=separator, order=order)
        assert cfg.strategy in {"first-wins", "prefix", "priority", "error"}
        assert cfg.separator == separator
        assert cfg.order == order

    @given(
        strategy=st.text(min_size=1, max_size=50).filter(
            lambda s: s not in {"first-wins", "prefix", "priority", "error"}
        )
    )
    @settings(max_examples=100)
    def test_invalid_strategy_rejected(self, strategy: str) -> None:
        with pytest.raises(ValidationError):
            ConflictResolutionConfig(strategy=strategy)

    @given(separator=st.text(max_size=50))
    @settings(max_examples=100)
    def test_arbitrary_separator_accepted(self, separator: str) -> None:
        cfg = ConflictResolutionConfig(separator=separator)
        assert cfg.separator == separator

    @given(order=st.lists(st.text(max_size=50), max_size=20))
    @settings(max_examples=100)
    def test_arbitrary_order_list_accepted(self, order: list[str]) -> None:
        cfg = ConflictResolutionConfig(order=order)
        assert cfg.order == order
