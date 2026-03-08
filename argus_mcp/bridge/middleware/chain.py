"""Core middleware chain infrastructure.

Defines the request context, handler/middleware protocols, and the
chain builder that composes middleware into a single async handler.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional, Protocol

# ── Type protocol ────────────────────────────────────────────────────────


class MCPHandler(Protocol):
    """Async callable that takes a RequestContext and returns a result."""

    async def __call__(self, ctx: RequestContext) -> Any: ...


class MCPMiddleware(Protocol):
    """Async callable that wraps the next handler in the chain."""

    async def __call__(self, ctx: RequestContext, next_handler: MCPHandler) -> Any: ...


# ── Request context ─────────────────────────────────────────────────────


@dataclass
class RequestContext:
    """Per-request metadata bag threaded through the middleware chain.

    Attributes:
        request_id: Unique identifier for this request.
        capability_name: The exposed capability name requested by the client.
        mcp_method: MCP method (``call_tool``, ``read_resource``, ``get_prompt``).
        arguments: Optional arguments for the call.
        server_name: Backend server name (populated by routing middleware).
        original_name: Original capability name at the backend (populated by routing).
        start_time: High-resolution monotonic timestamp.
        metadata: Arbitrary key–value store for middleware to attach data.
        error: Set by recovery middleware if an exception was caught.
    """

    capability_name: str
    mcp_method: str
    arguments: Optional[Dict[str, Any]] = None
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    server_name: Optional[str] = None
    original_name: Optional[str] = None
    start_time: float = field(default_factory=time.monotonic)
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[Exception] = None

    @property
    def elapsed_ms(self) -> float:
        """Milliseconds since request start."""
        return (time.monotonic() - self.start_time) * 1000.0


# ── Chain builder ────────────────────────────────────────────────────────


def build_chain(
    middlewares: List[Any],
    handler: Any,
) -> Callable[[RequestContext], Awaitable[Any]]:
    """Compose *middlewares* around a final *handler*.

    Middleware are applied in list order: the first middleware in the list
    is the outermost wrapper (executed first for requests, last for
    responses).

    Args:
        middlewares: Callables conforming to :class:`MCPMiddleware`.
        handler: The innermost handler (typically routing middleware).

    Returns:
        An async callable ``(RequestContext) -> Any``.
    """
    chain = handler
    for mw in reversed(middlewares):
        next_handler = chain

        async def _wrap(
            ctx: RequestContext,
            _mw: Any = mw,
            _next: Any = next_handler,
        ) -> Any:
            return await _mw(ctx, _next)

        chain = _wrap
    final: Callable[[RequestContext], Awaitable[Any]] = chain
    return final
