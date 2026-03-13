"""Configurable conflict resolution strategies for capability name collisions.

When multiple backend servers expose capabilities with the same name,
these strategies determine how Argus MCP handles the collision.

Strategies:
    - **first-wins**: Keep the first registered capability; ignore duplicates.
    - **prefix**: Prefix *all* capability names with the server name,
      preventing conflicts entirely.
    - **priority**: Highest-priority server wins; unprioritised backends
      fall back to prefix.
    - **error**: Raise :class:`CapabilityConflictError` on any conflict.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from argus_mcp.errors import CapabilityConflictError

logger = logging.getLogger(__name__)


class ConflictAction:
    """Result of conflict resolution."""

    __slots__ = ("action", "new_name")

    SKIP = "skip"
    REPLACE = "replace"
    ERROR = "error"
    RENAME = "rename"

    def __init__(self, action: str, new_name: Optional[str] = None) -> None:
        self.action = action
        self.new_name = new_name

    @classmethod
    def skip(cls) -> ConflictAction:
        return cls(cls.SKIP)

    @classmethod
    def replace(cls) -> ConflictAction:
        return cls(cls.REPLACE)

    @classmethod
    def error(cls) -> ConflictAction:
        return cls(cls.ERROR)

    @classmethod
    def rename(cls, new_name: str) -> ConflictAction:
        return cls(cls.RENAME, new_name)


class ConflictStrategy(ABC):
    """Base class for conflict resolution strategies."""

    @abstractmethod
    def transform_name(self, server_name: str, original_name: str) -> str:
        """Transform a capability name before registration.

        Called for *every* capability. Prefix strategy uses this to
        prepend the server name; other strategies return the original.
        """

    @abstractmethod
    def handle_conflict(
        self,
        exposed_name: str,
        existing_server: str,
        new_server: str,
    ) -> ConflictAction:
        """Decide what to do when *exposed_name* is already registered.

        Returns a :class:`ConflictAction` indicating the resolution.
        """


class FirstWinsStrategy(ConflictStrategy):
    """Keep the first registered capability; ignore duplicates.

    This is the default strategy.
    """

    def transform_name(self, server_name: str, original_name: str) -> str:
        return original_name

    def handle_conflict(
        self,
        exposed_name: str,
        existing_server: str,
        new_server: str,
    ) -> ConflictAction:
        logger.warning(
            "Conflict: '%s' already registered by '%s'; duplicate from '%s' ignored (first-wins).",
            exposed_name,
            existing_server,
            new_server,
        )
        return ConflictAction.skip()


class PrefixStrategy(ConflictStrategy):
    """Prefix all capability names with the server name.

    Every tool becomes ``{server_name}{separator}{tool_name}``,
    eliminating any possibility of name collisions.
    """

    def __init__(self, separator: str = "_") -> None:
        self.separator = separator

    def transform_name(self, server_name: str, original_name: str) -> str:
        return f"{server_name}{self.separator}{original_name}"

    def handle_conflict(
        self,
        exposed_name: str,
        existing_server: str,
        new_server: str,
    ) -> ConflictAction:
        # Should not happen with prefix strategy, but handle gracefully.
        logger.warning(
            "Unexpected conflict with prefix strategy: '%s' "
            "(servers: '%s' vs '%s'). Skipping duplicate.",
            exposed_name,
            existing_server,
            new_server,
        )
        return ConflictAction.skip()


class PriorityStrategy(ConflictStrategy):
    """Higher-priority server wins conflicts; others are prefixed.

    Servers are ranked by a configured order list. On conflict,
    the server appearing earlier in the list wins. Servers not in
    the list have lowest priority and fall back to prefix renaming.
    """

    def __init__(
        self,
        order: List[str],
        separator: str = "_",
    ) -> None:
        self.order = order
        self.separator = separator
        # Build a priority lookup — lower index = higher priority.
        self._priority: Dict[str, int] = {name: idx for idx, name in enumerate(order)}

    def _get_priority(self, server_name: str) -> int:
        """Return priority (lower = higher). Unlisted servers get max."""
        return self._priority.get(server_name, len(self.order))

    def transform_name(self, server_name: str, original_name: str) -> str:
        return original_name

    def handle_conflict(
        self,
        exposed_name: str,
        existing_server: str,
        new_server: str,
    ) -> ConflictAction:
        existing_pri = self._get_priority(existing_server)
        new_pri = self._get_priority(new_server)

        if new_pri < existing_pri:
            # New server has higher priority — replace.
            logger.info(
                "Conflict: '%s' — server '%s' (priority %d) replaces '%s' (priority %d).",
                exposed_name,
                new_server,
                new_pri,
                existing_server,
                existing_pri,
            )
            return ConflictAction.replace()

        # Existing wins; rename the new one with a prefix.
        prefixed = f"{new_server}{self.separator}{exposed_name}"
        logger.info(
            "Conflict: '%s' won by '%s' (priority %d); '%s' renamed to '%s'.",
            exposed_name,
            existing_server,
            existing_pri,
            new_server,
            prefixed,
        )
        return ConflictAction.rename(prefixed)


class ErrorStrategy(ConflictStrategy):
    """Raise an error on any name conflict.

    This is the strictest strategy — the server refuses to start
    if any two backends expose a capability with the same name.
    """

    def transform_name(self, server_name: str, original_name: str) -> str:
        return original_name

    def handle_conflict(
        self,
        exposed_name: str,
        existing_server: str,
        new_server: str,
    ) -> ConflictAction:
        raise CapabilityConflictError(exposed_name, existing_server, new_server)


_STRATEGY_MAP = {
    "first-wins": "FirstWinsStrategy",
    "prefix": "PrefixStrategy",
    "priority": "PriorityStrategy",
    "error": "ErrorStrategy",
}

VALID_STRATEGIES = frozenset(_STRATEGY_MAP.keys())


def create_strategy(
    strategy: str = "first-wins",
    separator: str = "_",
    priority_order: Optional[List[str]] = None,
) -> ConflictStrategy:
    """Create a conflict resolution strategy from config values.

    Args:
        strategy: Strategy name (first-wins, prefix, priority, error).
        separator: Separator for prefix-based naming (default ``_``).
        priority_order: Server priority list (required for ``priority``).

    Returns:
        A :class:`ConflictStrategy` instance.

    Raises:
        ValueError: If *strategy* is unknown or *priority* is missing its order.
    """
    if strategy not in VALID_STRATEGIES:
        raise ValueError(
            f"Unknown conflict strategy '{strategy}'. Valid options: {sorted(VALID_STRATEGIES)}"
        )

    if strategy == "first-wins":
        return FirstWinsStrategy()
    if strategy == "prefix":
        return PrefixStrategy(separator=separator)
    if strategy == "priority":
        if not priority_order:
            raise ValueError("Priority strategy requires a non-empty 'order' list.")
        return PriorityStrategy(order=priority_order, separator=separator)
    if strategy == "error":
        return ErrorStrategy()

    # Should not reach here.
    return FirstWinsStrategy()
