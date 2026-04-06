"""Payload limits middleware.

Pure ASGI middleware (no ``BaseHTTPMiddleware``).  Enforces:

* Maximum request body size (default 1 MB).
* Maximum JSON nesting depth (default 20 levels).

Requests exceeding these limits receive a ``413 Payload Too Large`` or
``400 Bad Request`` response before reaching the application.
"""

import json as _json
import logging
from typing import List, Optional

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from argus_mcp.config.schema_security import PayloadLimitsConfig

logger = logging.getLogger(__name__)


def _check_json_depth(data: object, max_depth: int, current: int = 0) -> bool:
    """Return True if *data* exceeds *max_depth* nesting levels."""
    if current > max_depth:
        return True
    if isinstance(data, dict):
        return any(_check_json_depth(v, max_depth, current + 1) for v in data.values())
    if isinstance(data, list):
        return any(_check_json_depth(v, max_depth, current + 1) for v in data)
    return False


class PayloadLimitsMiddleware:
    """Pure ASGI middleware that enforces body size and JSON depth limits.

    The middleware buffers the incoming request body and validates it
    *before* passing the request to the inner application.

    Usage::

        middleware = PayloadLimitsMiddleware(app, config=PayloadLimitsConfig())
    """

    def __init__(self, app: ASGIApp, config: Optional[PayloadLimitsConfig] = None) -> None:
        self.app = app
        self._config = config or PayloadLimitsConfig()

        if self._config.enabled:
            logger.info(
                "Payload limits middleware ENABLED: max body %d bytes, max JSON depth %d.",
                self._config.max_body_bytes,
                self._config.max_json_depth,
            )
        else:
            logger.info("Payload limits middleware DISABLED.")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._config.enabled:
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET").upper()
        # Skip body checks for methods that don't carry a body.
        if method in ("GET", "HEAD", "OPTIONS", "DELETE"):
            await self.app(scope, receive, send)
            return

        # Buffer body for size + depth validation
        body_chunks: List[bytes] = []
        total_size = 0
        body_done = False

        async def buffering_receive():
            nonlocal total_size, body_done
            message = await receive()
            if message.get("type") == "http.request":
                chunk = message.get("body", b"")
                total_size += len(chunk)
                if total_size > self._config.max_body_bytes:
                    raise _PayloadTooLarge(total_size, self._config.max_body_bytes)
                body_chunks.append(chunk)
                if not message.get("more_body", False):
                    body_done = True
            return message

        try:
            # Consume body through wrapper to enforce size limit
            # Then replay the full body to the inner app
            while not body_done:
                await buffering_receive()
        except _PayloadTooLarge as exc:
            logger.warning(
                "Payload too large from %s on %s: %d bytes (limit %d)",
                _client_ip(scope),
                scope.get("path", "/"),
                exc.received,
                exc.limit,
            )
            response = JSONResponse(
                {
                    "error": "payload_too_large",
                    "message": f"Request body exceeds {exc.limit} byte limit.",
                },
                status_code=413,
            )
            await response(scope, receive, send)
            return

        full_body = b"".join(body_chunks)

        # JSON depth check
        if full_body and self._is_json_content(scope):
            try:
                parsed = _json.loads(full_body)
            except (ValueError, TypeError):
                pass  # malformed JSON — let the app layer handle it
            else:
                if _check_json_depth(parsed, self._config.max_json_depth):
                    logger.warning(
                        "JSON nesting depth exceeded from %s on %s (limit %d)",
                        _client_ip(scope),
                        scope.get("path", "/"),
                        self._config.max_json_depth,
                    )
                    response = JSONResponse(
                        {
                            "error": "bad_request",
                            "message": f"JSON nesting depth exceeds {self._config.max_json_depth} level limit.",
                        },
                        status_code=400,
                    )
                    await response(scope, receive, send)
                    return

        # Replay the buffered body to the inner app
        body_sent = False

        async def replay_receive():
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": full_body, "more_body": False}
            return await receive()

        await self.app(scope, replay_receive, send)

    @staticmethod
    def _is_json_content(scope: Scope) -> bool:
        """Check if the request Content-Type indicates JSON."""
        for key, value in scope.get("headers", []):
            if key == b"content-type":
                return b"json" in value.lower()
        return False


class _PayloadTooLarge(Exception):
    """Internal sentinel raised when body exceeds size limit."""

    def __init__(self, received: int, limit: int) -> None:
        self.received = received
        self.limit = limit


def _client_ip(scope: Scope) -> str:
    client = scope.get("client")
    return client[0] if client else "unknown"
