"""ContextVar for passing auth identity from the ASGI layer to MCP handlers.

The ASGI-level auth gate (in ``transport.py``) validates the incoming
bearer token and stores the resulting :class:`UserIdentity` here. MCP
handler code (``handlers.py``) reads it to populate
``RequestContext.metadata``.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Literal, Optional

from argus_mcp.server.auth.providers import UserIdentity

current_user: ContextVar[Optional[UserIdentity]] = ContextVar("current_user", default=None)

current_auth_token: ContextVar[Optional[str]] = ContextVar("current_auth_token", default=None)

current_session_id: ContextVar[Optional[str]] = ContextVar("current_session_id", default=None)

current_client_ip: ContextVar[Optional[str]] = ContextVar("current_client_ip", default=None)

current_auth_mode: ContextVar[Literal["strict", "permissive"]] = ContextVar(
    "current_auth_mode", default="strict"
)
