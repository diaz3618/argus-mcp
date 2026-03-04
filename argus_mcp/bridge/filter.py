"""Capability filter engine with glob-pattern allow/deny lists.

Filters are applied **per-server** during capability discovery, after
conflict resolution name transforms but before aggregation.

Denied capabilities are removed from **both** the advertised list
(what clients see in ``list_tools``) **and** the route map —
``CapabilityRegistry.register()`` uses ``continue`` to skip
filtered items entirely (see ``capability_registry.py``).
"""

from __future__ import annotations

import fnmatch
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)


class CapabilityFilter:
    """Evaluate allow/deny glob patterns against capability names.

    Evaluation order (deny takes precedence over allow):

    1. If ``deny`` is set and the name matches any deny pattern → **hidden**.
    2. If ``allow`` is set and the name matches any allow pattern → **visible**.
    3. If ``allow`` is set but the name does NOT match → **hidden**.
    4. If neither ``allow`` nor ``deny`` is set → **visible** (pass-through).
    """

    def __init__(
        self,
        allow: Optional[List[str]] = None,
        deny: Optional[List[str]] = None,
    ) -> None:
        self.allow = allow or []
        self.deny = deny or []

    @property
    def is_active(self) -> bool:
        """Return True if any filter patterns are configured."""
        return bool(self.allow or self.deny)

    def is_allowed(self, name: str) -> bool:
        """Return True if *name* passes the filter."""
        # Deny overrides allow.
        if self.deny and any(fnmatch.fnmatch(name, pat) for pat in self.deny):
            return False

        # If allow list is set, name must match at least one pattern.
        if self.allow:
            return any(fnmatch.fnmatch(name, pat) for pat in self.allow)

        # No filters configured — allow everything.
        return True


def build_filter(
    allow: Optional[List[str]] = None,
    deny: Optional[List[str]] = None,
) -> CapabilityFilter:
    """Create a :class:`CapabilityFilter` from config values."""
    return CapabilityFilter(allow=allow, deny=deny)
