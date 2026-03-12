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


def _get_incoming_auth_config() -> Any | None:
    """Load the current IncomingAuthConfig from the running app's config.

    Returns ``None`` when config is unavailable or auth is anonymous.
    """
    try:
        from argus_mcp.config.loader import load_argus_config

        cfg = load_argus_config()
        if cfg is not None and cfg.incoming_auth.type != "anonymous":
            return cfg.incoming_auth
    except Exception:  # noqa: BLE001
        logger.debug("Could not load incoming auth config for well-known endpoint.", exc_info=True)
    return None


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
    auth_cfg = _get_incoming_auth_config()
    if auth_cfg is None:
        return JSONResponse(
            {
                "error": "no_auth_configured",
                "error_description": "This server does not require OAuth authentication.",
            },
            status_code=404,
        )

    # Build the resource identifier from the request URL (scheme + host)
    resource = f"{request.url.scheme}://{request.url.netloc}"

    # Authorization servers: use the configured issuer
    authorization_servers: list[str] = []
    if auth_cfg.issuer:
        authorization_servers.append(auth_cfg.issuer)

    metadata: dict[str, Any] = {
        "resource": resource,
        "authorization_servers": authorization_servers,
        "bearer_methods_supported": ["header"],
    }

    # Include audience if configured
    if auth_cfg.audience:
        metadata["resource_documentation"] = None  # reserved field
        metadata["scopes_supported"] = []

    return JSONResponse(metadata, status_code=200)
