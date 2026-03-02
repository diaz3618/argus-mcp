"""Named session management for detached Argus MCP servers.

Stores session metadata as JSON files under ``~/.argus/sessions/``
(or ``$ARGUS_STATE_DIR/sessions/`` if the env-var is set).  Each file
contains the PID, port, host, config path, and start time so that
``argus-mcp status`` can list all running instances and
``argus-mcp stop <name>`` can target a specific one.
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────


def _state_base() -> str:
    """Return a writable base directory for Argus runtime state.

    Resolution order:
    1. ``ARGUS_STATE_DIR`` environment variable (explicit override)
    2. ``~/.argus`` (works in Docker, venvs, and local dev alike)
    """
    env = os.environ.get("ARGUS_STATE_DIR")
    if env:
        return env
    return os.path.join(os.path.expanduser("~"), ".argus")


_SESSION_DIR = os.path.join(_state_base(), "sessions")

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,31}$")


# ── Data ─────────────────────────────────────────────────────────────────


@dataclass
class SessionInfo:
    """Metadata for a single detached server session."""

    name: str
    pid: int
    host: str
    port: int
    config: str
    log_file: str = ""
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def is_alive(self) -> bool:
        """Return *True* if the process is still running."""
        try:
            os.kill(self.pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # exists but not ours


# ── Public API ───────────────────────────────────────────────────────────


def validate_name(name: str) -> str:
    """Validate and normalise a session name.

    Raises ``ValueError`` if the name is invalid.
    """
    name = name.lower().strip()
    if not _NAME_RE.match(name):
        raise ValueError(
            f"Invalid session name '{name}'. "
            "Use lowercase alphanumeric + hyphens, 1–32 chars, "
            "starting with a letter or digit."
        )
    return name


def auto_name(port: int, default_port: int) -> str:
    """Generate a session name from the port number.

    * Default port → ``"default"``
    * Custom port  → ``"argus-<port>"``
    """
    if port == default_port:
        return "default"
    return f"argus-{port}"


def session_path(name: str) -> str:
    """Return the file path for a session metadata file."""
    return os.path.join(_SESSION_DIR, f"{name}.json")


def save_session(info: SessionInfo) -> str:
    """Write session metadata to disk.  Returns the file path."""
    os.makedirs(_SESSION_DIR, exist_ok=True)
    path = session_path(info.name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(asdict(info), fh, indent=2)
    logger.debug("Session '%s' saved to %s", info.name, path)
    return path


def load_session(name: str) -> Optional[SessionInfo]:
    """Load session metadata from disk, or ``None`` if missing/corrupt."""
    path = session_path(name)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return SessionInfo(**data)
    except FileNotFoundError:
        return None
    except Exception:
        logger.warning("Corrupt session file %s", path, exc_info=True)
        return None


def remove_session(name: str) -> None:
    """Delete the session metadata file."""
    path = session_path(name)
    try:
        os.unlink(path)
        logger.debug("Session file removed: %s", path)
    except FileNotFoundError:
        pass


def list_sessions(*, include_dead: bool = False) -> List[SessionInfo]:
    """List all saved sessions, optionally filtering out dead ones.

    Dead sessions (stale PIDs) are automatically cleaned up unless
    ``include_dead`` is *True*.
    """
    if not os.path.isdir(_SESSION_DIR):
        return []

    sessions: List[SessionInfo] = []
    for fname in sorted(os.listdir(_SESSION_DIR)):
        if not fname.endswith(".json"):
            continue
        name = fname[:-5]
        info = load_session(name)
        if info is None:
            continue

        if info.is_alive():
            sessions.append(info)
        elif include_dead:
            sessions.append(info)
        else:
            # Auto-clean stale sessions
            logger.info(
                "Cleaning stale session '%s' (PID %d no longer running)",
                info.name,
                info.pid,
            )
            remove_session(info.name)

    return sessions


def find_session(name_or_none: Optional[str] = None) -> Optional[SessionInfo]:
    """Find a session by name, or return the only running session.

    If *name_or_none* is ``None``:
    * Returns the session if exactly one is running.
    * Returns ``None`` if zero or more than one are running.
    """
    if name_or_none is not None:
        info = load_session(name_or_none)
        if info is not None and info.is_alive():
            return info
        return None

    alive = list_sessions()
    if len(alive) == 1:
        return alive[0]
    return None


def stop_session(
    info: SessionInfo,
    *,
    timeout: float = 3.0,
    force: bool = False,
) -> bool:
    """Stop a session by sending SIGTERM (then SIGKILL if needed).

    Returns *True* if the process was stopped successfully.
    """
    if not info.is_alive():
        remove_session(info.name)
        return True

    sig = signal.SIGKILL if force else signal.SIGTERM
    try:
        os.kill(info.pid, sig)
    except OSError as exc:
        logger.error("Failed to signal PID %d: %s", info.pid, exc)
        return False

    # Wait for exit
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not info.is_alive():
            remove_session(info.name)
            return True
        time.sleep(0.1)

    # Escalate to SIGKILL
    if not force:
        try:
            os.kill(info.pid, signal.SIGKILL)
        except OSError:
            pass
        time.sleep(0.2)

    remove_session(info.name)
    return not info.is_alive()


def check_port_conflict(host: str, port: int) -> Optional[SessionInfo]:
    """Return a running session using the same host:port, if any."""
    for info in list_sessions():
        if info.port == port and (info.host == host or info.host == "0.0.0.0"):
            return info
    return None
