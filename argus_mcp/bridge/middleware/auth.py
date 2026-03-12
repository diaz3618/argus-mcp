"""Authentication middleware for the MCP data plane.

Validates incoming requests via the configured auth provider and
injects :class:`UserIdentity` into ``ctx.metadata["user"]``.

Slot order in the chain: **AUTH → Audit → Recovery → Routing**.

Two enforcement modes are supported:

* **strict** (default) — reject unauthenticated requests.
* **permissive** — allow unauthenticated requests through with an
  anonymous identity, but *never* silently downgrade an invalid bearer
  token.  A malformed or expired token is rejected even in permissive
  mode to prevent credential-confusion attacks.
"""

from __future__ import annotations

import logging
from typing import Any, Literal, Optional

from argus_mcp.bridge.middleware.chain import MCPHandler, RequestContext
from argus_mcp.server.auth.providers import (
    AuthenticationError,
    AuthProviderRegistry,
    UserIdentity,
)

logger = logging.getLogger(__name__)


class AuthMiddleware:
    """MCP middleware that validates bearer tokens on incoming requests.

    Parameters
    ----------
    provider_registry:
        The :class:`AuthProviderRegistry` to delegate auth to.
    auth_mode:
        ``"strict"`` rejects unauthenticated requests.
        ``"permissive"`` injects an anonymous identity when no token is
        present but still rejects **invalid** tokens.
    """

    def __init__(
        self,
        provider_registry: AuthProviderRegistry,
        auth_mode: Literal["strict", "permissive"] = "strict",
    ) -> None:
        self._registry = provider_registry
        self._auth_mode: Literal["strict", "permissive"] = auth_mode

    async def __call__(self, ctx: RequestContext, next_handler: MCPHandler) -> Any:
        """Extract token from context, authenticate, and continue chain."""
        token: Optional[str] = ctx.metadata.get("auth_token")

        if token is not None:
            # A token was presented — ALWAYS validate it regardless of mode.
            # Invalid tokens must never silently downgrade to anonymous.
            try:
                user = await self._registry.authenticate(token)
            except AuthenticationError as exc:
                logger.warning(
                    "Auth failed for request %s (%s): %s",
                    ctx.request_id,
                    ctx.capability_name,
                    exc,
                )
                raise
        elif self._auth_mode == "permissive":
            # No token + permissive → anonymous pass-through
            user = UserIdentity(provider="anonymous")
            logger.debug(
                "Permissive auth: anonymous access for request %s (%s)",
                ctx.request_id,
                ctx.capability_name,
            )
        else:
            # No token + strict → delegate to provider (which will reject)
            try:
                user = await self._registry.authenticate(token)
            except AuthenticationError as exc:
                logger.warning(
                    "Auth failed for request %s (%s): %s",
                    ctx.request_id,
                    ctx.capability_name,
                    exc,
                )
                raise

        # Inject user identity for downstream middleware (audit, authz)
        ctx.metadata["user"] = user
        ctx.metadata["auth_mode"] = self._auth_mode
        if user.subject:
            ctx.metadata["user_subject"] = user.subject

        return await next_handler(ctx)
