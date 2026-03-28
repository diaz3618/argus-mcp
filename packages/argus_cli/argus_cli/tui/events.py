"""Custom Textual messages for Argus MCP TUI."""

from __future__ import annotations

from typing import Any

from textual.message import Message


class CapabilitiesReady(Message):
    """Posted once capabilities have been discovered and are available."""

    def __init__(
        self,
        tools: list[Any],
        resources: list[Any],
        prompts: list[Any],
        route_map: dict[str, tuple] | None = None,
    ) -> None:
        self.tools = tools
        self.resources = resources
        self.prompts = prompts
        self.route_map = route_map or {}
        super().__init__()


class ConnectionLost(Message):
    """Posted when the TUI loses its HTTP connection to the server."""

    def __init__(self, reason: str = "Connection lost") -> None:
        self.reason = reason
        super().__init__()


class ConnectionRestored(Message):
    """Posted when the TUI re-establishes its HTTP connection."""

    def __init__(self) -> None:
        super().__init__()


class ConfigSyncUpdate(Message):
    """Posted when the server reports a config file change.

    Carries the details needed by :class:`SyncStatusWidget` to refresh.
    """

    def __init__(
        self,
        config_file: str = "",
        config_hash: str = "",
        sync_type: str = "changed",
        details: str = "",
        timestamp: str = "",
    ) -> None:
        self.config_file = config_file
        self.config_hash = config_hash
        self.sync_type = sync_type
        self.details = details
        self.timestamp = timestamp
        super().__init__()


class ReAuthRequired(Message):
    """Posted when a backend's OAuth token cannot be refreshed.

    Signals that the user must interactively re-authenticate for a
    specific backend (e.g. via a browser-based PKCE flow).
    """

    def __init__(self, backend_name: str, reason: str = "") -> None:
        self.backend_name = backend_name
        self.reason = reason
        super().__init__()
