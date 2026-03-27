"""Starlette ASGI application factory and MCP server instance."""

import logging
from typing import Optional

from mcp.server import Server as McpServer
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.applications import Starlette
from starlette.routing import Mount, Route
from starlette.types import Receive, Scope, Send

from argus_mcp.constants import (
    MANAGEMENT_API_PREFIX,
    POST_MESSAGES_PATH,
    SERVER_NAME,
    SSE_PATH,
    STREAMABLE_HTTP_PATH,
    WELL_KNOWN_OAUTH_RESOURCE_PATH,
)
from argus_mcp.server.handlers import register_handlers
from argus_mcp.server.lifespan import app_lifespan
from argus_mcp.server.management import create_management_app
from argus_mcp.server.origin import OriginValidationMiddleware
from argus_mcp.server.transport import handle_sse, handle_streamable_http, sse_transport
from argus_mcp.server.well_known import handle_well_known_oauth_resource

logger = logging.getLogger(__name__)


class _MCPSlashMiddleware:
    """ASGI middleware: route ``/mcp`` (no trailing slash) to the MCP handler.

    Starlette's ``Mount("/mcp", app=handler)`` only matches ``/mcp/…`` and
    307-redirects the bare ``/mcp`` path.  MCP clients (VS Code, Claude
    Desktop) POST to ``/mcp`` and do *not* follow POST redirects.  This
    middleware intercepts the exact path before the router can redirect.
    """

    def __init__(self, app, *, mcp_path: str, mcp_handler) -> None:
        self.app = app
        self.mcp_path = mcp_path
        self.mcp_handler = mcp_handler

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope.get("path", "") == self.mcp_path:
            await self.mcp_handler(scope, receive, send)
            return
        await self.app(scope, receive, send)


# Module-level MCP server instance
mcp_server = McpServer(SERVER_NAME)
setattr(mcp_server, "manager", None)
setattr(mcp_server, "registry", None)
logger.debug("Underlying MCP server instance '%s' created.", mcp_server.name)

# SDK session manager for Streamable-HTTP transport.
# Handles all session persistence, transport lifecycle, and MCP server-loop
# management internally.  ``session_manager.run()`` must be entered during
# the application lifespan, and ``session_manager.handle_request()`` is
# called per HTTP request (see transport.py).
streamable_session_manager: Optional[StreamableHTTPSessionManager] = None

register_handlers(mcp_server)


def create_app() -> Starlette:
    """Create and return the Starlette ASGI application."""
    mgmt_app = create_management_app()

    # handle_streamable_http is a raw ASGI app (scope, receive, send)
    # because transport.handle_request() sends the HTTP response via
    # the ASGI send callable directly.  Starlette's ``endpoint=``
    # wrapper (request_response) would try to call the return value
    # as Response(...), causing a TypeError.  We mount it as a raw
    # ASGI app instead with a thin method-check wrapper.

    _ALLOWED_METHODS = {"GET", "POST", "DELETE"}

    async def _streamable_http_app(scope: Scope, receive: Receive, send: Send) -> None:
        from starlette.responses import PlainTextResponse

        if scope["type"] == "http" and scope.get("method", "GET") not in _ALLOWED_METHODS:
            resp = PlainTextResponse("Method Not Allowed", status_code=405)
            await resp(scope, receive, send)
            return
        await handle_streamable_http(scope, receive, send)

    application = Starlette(
        lifespan=app_lifespan,
        routes=[
            Route(WELL_KNOWN_OAUTH_RESOURCE_PATH, endpoint=handle_well_known_oauth_resource),
            Route(SSE_PATH, endpoint=handle_sse),
            Mount(POST_MESSAGES_PATH, app=sse_transport.handle_post_message),
            Mount(STREAMABLE_HTTP_PATH, app=_streamable_http_app),
            Mount(MANAGEMENT_API_PREFIX, app=mgmt_app),
        ],
    )

    # Intercept /mcp (no trailing slash) before Starlette's Mount()
    # can 307-redirect it to /mcp/.  MCP clients POST to /mcp and
    # do not follow redirects.
    application.add_middleware(
        _MCPSlashMiddleware,
        mcp_path=STREAMABLE_HTTP_PATH,
        mcp_handler=_streamable_http_app,
    )

    # Validate Origin header on MCP transport endpoints per MCP spec.
    # Must be added AFTER _MCPSlashMiddleware (Starlette middleware
    # wraps in reverse order, so last-added executes first).
    application.add_middleware(OriginValidationMiddleware)
    # Store mgmt_app reference so lifespan can propagate service state to it.
    setattr(application.state, "mgmt_app", mgmt_app)
    logger.info(
        "Starlette ASGI app '%s' created. "
        "SSE GET on %s, POST on %s, Streamable HTTP on %s, Manage on %s",
        SERVER_NAME,
        SSE_PATH,
        POST_MESSAGES_PATH,
        STREAMABLE_HTTP_PATH,
        MANAGEMENT_API_PREFIX,
    )
    return application


# Default app instance for uvicorn import
app = create_app()
