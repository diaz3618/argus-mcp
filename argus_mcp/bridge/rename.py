"""Capability rename engine for per-server name and description overrides.

Renames are applied *per-server* during capability discovery, after
filtering but before conflict resolution, so that conflict strategies
see the post-rename names.

The route map stores the **original** backend name so that the router
can reverse-map renamed capabilities back to what the backend expects.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class RenameMap:
    """Per-server capability rename and description overrides.

    ``overrides`` maps *original* capability names to their replacements::

        {
            "search": {"name": "db_search", "description": "..."},
            "execute": {"name": "db_exec"}
        }
    """

    def __init__(
        self,
        overrides: Optional[Dict[str, Dict[str, str]]] = None,
    ) -> None:
        self._overrides = overrides or {}
        # Pre-computed rename lookup: original → new_name (only entries with a non-None name)
        self._forward: Dict[str, str] = {}
        for orig, cfg in self._overrides.items():
            new_name = cfg.get("name")
            if new_name is not None:
                self._forward[orig] = new_name

    @property
    def is_active(self) -> bool:
        """Return True if any overrides are configured."""
        return bool(self._overrides)

    def get_new_name(self, original_name: str) -> str:
        """Return the renamed name, or *original_name* if no rename applies."""
        return self._forward.get(original_name, original_name)

    def get_description_override(self, original_name: str) -> Optional[str]:
        """Return a description override if configured, else ``None``."""
        cfg = self._overrides.get(original_name, {})
        return cfg.get("description")

    def has_override(self, original_name: str) -> bool:
        """Return True if *original_name* has any override entries."""
        return original_name in self._overrides


def build_rename_map(
    overrides: Optional[Dict[str, Dict[str, str]]] = None,
) -> RenameMap:
    """Create a :class:`RenameMap` from config values."""
    return RenameMap(overrides=overrides)
