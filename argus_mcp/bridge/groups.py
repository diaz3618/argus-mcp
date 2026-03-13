"""Server group manager for organizing backends into named collections.

Groups are logical labels derived from the ``group`` field in each
backend's configuration.  The :class:`GroupManager` provides helpers for
listing servers by group, iterating groups, and performing batch
operations on group members.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any, Dict, FrozenSet, List

logger = logging.getLogger(__name__)

# Argus value used when a backend has no explicit group.
DEFAULT_GROUP = "default"


class GroupManager:
    """Track server → group mappings and expose group-level helpers.

    Constructed once from the validated config and shared by
    :class:`~argus_mcp.runtime.service.ArgusService`.

    Parameters
    ----------
    backends:
        Mapping of ``{server_name: backend_config}`` where each config
        has an optional ``.group`` attribute (defaults to ``"default"``).
    """

    def __init__(self, backends: Dict[str, Any]) -> None:
        # server_name → group_name
        self._server_group: Dict[str, str] = {}
        # group_name → set of server_names
        self._group_servers: Dict[str, set[str]] = defaultdict(set)

        for name, cfg in backends.items():
            group = getattr(cfg, "group", DEFAULT_GROUP) or DEFAULT_GROUP
            self._server_group[name] = group
            self._group_servers[group].add(name)

    @property
    def groups(self) -> List[str]:
        """Return sorted list of group names."""
        return sorted(self._group_servers.keys())

    @property
    def group_count(self) -> int:
        """Number of distinct groups."""
        return len(self._group_servers)

    def group_of(self, server_name: str) -> str:
        """Return the group a server belongs to (or DEFAULT_GROUP)."""
        return self._server_group.get(server_name, DEFAULT_GROUP)

    def servers_in(self, group: str) -> FrozenSet[str]:
        """Return set of server names in the given group."""
        return frozenset(self._group_servers.get(group, set()))

    def all_servers(self) -> FrozenSet[str]:
        """Return all known server names."""
        return frozenset(self._server_group.keys())

    def group_summary(self) -> Dict[str, List[str]]:
        """Return ``{group: [server_names]}`` for all groups, sorted."""
        return {g: sorted(self._group_servers[g]) for g in self.groups}

    def add_server(self, server_name: str, group: str = DEFAULT_GROUP) -> None:
        """Register a new server ↔ group mapping."""
        old_group = self._server_group.get(server_name)
        if old_group is not None and old_group != group:
            self._group_servers[old_group].discard(server_name)
            if not self._group_servers[old_group]:
                del self._group_servers[old_group]
        self._server_group[server_name] = group
        self._group_servers[group].add(server_name)

    def remove_server(self, server_name: str) -> None:
        """Remove a server from its group."""
        group = self._server_group.pop(server_name, None)
        if group is not None:
            self._group_servers[group].discard(server_name)
            if not self._group_servers[group]:
                del self._group_servers[group]

    def to_dict(self) -> Dict[str, Any]:
        """Serialise for management API responses."""
        return {
            "groups": {
                g: {
                    "servers": sorted(members),
                    "count": len(members),
                }
                for g, members in sorted(self._group_servers.items())
            },
            "total_groups": self.group_count,
            "total_servers": len(self._server_group),
        }
