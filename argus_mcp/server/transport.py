"""SSE and streamable HTTP transport handling for MCP connections."""

from __future__ import annotations

import logging
from typing import Any, Optional

from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.sse import SseServerTransport
from starlette.requests import Request
from starlette.responses import Response

from argus_mcp.constants import POST_MESSAGES_PATH, SERVER_NAME, SERVER_VERSION
from argus_mcp.server.auth.providers import AuthenticationError, AuthProviderRegistry
from argus_mcp.server.auth_context import (
    current_auth_token,
    current_client_ip,
    current_session_id,
    current_user,
)

logger = logging.getLogger(__name__)

# Module-level SSE transport instance
sse_transport = SseServerTransport(POST_MESSAGES_PATH)

# Module-level incoming auth provider. Set during startup by lifespan
# when ``incoming_auth.type`` is not ``anonymous``.
_incoming_auth_provider: Optional[AuthProviderRegistry] = None


def _extract_bearer_token(scope: dict) -> Optional[str]:
    """Extract a bearer token from the ASSI scope's ``headers``."""
    for name, value in scope.get("headers", []):
        if name == b"authorization":
            decoded = value.decode("latin-1")
            if decoded.lower().startswith("bearer "):
                return decoded[7:]
            return None
    return None


async def _authenticate_request(scope: dict) -> None:
    """Validate the incoming request and store identity in contextvars.

    No-op when ``_incoming_auth_provider`` is *None* (anonymous mode).
    Raises :class:`AuthenticationError` on failure.
    """
    # Extract session-id and client IP regardless of auth mode
    for name, value in scope.get("headers", []):
        if name == b"mcp-session-id":
            current_session_id.set(value.decode("latin-1"))
            break
    client = scope.get("client")
    if client is not None:
        current_client_ip.set(client[0])

    if _incoming_auth_provider is None:
        return

    token = _extract_bearer_token(scope)
    user = await _incoming_auth_provider.authenticate(token)
    current_user.set(user)
    if token is not None:
        current_auth_token.set(token)


async def handle_sse(request: Request) -> None:
    """Handle incoming SSE connection requests."""
    from argus_mcp.server.app import mcp_server

    logger.debug("Received new SSE connection request (GET): %s", request.url)

    # ── Incoming auth gate ───────────────────────────────────────────
    try:
        await _authenticate_request(request.scope)
    except AuthenticationError as exc:
        logger.warning("SSE auth rejected: %s", exc)
        response = Response(status_code=401, content="Unauthorized")
        await response(request.scope, request.receive, request._send)
        return

    if not mcp_server.manager or not mcp_server.registry:
        logger.error(
            "manager or registry is unset in handle_sse. "
            "Missing critical components; cannot handle SSE connection."
        )
        return

    # ── Session management ───────────────────────────────────────────
    session_mgr = getattr(mcp_server, "session_manager", None)
    session = None
    if session_mgr is not None:
        route_map = mcp_server.registry.get_route_map()
        # route_map: tool_name → (backend_name, orig_name); flatten to tool_name → backend_name
        routing_table = {k: v[0] for k, v in route_map.items()} if route_map else {}
        session = session_mgr.create_session(
            routing_table=routing_table,
            capability_snapshot={
                "tools": len(mcp_server.registry.get_aggregated_tools()),
                "resources": len(mcp_server.registry.get_aggregated_resources()),
                "prompts": len(mcp_server.registry.get_aggregated_prompts()),
            },
            transport_type="sse",
        )

    async with sse_transport.connect_sse(
        request.scope,
        request.receive,
        request._send,
    ) as (read_stream, write_stream):
        try:
            srv_caps = {}
            if mcp_server.registry:
                srv_caps = mcp_server.get_capabilities(NotificationOptions(), {})
            else:
                logger.warning(
                    "mcp_server.registry is unset; SSE initialization will use empty capabilities."
                )
            logger.debug("Server capabilities for SSE connection: %s", srv_caps)
        except Exception as e_caps:  # noqa: BLE001
            logger.exception(
                "Error getting mcp_server.get_capabilities for SSE connection: %s",
                e_caps,
            )
            srv_caps = {}

        init_opts = InitializationOptions(
            server_name=SERVER_NAME,
            server_version=SERVER_VERSION,
            capabilities=srv_caps,
        )
        logger.debug(
            "Running mcp_server.run (MCP main loop) for SSE connection with options: %s",
            init_opts,
        )
        await mcp_server.run(read_stream, write_stream, init_opts)
    # ── Clean up session on disconnect ───────────────────────────────
    if session is not None and session_mgr is not None:
        session_mgr.remove_session(session.id)
    logger.debug("SSE connection closed: %s", request.url)


async def handle_streamable_http(scope: Any, receive: Any, send: Any) -> None:
    """Raw ASGI app for streamable-HTTP MCP requests (POST/GET/DELETE on /mcp).

    Delegates all session management, transport lifecycle, and MCP protocol
    handling to the SDK's ``StreamableHTTPSessionManager``.  That manager
    is created during application startup and stored on the app module; it
    internally maintains a registry of ``StreamableHTTPServerTransport``
    instances keyed by session-id and runs each session's ``mcp_server.run()``
    in a managed task group.

    This is a *raw* ASGI callable (not a Starlette ``endpoint``): the SDK
    manager's ``handle_request`` writes the HTTP response directly via the
    ASGI ``send`` callback.
    """
    from argus_mcp.server.app import streamable_session_manager

    if streamable_session_manager is None:
        response = Response(status_code=503, content="Service not ready")
        await response(scope, receive, send)
        return

    # ── Incoming auth gate ───────────────────────────────────────────
    try:
        await _authenticate_request(scope)
    except AuthenticationError as exc:
        logger.warning("Streamable-HTTP auth rejected: %s", exc)
        response = Response(status_code=401, content="Unauthorized")
        await response(scope, receive, send)
        return

    logger.debug(
        "Routing streamable-HTTP request to SDK session manager: %s %s",
        scope.get("method", "?"),
        scope.get("path", "?"),
    )
    await streamable_session_manager.handle_request(scope, receive, send)
