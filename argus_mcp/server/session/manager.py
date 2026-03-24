"""Session lifecycle management with TTL-based cleanup."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from argus_mcp._task_utils import _log_task_exception
from argus_mcp.constants import SESSION_DEFAULT_TTL
from argus_mcp.server.session.models import MCPSession

logger = logging.getLogger(__name__)

_DEFAULT_CLEANUP_INTERVAL: float = 60.0  # seconds between cleanup sweeps


class SessionManager:
    """Manages per-client MCP sessions.

    Each session captures a snapshot of the routing table at creation
    time.  A background task periodically removes expired sessions.

    Parameters
    ----------
    default_ttl:
        Default session time-to-live in seconds.
    cleanup_interval:
        How often (in seconds) the cleanup loop runs.
    """

    def __init__(
        self,
        default_ttl: float = SESSION_DEFAULT_TTL,
        cleanup_interval: float = _DEFAULT_CLEANUP_INTERVAL,
    ) -> None:
        self._sessions: Dict[str, MCPSession] = {}
        self._default_ttl = default_ttl
        self._cleanup_interval = cleanup_interval
        self._cleanup_task: Optional[asyncio.Task[None]] = None

    def start(self) -> None:
        """Start the background cleanup loop."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop(), name="session-cleanup")
            self._cleanup_task.add_done_callback(_log_task_exception)
            logger.info(
                "Session cleanup started (interval=%.0fs, default_ttl=%.0fs).",
                self._cleanup_interval,
                self._default_ttl,
            )

    async def stop(self) -> None:
        """Cancel the cleanup task and clear all sessions."""
        if self._cleanup_task is not None and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        count = len(self._sessions)
        self._sessions.clear()
        logger.info("SessionManager stopped. Cleared %d session(s).", count)

    def create_session(
        self,
        routing_table: Dict[str, str],
        capability_snapshot: Optional[Dict[str, Any]] = None,
        transport_type: str = "",
        session_id: Optional[str] = None,
    ) -> MCPSession:
        """Create a new session with a *frozen* routing table snapshot.

        Parameters
        ----------
        routing_table:
            Current ``tool_name → backend_name`` mapping (will be copied).
        capability_snapshot:
            Optional ``{"tools": N, "resources": N, "prompts": N}`` dict.
        transport_type:
            ``"sse"`` or ``"streamable_http"``.
        session_id:
            Optional pre-assigned session ID (used by streamable HTTP
            when the client sends ``Mcp-Session-Id``).
        """
        session = MCPSession(
            routing_table=dict(routing_table),
            capability_snapshot=dict(capability_snapshot) if capability_snapshot else {},
            ttl=self._default_ttl,
            transport_type=transport_type,
        )
        if session_id:
            session.id = session_id
        self._sessions[session.id] = session
        logger.info(
            "Session created: id=%s transport=%s tools=%d ttl=%.0f",
            session.id,
            transport_type,
            len(session.routing_table),
            session.ttl,
        )
        return session

    def get_session(self, session_id: str) -> Optional[MCPSession]:
        """Return the session if it exists and is not expired.

        Automatically calls ``touch()`` to refresh the idle timer.
        """
        session = self._sessions.get(session_id)
        if session is None:
            return None
        if session.expired:
            self._remove(session_id)
            return None
        session.touch()
        return session

    def remove_session(self, session_id: str) -> bool:
        """Explicitly remove a session (e.g. on SSE disconnect).

        Returns ``True`` if the session existed.
        """
        return self._remove(session_id)

    @property
    def active_count(self) -> int:
        """Number of non-expired sessions."""
        return sum(1 for s in self._sessions.values() if not s.expired)

    def list_sessions(self) -> List[Dict[str, Any]]:
        """Return a list of session summaries for the management API."""
        return [s.to_dict() for s in self._sessions.values() if not s.expired]

    def _remove(self, session_id: str) -> bool:
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.debug("Session removed: %s", session_id)
            return True
        return False

    async def _cleanup_loop(self) -> None:
        """Periodically remove expired sessions."""
        try:
            while True:
                await asyncio.sleep(self._cleanup_interval)
                expired = [sid for sid, s in self._sessions.items() if s.expired]
                for sid in expired:
                    self._remove(sid)
                if expired:
                    logger.info(
                        "Session cleanup: removed %d expired session(s), %d remaining.",
                        len(expired),
                        len(self._sessions),
                    )
        except asyncio.CancelledError:
            logger.debug("Session cleanup loop cancelled.")
