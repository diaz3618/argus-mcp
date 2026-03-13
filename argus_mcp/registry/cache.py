"""Local JSON cache for registry data.

Stores fetched ``ServerEntry`` objects so the TUI can work offline
or when the registry is temporarily unreachable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from argus_mcp.registry.models import ServerEntry

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_DIR = os.path.realpath(
    os.path.join(
        os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")),
        "argus-mcp",
        "registry",
    )
)


class RegistryCache:
    """File-backed JSON cache for :class:`ServerEntry` lists.

    Each registry URL is stored as a separate JSON file identified
    by a sanitised version of its URL.

    Parameters
    ----------
    cache_dir:
        Directory for cache files.  Created on first write.
    ttl:
        Cache time-to-live in seconds.  After expiry, cached data
        is still returned but ``is_fresh`` returns ``False``.
    """

    def __init__(
        self,
        cache_dir: str = _DEFAULT_CACHE_DIR,
        ttl: float = 300.0,
    ) -> None:
        self._cache_dir = os.path.realpath(cache_dir)
        self._ttl = ttl

    def get(self, registry_url: str) -> Optional[List[ServerEntry]]:
        """Return cached entries for *registry_url* or ``None``."""
        path = self._path_for(registry_url)
        payload = self._read(path)
        if payload is None:
            return None
        raw_entries = payload.get("entries", [])
        return [ServerEntry.from_dict(e) for e in raw_entries]

    def put(self, registry_url: str, entries: List[ServerEntry]) -> None:
        """Write *entries* to the cache."""
        os.makedirs(self._cache_dir, exist_ok=True)
        payload: Dict[str, Any] = {
            "registry_url": registry_url,
            "fetched_at": time.time(),
            "entries": [_entry_to_dict(e) for e in entries],
        }
        path = self._path_for(registry_url)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            logger.debug("Registry cache written: %s (%d entries)", path, len(entries))
        except OSError as exc:
            logger.warning("Failed to write registry cache: %s", exc)

    def is_fresh(self, registry_url: str) -> bool:
        """Return ``True`` if the cached data is within the TTL."""
        path = self._path_for(registry_url)
        payload = self._read(path)
        if payload is None:
            return False
        fetched_at = payload.get("fetched_at", 0)
        return bool((time.time() - fetched_at) < self._ttl)

    def clear(self, registry_url: Optional[str] = None) -> None:
        """Remove cache for a specific URL or all caches."""
        if registry_url:
            path = self._path_for(registry_url)
            if os.path.exists(path):
                os.unlink(path)
        else:
            resolved_dir = os.path.realpath(self._cache_dir)
            if os.path.isdir(resolved_dir):
                for fname in os.listdir(resolved_dir):
                    fp = os.path.realpath(os.path.join(resolved_dir, fname))
                    # Guard against symlinks escaping cache directory
                    if not fp.startswith(resolved_dir + os.sep):
                        continue
                    if os.path.isfile(fp) and fp.endswith(".json"):
                        os.unlink(fp)

    def _path_for(self, registry_url: str) -> str:
        # Use SHA-256 hash to eliminate injection, length, and encoding issues
        safe_name = hashlib.sha256(registry_url.encode()).hexdigest()
        base_dir = Path(self._cache_dir).resolve()
        target_path = (base_dir / f"{safe_name}.json").resolve()
        if not target_path.is_relative_to(base_dir):
            raise ValueError("Cache path escapes cache directory")
        return str(target_path)

    def _read(self, path: str) -> Optional[Dict[str, Any]]:
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                result: Dict[str, Any] = json.load(fh)
                return result
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Corrupt registry cache file %s: %s", path, exc)
            return None


def _entry_to_dict(entry: ServerEntry) -> Dict[str, Any]:
    """Serialise a :class:`ServerEntry` to a plain dict for JSON."""
    return {
        "name": entry.name,
        "description": entry.description,
        "transport": entry.transport,
        "url": entry.url,
        "command": entry.command,
        "args": list(entry.args),
        "version": entry.version,
        "icon_url": entry.icon_url,
        "categories": list(entry.categories),
        "tools": [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in entry.tools
        ],
        **entry.extra,
    }
