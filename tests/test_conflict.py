"""Tests for argus_mcp.bridge.conflict — Conflict resolution strategies.

Covers:
- ConflictAction factory methods and attributes
- FirstWinsStrategy: transform_name passthrough, handle_conflict returns SKIP
- PrefixStrategy: transform_name adds prefix, configurable separator
- PriorityStrategy: priority ordering, unlisted servers, replace vs rename
- ErrorStrategy: raises CapabilityConflictError
- create_strategy factory: all valid strategies, unknown strategy, missing priority order
- Edge cases: empty priority lists, same-priority servers
"""

from __future__ import annotations

import pytest

from argus_mcp.bridge.conflict import (
    VALID_STRATEGIES,
    ConflictAction,
    ErrorStrategy,
    FirstWinsStrategy,
    PrefixStrategy,
    PriorityStrategy,
    create_strategy,
)
from argus_mcp.errors import CapabilityConflictError


class TestConflictAction:
    """ConflictAction value-object factory methods."""

    def test_skip(self) -> None:
        ca = ConflictAction.skip()
        assert ca.action == ConflictAction.SKIP
        assert ca.new_name is None

    def test_replace(self) -> None:
        ca = ConflictAction.replace()
        assert ca.action == ConflictAction.REPLACE
        assert ca.new_name is None

    def test_error(self) -> None:
        ca = ConflictAction.error()
        assert ca.action == ConflictAction.ERROR
        assert ca.new_name is None

    def test_rename(self) -> None:
        ca = ConflictAction.rename("new_tool")
        assert ca.action == ConflictAction.RENAME
        assert ca.new_name == "new_tool"

    def test_rename_empty_name(self) -> None:
        ca = ConflictAction.rename("")
        assert ca.action == ConflictAction.RENAME
        assert ca.new_name == ""

    def test_slots(self) -> None:
        """Verify __slots__ prevent arbitrary attribute assignment."""
        ca = ConflictAction.skip()
        assert hasattr(ca, "__slots__")
        with pytest.raises(AttributeError):
            ca.nonexistent = True  # type: ignore[attr-defined]


class TestFirstWinsStrategy:
    def test_transform_name_passthrough(self) -> None:
        s = FirstWinsStrategy()
        assert s.transform_name("server-a", "my_tool") == "my_tool"

    def test_handle_conflict_returns_skip(self) -> None:
        s = FirstWinsStrategy()
        action = s.handle_conflict("tool", "server-a", "server-b")
        assert action.action == ConflictAction.SKIP

    def test_consistent_across_calls(self) -> None:
        s = FirstWinsStrategy()
        a1 = s.handle_conflict("t1", "s1", "s2")
        a2 = s.handle_conflict("t2", "s3", "s4")
        assert a1.action == a2.action == ConflictAction.SKIP


class TestPrefixStrategy:
    def test_transform_name_adds_prefix(self) -> None:
        s = PrefixStrategy()
        assert s.transform_name("myserver", "tool") == "myserver_tool"

    def test_custom_separator(self) -> None:
        s = PrefixStrategy(separator="-")
        assert s.transform_name("srv", "echo") == "srv-echo"

    def test_empty_separator(self) -> None:
        s = PrefixStrategy(separator="")
        assert s.transform_name("srv", "tool") == "srvtool"

    def test_handle_conflict_returns_skip(self) -> None:
        """Conflicts shouldn't happen with prefix, but graceful fallback."""
        s = PrefixStrategy()
        action = s.handle_conflict("srv_tool", "srv-a", "srv-b")
        assert action.action == ConflictAction.SKIP


class TestPriorityStrategy:
    def test_higher_priority_replaces(self) -> None:
        s = PriorityStrategy(order=["high", "low"])
        action = s.handle_conflict("tool", "low", "high")
        assert action.action == ConflictAction.REPLACE

    def test_lower_priority_is_renamed(self) -> None:
        s = PriorityStrategy(order=["high", "low"])
        action = s.handle_conflict("tool", "high", "low")
        assert action.action == ConflictAction.RENAME
        assert action.new_name == "low_tool"

    def test_custom_separator_in_rename(self) -> None:
        s = PriorityStrategy(order=["h", "l"], separator="-")
        action = s.handle_conflict("tool", "h", "l")
        assert action.new_name == "l-tool"

    def test_unlisted_server_has_lowest_priority(self) -> None:
        s = PriorityStrategy(order=["listed"])
        # An unlisted server vs a listed one → listed wins
        action = s.handle_conflict("tool", "listed", "unlisted")
        assert action.action == ConflictAction.RENAME

    def test_two_unlisted_servers(self) -> None:
        """Two unlisted servers have same priority → existing wins (RENAME new)."""
        s = PriorityStrategy(order=["neither"])
        action = s.handle_conflict("tool", "a", "b")
        # Both have priority len(order)=1, equal priority → RENAME new
        assert action.action == ConflictAction.RENAME

    def test_transform_name_passthrough(self) -> None:
        s = PriorityStrategy(order=["a", "b"])
        assert s.transform_name("a", "tool") == "tool"

    def test_same_priority_existing_wins(self) -> None:
        """When priorities are equal, existing wins."""
        s = PriorityStrategy(order=["a", "b"])
        # server 'a' has priority 0, 'b' has priority 1
        action = s.handle_conflict("tool", "a", "b")
        assert action.action == ConflictAction.RENAME  # b is renamed


class TestErrorStrategy:
    def test_transform_name_passthrough(self) -> None:
        s = ErrorStrategy()
        assert s.transform_name("srv", "tool") == "tool"

    def test_raises_conflict_error(self) -> None:
        s = ErrorStrategy()
        with pytest.raises(CapabilityConflictError) as exc_info:
            s.handle_conflict("tool", "server-a", "server-b")
        assert "server-a" in str(exc_info.value)
        assert "server-b" in str(exc_info.value)


class TestCreateStrategy:
    def test_first_wins(self) -> None:
        s = create_strategy("first-wins")
        assert isinstance(s, FirstWinsStrategy)

    def test_prefix(self) -> None:
        s = create_strategy("prefix")
        assert isinstance(s, PrefixStrategy)

    def test_prefix_with_separator(self) -> None:
        s = create_strategy("prefix", separator="-")
        assert isinstance(s, PrefixStrategy)
        assert s.separator == "-"

    def test_priority(self) -> None:
        s = create_strategy("priority", priority_order=["a", "b"])
        assert isinstance(s, PriorityStrategy)

    def test_priority_missing_order_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            create_strategy("priority")

    def test_priority_empty_order_raises(self) -> None:
        with pytest.raises(ValueError, match="non-empty"):
            create_strategy("priority", priority_order=[])

    def test_error(self) -> None:
        s = create_strategy("error")
        assert isinstance(s, ErrorStrategy)

    def test_unknown_strategy_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown"):
            create_strategy("nonexistent")

    def test_valid_strategies_frozenset(self) -> None:
        assert isinstance(VALID_STRATEGIES, frozenset)
        assert "first-wins" in VALID_STRATEGIES
        assert "prefix" in VALID_STRATEGIES
        assert "priority" in VALID_STRATEGIES
        assert "error" in VALID_STRATEGIES

    def test_all_valid_strategies_constructable(self) -> None:
        """Every strategy in VALID_STRATEGIES can be created."""
        for name in VALID_STRATEGIES:
            kwargs = {}
            if name == "priority":
                kwargs["priority_order"] = ["s1"]
            s = create_strategy(name, **kwargs)
            assert s is not None
