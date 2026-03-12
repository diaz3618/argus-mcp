"""Runtime feature flags.

A ``Dict[str, bool]`` registry with sensible defaults and governance
metadata.  Flags are loaded from the ``feature_flags`` section of the
Argus config and can be queried at runtime via
:meth:`FeatureFlags.is_enabled`.

Each registered flag carries:

* **default** – whether the flag is on or off out-of-the-box.
* **risk** – ``"high"`` flags are default-disabled and require an
  explicit opt-in in the user's config.  ``"low"`` flags are safe to
  enable by default.
* **description** – human-readable purpose shown in ``--show-flags``
  and the TUI settings screen.

Usage::

    from argus_mcp.config.flags import FeatureFlags

    flags = FeatureFlags({"optimizer": True, "hot_reload": False})
    if flags.is_enabled("optimizer"):
        ...
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FlagSpec:
    """Metadata for a single feature flag."""

    default: bool
    risk: str  # "high" or "low"
    description: str


# ------------------------------------------------------------------
# Flag registry
# ------------------------------------------------------------------
# Convention:
#   • risk="high"  → default MUST be False (enforced in _validate_registry)
#   • risk="low"   → default may be True or False
# ------------------------------------------------------------------
FLAG_REGISTRY: Dict[str, FlagSpec] = {
    "optimizer": FlagSpec(
        default=False,
        risk="high",
        description="Experimental prompt/request optimizer. May alter tool payloads.",
    ),
    "hot_reload": FlagSpec(
        default=True,
        risk="low",
        description="Watch config file for changes and reload backends automatically.",
    ),
    "outgoing_auth": FlagSpec(
        default=True,
        risk="low",
        description="Attach OAuth/API-key headers to outgoing backend requests.",
    ),
    "session_management": FlagSpec(
        default=True,
        risk="low",
        description="Enable per-client session tracking and lifecycle management.",
    ),
    "yaml_config": FlagSpec(
        default=True,
        risk="low",
        description="Load configuration from YAML file (config.yaml).",
    ),
    "container_isolation": FlagSpec(
        default=True,
        risk="low",
        description="Run stdio backends inside isolated containers when available.",
    ),
    "build_on_startup": FlagSpec(
        default=True,
        risk="low",
        description="Pre-build container images for stdio backends at server startup.",
    ),
}

_DEFAULTS: Dict[str, bool] = {k: v.default for k, v in FLAG_REGISTRY.items()}


def _validate_registry() -> None:
    """Verify governance invariants at import time."""
    for name, spec in FLAG_REGISTRY.items():
        if spec.risk == "high" and spec.default is True:
            raise AssertionError(f"High-risk flag '{name}' must default to False, got True")
        if spec.risk not in ("high", "low"):
            raise AssertionError(f"Flag '{name}' has invalid risk level '{spec.risk}'")


_validate_registry()


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

    def describe(self, name: str) -> Optional[FlagSpec]:
        """Return the :class:`FlagSpec` for *name*, or ``None``."""
        return FLAG_REGISTRY.get(name)

    def __repr__(self) -> str:
        enabled = [k for k, v in self._flags.items() if v]
        return f"FeatureFlags(enabled={enabled})"
