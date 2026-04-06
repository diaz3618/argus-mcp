"""MCP Origin validation middleware.

Per the MCP specification (§ Transports — HTTP):

    "Servers MUST validate the Origin header on all HTTP requests to
    prevent DNS rebinding attacks.  If the Origin header is not present
    or does not match the expected origin, the server MUST reject the
    request with a 403 Forbidden response."

    Source: https://modelcontextprotocol.io/specification/2025-11-05/basic/transports

This middleware validates the ``Origin`` header on MCP transport paths
(``/mcp``, ``/sse``, ``/messages/``).  Localhost origins are always
allowed for local development.  Additional allowed origins can be
configured via the ``ARGUS_ALLOWED_ORIGINS`` environment variable
(comma-separated list).

The management API (``/manage/…``) is **not** subject to Origin checks
because it has its own authentication layer (``BearerAuthMiddleware``).
"""

import logging
import os
from typing import FrozenSet, Optional
from urllib.parse import urlparse

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

# Path prefixes subject to Origin validation (MCP transport endpoints).
_MCP_PATH_PREFIXES = ("/mcp", "/sse", "/messages")

# Hosts considered "localhost" — requests from these origins are always
# permitted, matching MCP Inspector / Claude Desktop / VS Code behaviour.
_LOCALHOST_HOSTS: FrozenSet[str] = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "::1",
        "[::1]",
    }
)

# Environment variable for additional allowed origins.
_ALLOWED_ORIGINS_ENV = "ARGUS_ALLOWED_ORIGINS"


def _parse_allowed_origins() -> FrozenSet[str]:
    """Parse ``ARGUS_ALLOWED_ORIGINS`` into a frozen set of lowercased origins."""
    raw = os.environ.get(_ALLOWED_ORIGINS_ENV, "").strip()
    if not raw:
        return frozenset()
    return frozenset(o.strip().lower() for o in raw.split(",") if o.strip())


def _is_localhost_origin(origin: str) -> bool:
    """Return True if *origin* points to a localhost address."""
    try:
        parsed = urlparse(origin)
        host = (parsed.hostname or "").lower()
        return host in _LOCALHOST_HOSTS
    except (ValueError, AttributeError) as exc:
        logger.debug("Failed to parse origin '%s': %s", origin, exc)
        return False


class OriginValidationMiddleware:
    """Pure ASGI middleware that validates the ``Origin`` header on MCP routes.

    * Requests from localhost origins are always accepted.
    * Requests from any origin listed in ``ARGUS_ALLOWED_ORIGINS`` are accepted.
    * All other origins receive a ``403 Forbidden`` response.

    Behaviour for **missing** Origin headers depends on ``require_origin``:

    * ``"permissive"`` (default) — requests without an ``Origin`` header are
      allowed through.  This accommodates CLI / SDK clients that do not send
      ``Origin``.
    * ``"strict"`` — requests on MCP transport paths **must** include an
      ``Origin`` header.  Missing headers result in a ``403 Forbidden``
      response (SEC-13).

    Non-MCP paths (e.g. ``/manage/…``) are never checked.
    """

    def __init__(
        self,
        app: ASGIApp,
        *,
        require_origin: str = "permissive",
    ) -> None:
        self.app = app
        self._require_origin = require_origin.lower()
        self._allowed_origins = _parse_allowed_origins()
        if self._allowed_origins:
            logger.info(
                "Origin validation: additional allowed origins = %s",
                self._allowed_origins,
            )
        else:
            logger.info(
                "Origin validation: only localhost origins allowed on MCP routes. "
                "Set %s to allow additional origins.",
                _ALLOWED_ORIGINS_ENV,
            )
        if self._require_origin == "strict":
            logger.info(
                "Origin validation: strict mode ENABLED — "
                "MCP requests without an Origin header will be rejected."
            )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path: str = scope.get("path", "/")

        # Only validate MCP transport paths.
        if not any(path.startswith(prefix) for prefix in _MCP_PATH_PREFIXES):
            await self.app(scope, receive, send)
            return

        origin: Optional[str] = None
        for key, value in scope.get("headers", []):
            if key == b"origin":
                origin = value.decode("latin-1")
                break

        # No Origin header — behaviour depends on require_origin mode.
        if not origin:
            if self._require_origin == "strict":
                client = scope.get("client")
                client_host = client[0] if client else "unknown"
                logger.warning(
                    "Rejected MCP request without Origin header (strict mode, client=%s, path=%s).",
                    client_host,
                    path,
                )
                response = JSONResponse(
                    {
                        "error": "forbidden",
                        "message": (
                            "Origin header is required on MCP transport requests "
                            "(strict mode). Include a valid Origin header."
                        ),
                    },
                    status_code=403,
                )
                await response(scope, receive, send)
                return
            # Permissive mode — allow through (CLI clients, curl, SDK direct calls).
            await self.app(scope, receive, send)
            return

        origin_lower = origin.lower()

        # Localhost origins are always acceptable.
        if _is_localhost_origin(origin_lower):
            await self.app(scope, receive, send)
            return

        if origin_lower in self._allowed_origins:
            await self.app(scope, receive, send)
            return

        # Reject — log and return 403.
        client = scope.get("client")
        client_host = client[0] if client else "unknown"
        logger.warning(
            "Rejected request from disallowed Origin '%s' (client=%s, path=%s). "
            "Set %s to allow this origin.",
            origin,
            client_host,
            path,
            _ALLOWED_ORIGINS_ENV,
        )
        response = JSONResponse(
            {
                "error": "forbidden",
                "message": (
                    f"Origin '{origin}' is not allowed. "
                    "Only localhost origins are accepted by default."
                ),
            },
            status_code=403,
        )
        await response(scope, receive, send)
