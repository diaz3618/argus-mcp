"""Multi-server connection manager for the Argus MCP TUI.

Manages a named collection of Argus server connections, persists them
to ``~/.config/argus-mcp/servers.json``, and tracks which server is
currently *active* (i.e. being polled and displayed).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from argus_mcp.tui.api_client import ApiClient

logger = logging.getLogger(__name__)

_CONFIG_DIR = os.path.realpath(
    os.path.join(
        os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
        "argus-mcp",
    )
)
_SERVERS_FILE = os.path.join(_CONFIG_DIR, "servers.json")


@dataclass
class ServerEntry:
    """A single named server connection."""

    name: str
    url: str
    token: Optional[str] = None
    client: Optional[ApiClient] = field(default=None, repr=False)
    connected: bool = False


class ServerManager:
    """Manages multiple named Argus server connections.

    Responsibilities
    ----------------
    * Load / save the server list from ``servers.json``.
    * Create and own one :class:`ApiClient` per entry.
    * Track which server is *active* (the one the TUI currently displays).
    * Provide helpers for connecting, disconnecting, add/remove.

    The manager does **not** own any polling logic — that belongs to the
    TUI app.  It simply provides the ``active_client`` property so the
    app's poll loop can call ``get_status()``, etc.
    """

    def __init__(self, config_path: Optional[str] = None) -> None:
        self._config_path = os.path.realpath(config_path or _SERVERS_FILE)
        self._servers: Dict[str, ServerEntry] = {}
        self._active_name: Optional[str] = None

    @property
    def active_name(self) -> Optional[str]:
        """Name of the currently active server, or ``None``."""
        return self._active_name

    @property
    def active_entry(self) -> Optional[ServerEntry]:
        """Return the active :class:`ServerEntry`, or ``None``."""
        if self._active_name and self._active_name in self._servers:
            return self._servers[self._active_name]
        return None

    @property
    def active_client(self) -> Optional[ApiClient]:
        """Return the :class:`ApiClient` for the active server (if connected)."""
        entry = self.active_entry
        if entry is not None and entry.connected and entry.client is not None:
            return entry.client
        return None

    @property
    def entries(self) -> Dict[str, ServerEntry]:
        """All server entries keyed by name (read-only view)."""
        return dict(self._servers)

    @property
    def names(self) -> List[str]:
        """Sorted list of server names."""
        return sorted(self._servers.keys())

    @property
    def count(self) -> int:
        return len(self._servers)

    def add(
        self,
        name: str,
        url: str,
        token: Optional[str] = None,
        *,
        set_active: bool = False,
    ) -> ServerEntry:
        """Add a server (overwrites if *name* already exists).

        If ``set_active`` is *True* or this is the first entry, the new
        server becomes the active one.
        """
        url = url.rstrip("/")
        entry = ServerEntry(name=name, url=url, token=token)
        self._servers[name] = entry

        if set_active or self._active_name is None:
            self._active_name = name

        logger.info("Server '%s' added (%s)", name, url)
        return entry

    def remove(self, name: str) -> None:
        """Remove a server by name (disconnects first if needed)."""
        if name not in self._servers:
            raise KeyError(f"No server named '{name}'")

        entry = self._servers.pop(name)
        if entry.client is not None:
            logger.debug(
                "Client for '%s' will be orphaned — call close_all() or disconnect() first", name
            )

        if self._active_name == name:
            self._active_name = next(iter(self._servers), None)

        logger.info("Server '%s' removed", name)

    def set_active(self, name: str) -> None:
        """Set the active server by name."""
        if name not in self._servers:
            raise KeyError(f"No server named '{name}'")
        self._active_name = name
        logger.info("Active server set to '%s'", name)

    async def connect(self, name: str) -> None:
        """Create and connect the :class:`ApiClient` for *name*."""
        if name not in self._servers:
            raise KeyError(f"No server named '{name}'")

        entry = self._servers[name]
        if entry.client is not None and entry.connected:
            return  # already connected

        client = ApiClient(base_url=entry.url, token=entry.token)
        await client.connect()
        entry.client = client
        entry.connected = True
        logger.info("Connected to server '%s' at %s", name, entry.url)

    async def disconnect(self, name: str) -> None:
        """Disconnect and close the client for *name*."""
        if name not in self._servers:
            return

        entry = self._servers[name]
        if entry.client is not None:
            try:
                await entry.client.close()
            except (OSError, ConnectionError):
                logger.debug("Error closing client for '%s'", name, exc_info=True)

        entry.client = None
        entry.connected = False
        logger.info("Disconnected from server '%s'", name)

    async def connect_all(self) -> Dict[str, Optional[Exception]]:
        """Connect all servers.  Returns a dict of name → error (None = OK)."""
        results: Dict[str, Optional[Exception]] = {}
        for name in list(self._servers):
            try:
                await self.connect(name)
                results[name] = None
            except (OSError, ConnectionError) as exc:
                logger.warning("Failed to connect to '%s': %s", name, exc)
                results[name] = exc
        return results

    async def close_all(self) -> None:
        """Disconnect every server."""
        for name in list(self._servers):
            await self.disconnect(name)

    def close_all_sync(self) -> None:
        """Best-effort synchronous cleanup of httpx clients.

        Used during Textual shutdown when the async event loop is being
        torn down and ``run_worker`` can no longer schedule coroutines.
        """
        for entry in self._servers.values():
            if entry.client is not None and hasattr(entry.client, "_client"):
                client = entry.client._client  # noqa: SLF001
                if client is not None and not client.is_closed:
                    try:
                        client.close()
                    except Exception:  # noqa: BLE001
                        pass
            entry.client = None
            entry.connected = False

    def mark_disconnected(self, name: str) -> None:
        """Mark a server as disconnected without closing the client.

        Used when a poll fails — the client object stays alive for retry.
        """
        if name in self._servers:
            self._servers[name].connected = False

    def mark_connected(self, name: str) -> None:
        """Mark a server as connected (e.g. after a successful retry)."""
        if name in self._servers:
            self._servers[name].connected = True

    def load(self) -> None:
        """Load the server list from ``servers.json``.

        Missing or corrupt files are silently ignored (manager starts
        empty).
        """
        try:
            with open(self._config_path, encoding="utf-8") as fh:
                data: Dict[str, Any] = json.load(fh)
        except FileNotFoundError:
            logger.debug("No servers.json found at %s — starting empty", self._config_path)
            return
        except (json.JSONDecodeError, ValueError, KeyError, TypeError):
            logger.warning("Could not read servers.json, starting empty", exc_info=True)
            return

        servers_list: List[Dict[str, Any]] = data.get("servers", [])
        for srv in servers_list:
            name = srv.get("name", "")
            url = srv.get("url", "")
            if not name or not url:
                continue
            token = srv.get("token")
            self._servers[name] = ServerEntry(name=name, url=url, token=token)

        active = data.get("active")
        if active and active in self._servers:
            self._active_name = active
        elif self._servers:
            self._active_name = next(iter(self._servers))

        logger.info(
            "Loaded %d server(s) from %s (active: %s)",
            len(self._servers),
            self._config_path,
            self._active_name,
        )

    def save(self) -> None:
        """Persist the server list to ``servers.json``."""
        servers_list = [
            {
                "name": e.name,
                "url": e.url,
                **({"token": e.token} if e.token else {}),
            }
            for e in self._servers.values()
        ]
        data = {
            "servers": servers_list,
            "active": self._active_name,
        }
        try:
            os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
            with open(self._config_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2)
            logger.debug("Saved %d server(s) to %s", len(servers_list), self._config_path)
        except OSError:
            logger.warning("Could not save servers.json", exc_info=True)

    @classmethod
    def from_single(
        cls,
        *,
        name: str = "default",
        url: str,
        token: Optional[str] = None,
        config_path: Optional[str] = None,
    ) -> "ServerManager":
        """Create a manager with a single, immediately-active server.

        This is the typical path when the user passes ``--server URL``.
        """
        mgr = cls(config_path=config_path)
        mgr.add(name, url, token, set_active=True)
        return mgr

    @classmethod
    def from_config(cls, config_path: Optional[str] = None) -> "ServerManager":
        """Create a manager and populate it from ``servers.json``."""
        mgr = cls(config_path=config_path)
        mgr.load()
        return mgr
