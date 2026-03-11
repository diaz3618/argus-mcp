"""Management API package.

Exposes ``create_management_app`` to build the management ASGI sub-app with auth.
"""

from starlette.applications import Starlette

from argus_mcp.server.management.auth import BearerAuthMiddleware, resolve_token
from argus_mcp.server.management.router import management_routes


def create_management_app() -> BearerAuthMiddleware:
    """Build the management sub-application with auth middleware.

    Returns a :class:`BearerAuthMiddleware` wrapping a Starlette app with
    the management routes.  The middleware's ``state`` property delegates
    to the inner Starlette's state, so ``mgmt_app.state.X`` works
    transparently.  The middleware's ``set_token()`` method allows the
    lifespan to apply a config-file token after startup.

    The middleware resolves the bind address lazily from the ASGI
    ``server`` scope tuple, so it correctly detects non-localhost
    exposure even though this function is called before the host
    is known.
    """
    token = resolve_token()
    inner_app = Starlette(routes=management_routes.routes)
    auth_middleware = BearerAuthMiddleware(inner_app, token=token)
    return auth_middleware


__all__ = ["create_management_app", "management_routes"]
