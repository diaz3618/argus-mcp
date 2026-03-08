"""Runtime feature flags.

A simple ``Dict[str, bool]`` registry with sensible defaults.
Flags are loaded from the ``feature_flags`` section of the Argus
config and can be queried at runtime via :func:`is_enabled`.

Usage::

    from argus_mcp.config.flags import FeatureFlags

    flags = FeatureFlags({"optimizer": True, "hot_reload": False})
    if flags.is_enabled("optimizer"):
        ...
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# Default feature-flag values.  Features are **off** unless explicitly
# enabled in the config.
_DEFAULTS: Dict[str, bool] = {
    "optimizer": False,
    "hot_reload": True,
    "outgoing_auth": True,
    "session_management": True,
    "yaml_config": True,
    "container_isolation": True,
    "build_on_startup": True,
}


class FeatureFlags:
    """Immutable set of boolean feature flags.

    Parameters
    ----------
    overrides:
        Mapping of ``flag_name → bool`` from user config.  Unknown
        names are accepted (future-proofing); missing names fall back
        to :data:`_DEFAULTS`.
    """

    def __init__(self, overrides: Optional[Dict[str, bool]] = None) -> None:
        self._flags: Dict[str, bool] = dict(_DEFAULTS)
        if overrides:
            for key, value in overrides.items():
                if not isinstance(value, bool):
                    logger.warning(
                        "Feature flag '%s' has non-boolean value '%s' — skipping.",
                        key,
                        value,
                    )
                    continue
                self._flags[key] = value

    def is_enabled(self, name: str) -> bool:
        """Return ``True`` if the named feature is enabled.

        Unknown flag names return ``False``.
        """
        return self._flags.get(name, False)

    def all_flags(self) -> Dict[str, bool]:
        """Return a copy of all flags and their current values."""
        return dict(self._flags)

    def __repr__(self) -> str:
        enabled = [k for k, v in self._flags.items() if v]
        return f"FeatureFlags(enabled={enabled})"
