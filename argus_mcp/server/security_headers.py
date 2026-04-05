"""Security headers middleware.

Pure ASGI middleware (no ``BaseHTTPMiddleware``).  Injects recommended
security response headers on every HTTP response:

* ``X-Content-Type-Options: nosniff``
* ``X-Frame-Options: DENY``
* ``Cache-Control: no-store``
* ``Content-Security-Policy: default-src 'none'``
* ``Strict-Transport-Security`` (TLS-only, configurable max-age)
"""

import logging
from typing import List, Optional, Tuple

from starlette.types import ASGIApp, Receive, Scope, Send

from argus_mcp.config.schema_security import SecurityHeadersConfig

logger = logging.getLogger(__name__)

# Headers injected on every response regardless of TLS status.
_STATIC_HEADERS: List[Tuple[bytes, bytes]] = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"cache-control", b"no-store"),
    (b"content-security-policy", b"default-src 'none'"),
]


class SecurityHeadersMiddleware:
    """Pure ASGI middleware that injects security response headers.

    Usage::

        middleware = SecurityHeadersMiddleware(app, config=SecurityHeadersConfig())
    """

    def __init__(self, app: ASGIApp, config: Optional[SecurityHeadersConfig] = None) -> None:
        self.app = app
        self._config = config or SecurityHeadersConfig()
        self._hsts_header: Optional[Tuple[bytes, bytes]] = None

        if self._config.enabled:
            self._hsts_header = (
                b"strict-transport-security",
                f"max-age={self._config.hsts_max_age}; includeSubDomains".encode(),
            )
            logger.info(
                "Security headers middleware ENABLED (HSTS max-age=%d).",
                self._config.hsts_max_age,
            )
        else:
            logger.info("Security headers middleware DISABLED.")

    def _is_tls(self, scope: Scope) -> bool:
        """Determine if the request arrived over TLS."""
        scheme = scope.get("scheme", "http")
        return scheme == "https"

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._config.enabled:
            await self.app(scope, receive, send)
            return

        is_tls = self._is_tls(scope)

        async def send_wrapper(message):
            if message.get("type") == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(_STATIC_HEADERS)
                if is_tls and self._hsts_header is not None:
                    headers.append(self._hsts_header)
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_wrapper)
