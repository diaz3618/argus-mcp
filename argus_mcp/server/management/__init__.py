"""Management API package.

Exposes ``create_management_app`` to build the management ASGI sub-app with auth.
"""

import logging
from typing import Optional

from starlette.applications import Starlette

from argus_mcp.server.management.auth import (
    BearerAuthMiddleware,
    resolve_token,
    validate_token_entropy,
)
from argus_mcp.server.management.router import management_routes

logger = logging.getLogger(__name__)


def create_management_app(
    *,
    config_token: Optional[str] = None,
    allow_weak_tokens: bool = False,
) -> BearerAuthMiddleware:
    """Build the management sub-application with auth middleware.

    Token is resolved and validated **before** the Starlette app is created,
    closing the race window where requests could arrive before authentication
    is configured (SEC-11).

    Args:
        config_token: Optional fallback token from the config file (used when
            ``ARGUS_MGMT_TOKEN`` env var is not set).
        allow_weak_tokens: When ``True``, accept tokens shorter than 16
            characters (not recommended for production).

    Returns a :class:`BearerAuthMiddleware` wrapping a Starlette app with
    the management routes.  The middleware's ``state`` property delegates
    to the inner Starlette's state, so ``mgmt_app.state.X`` works
    transparently.

    Raises:
        ValueError: If the token is a known placeholder or too short
            (and ``allow_weak_tokens`` is ``False``).
    """
    # Resolve token BEFORE building the app — no race window (SEC-11)
    raw_token = resolve_token(config_token=config_token)
    token = validate_token_entropy(raw_token, allow_weak=allow_weak_tokens)

    inner_app = Starlette(routes=management_routes.routes)
    auth_middleware = BearerAuthMiddleware(inner_app, token=token)
    return auth_middleware


__all__ = ["create_management_app", "management_routes"]
