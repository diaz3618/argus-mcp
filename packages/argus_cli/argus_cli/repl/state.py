"""REPL state — split into focused dataclasses."""

from __future__ import annotations

__all__ = [
    "CompletionData",
    "ConnectionState",
    "ReplState",
    "SessionState",
    "ensure_history_dir",
]

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from argus_cli.config import CliConfig

_HISTORY_DIR = "~/.config/argus-mcp"


def ensure_history_dir() -> str:
    """Ensure the history directory exists and return the history file path."""
    history_dir = Path(_HISTORY_DIR).expanduser()
    history_dir.mkdir(parents=True, exist_ok=True)
    return str(history_dir / "history")


@dataclass
class ConnectionState:
    """Server connection status."""

    is_connected: bool = False
    server_status: str = "unknown"
    version: str = ""
    uptime: str = ""
    backend_count: int = 0
    healthy_count: int = 0
    last_event_age: str = ""


@dataclass
class CompletionData:
    """Dynamic completion data fetched from the API."""

    backend_names: list[str] = field(default_factory=list)
    tool_names: list[str] = field(default_factory=list)
    resource_uris: list[str] = field(default_factory=list)
    prompt_names: list[str] = field(default_factory=list)
    skill_names: list[str] = field(default_factory=list)
    workflow_names: list[str] = field(default_factory=list)
    secret_names: list[str] = field(default_factory=list)


@dataclass
class SessionState:
    """Per-session REPL state."""

    aliases: dict[str, str] = field(default_factory=dict)
    scoped_backend: str | None = None
    last_result: Any = None


@dataclass
class ReplState:
    """Composite REPL state.

    Attributes:
        config: Resolved CLI configuration for the current session.
        connection: Server connection and health status.
        completions: Dynamic completion data fetched from the API.
        session: Per-session state including aliases and scoped backend.
    """

    config: CliConfig
    connection: ConnectionState = field(default_factory=ConnectionState)
    completions: CompletionData = field(default_factory=CompletionData)
    session: SessionState = field(default_factory=SessionState)
