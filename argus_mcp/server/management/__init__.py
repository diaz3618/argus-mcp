"""Management API package.

Exposes ``create_management_app`` to build the management ASGI sub-app with auth.
"""

from starlette.applications import Starlette
from starlette.middleware import Middleware

from argus_mcp.server.management.auth import BearerAuthMiddleware, resolve_token
from argus_mcp.server.management.router import management_routes


def create_management_app() -> Starlette:
    """Build the management sub-application with auth middleware.

    Returns a Starlette app wrapping the management routes with
    ``BearerAuthMiddleware``.  The token is resolved from env var
    or config at construction time.

    The middleware resolves the bind address lazily from the ASGI
    ``server`` scope tuple, so it correctly detects non-localhost
    exposure even though this function is called before the host
    is known.
    """
    token = resolve_token()
    mgmt_app = Starlette(
        routes=management_routes.routes,
        middleware=[Middleware(BearerAuthMiddleware, token=token)],
    )
    return mgmt_app


__all__ = ["create_management_app", "management_routes"]
