"""Configuration diff utilities.

Extracts config-comparison logic so it can be shared between the
manual ``reload()`` path and the automatic file-watcher path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Set

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfigDiff:
    """Describes the difference between two backend configuration snapshots."""

    added: Set[str] = field(default_factory=set)
    removed: Set[str] = field(default_factory=set)
    changed: Set[str] = field(default_factory=set)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.removed or self.changed)

    def summary(self) -> str:
        return f"+{len(self.added)} -{len(self.removed)} ~{len(self.changed)}"


def _stdio_configs_differ(old: Dict[str, Any], new: Dict[str, Any]) -> bool:
    """Compare two stdio-type backend configs."""
    old_params = old.get("params")
    new_params = new.get("params")
    if old_params is None or new_params is None:
        return old_params is not new_params
    return (
        getattr(old_params, "command", None) != getattr(new_params, "command", None)
        or getattr(old_params, "args", []) != getattr(new_params, "args", [])
        or getattr(old_params, "env", None) != getattr(new_params, "env", None)
    )


def _sse_configs_differ(old: Dict[str, Any], new: Dict[str, Any]) -> bool:
    """Compare two SSE-type backend configs."""
    return (
        old.get("url") != new.get("url")
        or old.get("command") != new.get("command")
        or old.get("args") != new.get("args")
        or old.get("env") != new.get("env")
        or old.get("headers") != new.get("headers")
        or old.get("auth") != new.get("auth")
    )


def _streamable_configs_differ(old: Dict[str, Any], new: Dict[str, Any]) -> bool:
    """Compare two streamable-http-type backend configs."""
    return (
        old.get("url") != new.get("url")
        or old.get("headers") != new.get("headers")
        or old.get("auth") != new.get("auth")
    )


def configs_differ(old: Dict[str, Any], new: Dict[str, Any]) -> bool:
    """Compare two individual backend config dicts.

    Handles non-serializable ``StdioServerParameters`` objects and
    falls back to dict equality for other fields.
    """
    if old.get("type") != new.get("type"):
        return True

    svr_type = old.get("type")

    if svr_type == "stdio":
        return _stdio_configs_differ(old, new)

    if svr_type == "sse":
        return _sse_configs_differ(old, new)

    if svr_type == "streamable-http":
        return _streamable_configs_differ(old, new)

    return False


def compute_diff(
    old_config: Dict[str, Dict[str, Any]],
    new_config: Dict[str, Dict[str, Any]],
) -> ConfigDiff:
    """Compute the difference between two full backend configurations.

    Parameters
    ----------
    old_config:
        Previous backend config dict (``name → backend_dict``).
    new_config:
        New backend config dict.

    Returns
    -------
    ConfigDiff:
        Sets of added, removed, and changed backend names.
    """
    old_names = set(old_config)
    new_names = set(new_config)

    added = new_names - old_names
    removed = old_names - new_names
    changed: Set[str] = set()

    for name in old_names & new_names:
        if configs_differ(old_config[name], new_config[name]):
            changed.add(name)

    return ConfigDiff(added=added, removed=removed, changed=changed)
