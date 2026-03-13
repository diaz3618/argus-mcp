"""Background token refresh service.

Periodically sweeps all registered auth providers and proactively
refreshes tokens that are near expiry — so requests never block
waiting for a fresh token.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, Optional

from argus_mcp.bridge.auth.provider import AuthProvider, StaticTokenProvider

logger = logging.getLogger(__name__)

# Type alias for the re-auth callback.  Receives (backend_name, reason).
ReAuthCallback = Callable[[str, str], None]


class AuthRefreshService:
    """Proactive background token refresh for all backend auth providers.

    The service iterates stored :class:`AuthProvider` instances and calls
    ``get_headers()`` on each non-static provider.  This triggers the
    provider's internal cache-check → refresh logic, keeping tokens warm.

    When a provider's ``get_headers()`` raises an exception, the service
    invokes the optional *on_reauth_required* callback so that the server
    or TUI can surface an interactive re-authentication prompt.
    """

    def __init__(
        self,
        auth_providers: Dict[str, Any],
        *,
        interval: float = 60.0,
        on_reauth_required: Optional[ReAuthCallback] = None,
    ) -> None:
        self._providers = auth_providers
        self._interval = max(5.0, interval)
        self._task: asyncio.Task[None] | None = None
        self._on_reauth_required = on_reauth_required

    def start(self) -> None:
        """Start the background refresh loop (idempotent)."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="auth-refresh-service")
        logger.info(
            "AuthRefreshService started (interval=%.1fs, providers=%d).",
            self._interval,
            len(self._providers),
        )

    async def stop(self) -> None:
        """Stop the background refresh loop gracefully."""
        if self._task is None or self._task.done():
            self._task = None
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("AuthRefreshService stopped.")

    @property
    def running(self) -> bool:
        """Whether the background task is currently active."""
        return self._task is not None and not self._task.done()

    async def _run(self) -> None:
        """Main loop — runs until cancelled."""
        while True:
            await asyncio.sleep(self._interval)
            await self._sweep()

    async def _sweep(self) -> None:
        """Refresh tokens for all non-static providers."""
        snapshot = list(self._providers.items())
        if not snapshot:
            return

        refreshed = 0
        for name, provider in snapshot:
            if not isinstance(provider, AuthProvider):
                continue
            if isinstance(provider, StaticTokenProvider):
                continue
            try:
                await provider.get_headers()
                refreshed += 1
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Background token refresh failed for backend '%s'.",
                    name,
                    exc_info=True,
                )
                if self._on_reauth_required is not None:
                    try:
                        self._on_reauth_required(
                            name,
                            f"Token refresh failed for backend '{name}'",
                        )
                    except Exception:  # noqa: BLE001
                        logger.debug(
                            "on_reauth_required callback error for '%s'.",
                            name,
                            exc_info=True,
                        )
        if refreshed:
            logger.debug("Background refresh sweep: %d provider(s) refreshed.", refreshed)
