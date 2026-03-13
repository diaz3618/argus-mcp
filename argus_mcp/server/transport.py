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
    current_auth_mode,
    current_auth_token,
    current_client_ip,
    current_session_id,
    current_user,
)
from argus_mcp.server.sse_resilience import SseResilience

logger = logging.getLogger(__name__)

# Module-level SSE transport instance
sse_transport = SseServerTransport(POST_MESSAGES_PATH)

# Module-level SSE resilience guard. Configured during startup by lifespan
# from ``sse_resilience`` config section; defaults are safe.
_sse_resilience: SseResilience = SseResilience()

# Module-level incoming auth provider. Set during startup by lifespan
# when ``incoming_auth.type`` is not ``anonymous``.
_incoming_auth_provider: Optional[AuthProviderRegistry] = None

# Module-level auth mode. Set during startup by lifespan from
# ``incoming_auth.auth_mode``; defaults to "strict".
_auth_mode: str = "strict"

# Module-level issuer URL for WWW-Authenticate headers (RFC 6750).
# Set during startup from ``incoming_auth.issuer``.
_auth_issuer: Optional[str] = None


def _build_www_authenticate(error: Optional[str] = None) -> str:
    """Build a ``WWW-Authenticate: Bearer`` header value per RFC 6750 §3.

    Includes ``realm`` (from configured issuer) and optional ``error``.
    """
    parts = ["Bearer"]
    params: list[str] = []
    if _auth_issuer:
        params.append(f'realm="{_auth_issuer}"')
    if error:
        params.append(f'error="{error}"')
    if params:
        parts.append(" ")
        parts.append(", ".join(params))
    return "".join(parts)


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
    # Always publish the configured auth mode so downstream handlers can read it.
    current_auth_mode.set(_auth_mode)

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
    """Handle incoming SSE connection requests with resilience guards."""
    from argus_mcp.server.app import mcp_server

    logger.debug("Received new SSE connection request (GET): %s", request.url)

    try:
        await _authenticate_request(request.scope)
    except AuthenticationError as exc:
        logger.warning("SSE auth rejected: %s", exc)
        # Determine error type: missing token vs invalid token
        token = _extract_bearer_token(request.scope)
        error_type = "invalid_token" if token else None
        www_auth = _build_www_authenticate(error=error_type)
        response = Response(
            status_code=401,
            content="Unauthorized",
            headers={"WWW-Authenticate": www_auth},
        )
        await response(request.scope, request.receive, request._send)
        return

    if not mcp_server.manager or not mcp_server.registry:
        logger.error(
            "manager or registry is unset in handle_sse. "
            "Missing critical components; cannot handle SSE connection."
        )
        return

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
        guarded_read, guarded_write, metrics = _sse_resilience.wrap_streams(
            read_stream, write_stream
        )

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
        await mcp_server.run(guarded_read, guarded_write, init_opts)

    if session is not None and session_mgr is not None:

        async def _do_cleanup() -> None:
            session_mgr.remove_session(session.id)

        await _sse_resilience.cleanup_with_deadline(
            _do_cleanup(), label=f"session {session.id} cleanup"
        )

    _sse_resilience.log_connection_summary(metrics, url=str(request.url))


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

    try:
        await _authenticate_request(scope)
    except AuthenticationError as exc:
        logger.warning("Streamable-HTTP auth rejected: %s", exc)
        token = _extract_bearer_token(scope)
        error_type = "invalid_token" if token else None
        www_auth = _build_www_authenticate(error=error_type)
        response = Response(
            status_code=401,
            content="Unauthorized",
            headers={"WWW-Authenticate": www_auth},
        )
        await response(scope, receive, send)
        return

    logger.debug(
        "Routing streamable-HTTP request to SDK session manager: %s %s",
        scope.get("method", "?"),
        scope.get("path", "?"),
    )
    await streamable_session_manager.handle_request(scope, receive, send)
