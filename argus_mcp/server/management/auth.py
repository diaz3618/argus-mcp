"""Bearer token authentication for the Management API.

Token is resolved from (highest priority first):
1. ``ARGUS_MGMT_TOKEN`` environment variable
2. ``management.token`` in the config file (future — Phase 0 config restructure)

If no token is configured, authentication is **disabled** and all requests pass.
``/manage/v1/health`` and ``/manage/v1/ready`` are always public regardless of auth configuration.
"""

import hmac
import logging
import os
from typing import Optional

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Environment variable for the management API token
MGMT_TOKEN_ENV_VAR = "ARGUS_MGMT_TOKEN"

# Path suffixes that never require authentication.  The middleware
# receives the full mounted path (e.g. ``/manage/v1/health``), so
# we match on the trailing segment(s) rather than the exact path.
PUBLIC_PATH_SUFFIXES = frozenset({"/health", "/ready"})


def resolve_token() -> Optional[str]:
    """Resolve the management API token from available sources.

    Returns ``None`` if no token is configured (auth disabled).
    """
    # 1. Environment variable (highest priority)
    env_token = os.environ.get(MGMT_TOKEN_ENV_VAR, "").strip()
    if env_token:
        # nosemgrep: python-logger-credential-disclosure (logs env var name, not token)
        logger.debug("Management API token resolved from %s env var.", MGMT_TOKEN_ENV_VAR)
        return env_token

    # 2. Config file (future — will be populated when config restructure lands)
    # For now, return None if env var is not set.
    return None


class BearerAuthMiddleware:
    """Pure ASGI middleware that enforces Bearer token auth on management routes.

    Uses the ASGI interface directly (no ``BaseHTTPMiddleware``) to avoid
    known performance and ``contextvars`` propagation issues.

    When the server binds to a non-localhost address (``0.0.0.0``, a LAN
    IP, etc.) **without** an auth token, a prominent warning is emitted
    and *mutating* management endpoints (everything except ``/health``)
    log a security warning per request.

    Usage::

        middleware = BearerAuthMiddleware(app, token="<your-token>")
    """

    # Mutating path suffixes — these are the endpoints that should
    # require auth when exposed to a non-localhost interface.
    _MUTATING_SUFFIXES = frozenset({"/reload", "/reconnect", "/reauth", "/shutdown"})

    _LOCALHOST_ADDRS = frozenset({"127.0.0.1", "localhost", "::1"})

    def __init__(
        self,
        app: ASGIApp,
        token: Optional[str] = None,
    ) -> None:
        self.app = app
        self._token = token
        # Track whether the startup-time exposure warning has been logged
        # so we emit it at most once (on the first non-localhost request).
        self._warned_exposed = False

        if token:
            logger.info("Management API authentication ENABLED.")
        else:
            logger.warning(
                "Management API authentication DISABLED — no token configured. "
                "Set %s env var to secure admin endpoints.",
                MGMT_TOKEN_ENV_VAR,
            )

    # When this middleware wraps a Starlette app and is stored as the
    # ``mgmt_app`` reference, callers that access ``mgmt_app.state``
    # (e.g. lifespan propagation, route handlers) transparently reach
    # the inner Starlette's State object.

    @property
    def state(self):
        """Delegate to inner app's Starlette state."""
        return self.app.state

    @property
    def auth_enabled(self) -> bool:
        return self._token is not None

    def set_token(self, token: str) -> None:
        """Apply a token at runtime (deferred config-file fallback).

        Called during lifespan when the config file provides
        ``server.management.token`` but no ``ARGUS_MGMT_TOKEN`` env var
        was set at app-factory time.
        """
        self._token = token
        logger.info("Management API authentication ENABLED (token applied from config).")

    async def _handle_no_auth(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Pass request through when auth is disabled, warning on exposed binds."""
        server_tuple = scope.get("server")
        bind_host = server_tuple[0] if server_tuple else "127.0.0.1"
        is_exposed = bind_host not in self._LOCALHOST_ADDRS

        if is_exposed and not self._warned_exposed:
            self._warned_exposed = True
            logger.warning(
                "⚠️  SECURITY WARNING: Management API authentication is "
                "DISABLED while serving on non-localhost address '%s'. "
                "Mutating endpoints (/reload, /reconnect, /shutdown) are "
                "accessible to anyone on the network. "
                "Set %s env var to secure admin endpoints.",
                bind_host,
                MGMT_TOKEN_ENV_VAR,
            )

        path = scope.get("path", "/")
        stripped = path.rstrip("/")
        if is_exposed and any(stripped.endswith(s) for s in self._MUTATING_SUFFIXES):
            client = scope.get("client")
            client_host = client[0] if client else "unknown"
            logger.warning(
                "⚠️  Unauthenticated mutating request from %s → %s "
                "(no %s configured, binding on non-localhost '%s')",
                client_host,
                path,
                MGMT_TOKEN_ENV_VAR,
                bind_host,
            )
        await self.app(scope, receive, send)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "/")

        # Always allow public paths (suffix match handles mount prefixes)
        stripped = path.rstrip("/")
        if any(stripped.endswith(suffix) for suffix in PUBLIC_PATH_SUFFIXES):
            await self.app(scope, receive, send)
            return

        if not self.auth_enabled:
            await self._handle_no_auth(scope, receive, send)
            return

        # Extract Authorization header from raw ASGI headers
        auth_header = ""
        for key, value in scope.get("headers", []):
            if key == b"authorization":
                auth_header = value.decode("latin-1")
                break

        if not auth_header.startswith("Bearer "):
            response = _unauthorized(
                "Missing or malformed Authorization header. Expected: Bearer <token>"
            )
            await response(scope, receive, send)
            return

        provided_token = auth_header[7:]  # Strip "Bearer " prefix

        # Constant-time comparison to prevent timing attacks
        if not hmac.compare_digest(provided_token, self._token):  # type: ignore[arg-type]
            client = scope.get("client")
            client_host = client[0] if client else "unknown"
            logger.warning(
                "Failed authentication attempt from %s for %s",
                client_host,
                path,
            )
            response = _unauthorized("Invalid bearer token.")
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


def _unauthorized(message: str) -> JSONResponse:
    """Return a 401 Unauthorized JSON response."""
    return JSONResponse(
        {"error": "unauthorized", "message": message},
        status_code=401,
        headers={"WWW-Authenticate": "Bearer"},
    )
