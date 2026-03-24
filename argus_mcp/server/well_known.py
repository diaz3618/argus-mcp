"""RFC 9728 OAuth Protected Resource Metadata endpoint.

Serves ``/.well-known/oauth-protected-resource`` so that MCP clients can
auto-discover which Authorization Server protects this gateway and what
scopes/methods are supported — without needing out-of-band configuration.

See: https://datatracker.ietf.org/doc/html/rfc9728
"""

from __future__ import annotations

import logging
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger(__name__)


def _is_auth_enabled() -> bool:
    """Check whether incoming authentication is active.

    Reads the already-initialized module-level state in ``transport``
    rather than re-loading the config file (which requires a file path
    not available at request time).
    """
    from argus_mcp.server.transport import _incoming_auth_provider

    return _incoming_auth_provider is not None


async def handle_well_known_oauth_resource(request: Request) -> JSONResponse:
    """Return OAuth Protected Resource Metadata per RFC 9728.

    Response shape (JSON):
    ```json
    {
      "resource": "<this server's base URL>",
      "authorization_servers": ["<issuer URL>"],
      "scopes_supported": [],
      "bearer_methods_supported": ["header"]
    }
    ```

    Returns 404 when incoming auth is not configured (anonymous mode).
    """
    if not _is_auth_enabled():
        return JSONResponse(
            {
                "error": "no_auth_configured",
                "error_description": "This server does not require OAuth authentication.",
            },
            status_code=404,
        )

    from argus_mcp.server.transport import _auth_issuer

    # For local/static bearer-token auth there is no OAuth authorization
    # server to advertise.  Returning an empty ``authorization_servers``
    # list causes VS Code's MCP client to attempt Dynamic Client
    # Registration, which always fails.  Return 404 so the client skips
    # OAuth discovery entirely and uses the static ``Authorization``
    # header from its configuration.
    if not _auth_issuer:
        return JSONResponse(
            {
                "error": "no_oauth_server",
                "error_description": (
                    "This server uses static bearer-token authentication. "
                    "No OAuth authorization server is configured."
                ),
            },
            status_code=404,
        )

    # Build the resource identifier from the request URL (scheme + host)
    resource = f"{request.url.scheme}://{request.url.netloc}"

    metadata: dict[str, Any] = {
        "resource": resource,
        "authorization_servers": [_auth_issuer],
        "bearer_methods_supported": ["header"],
    }

    return JSONResponse(metadata, status_code=200)
