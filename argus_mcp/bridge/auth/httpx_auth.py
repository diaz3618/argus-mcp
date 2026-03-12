"""httpx.Auth integration for MCP backend authentication.

Provides :class:`McpBearerAuth`, a custom :class:`httpx.Auth` subclass
that injects ``Authorization: Bearer …`` headers on every outgoing
request and transparently retries once on HTTP 401 after invalidating
the cached token.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, AsyncGenerator

import httpx

if TYPE_CHECKING:
    from argus_mcp.bridge.auth.provider import AuthProvider

logger = logging.getLogger(__name__)

_MAX_401_RETRIES: int = 1


class McpBearerAuth(httpx.Auth):
    """Per-request bearer-token auth with automatic 401 retry.

    Wraps an :class:`AuthProvider` and uses the ``httpx.Auth`` flow
    protocol so that every HTTP request made by the MCP SDK transport
    gets a fresh ``Authorization`` header.  If the server responds with
    ``401 Unauthorized``, the cached token is invalidated, a new one is
    acquired, and the request is retried (at most once).

    Parameters
    ----------
    provider:
        The :class:`AuthProvider` that supplies bearer tokens.
    retry_on_401:
        When *False*, skip the automatic 401-retry logic.  Defaults to *True*.
    """

    requires_request_body = False
    requires_response_body = False

    def __init__(self, provider: AuthProvider, *, retry_on_401: bool = True) -> None:
        self._provider = provider
        self._retry_on_401 = retry_on_401

    async def async_auth_flow(
        self,
        request: httpx.Request,
    ) -> AsyncGenerator[httpx.Request, httpx.Response]:
        """Inject auth headers and retry on 401."""
        headers = await self._provider.get_headers()
        for key, value in headers.items():
            request.headers[key] = value
        response = yield request

        retries = 0
        while self._retry_on_401 and response.status_code == 401 and retries < _MAX_401_RETRIES:
            retries += 1
            logger.warning(
                "Received 401 from %s — invalidating token and retrying (%d/%d).",
                request.url.host,
                retries,
                _MAX_401_RETRIES,
            )
            self._provider.invalidate()
            headers = await self._provider.get_headers()
            for key, value in headers.items():
                request.headers[key] = value
            response = yield request
