"""Backend MCP server connection management.

This module is the **facade** that owns shared lifecycle state (sessions,
exit stacks, auth caches) and delegates to extracted helpers:

* :mod:`~argus_mcp.bridge.backend_connection` – per-backend connect / error handling
* :mod:`~argus_mcp.bridge.startup_coordinator` – staggered launch, retry loop
* :mod:`~argus_mcp.bridge.auth_discovery` – OAuth auto-discovery
* :mod:`~argus_mcp.bridge.transport_factory` – transport init
"""

import asyncio
import logging
import os
from contextlib import AsyncExitStack
from typing import TYPE_CHECKING, Any, Callable, Dict, Optional, Tuple

from mcp import ClientSession, StdioServerParameters

from argus_mcp.bridge import auth_discovery as ad
from argus_mcp.bridge import backend_connection as bc
from argus_mcp.bridge import startup_coordinator as sc

if TYPE_CHECKING:
    from argus_mcp.bridge.auth.refresh_service import ReAuthCallback

logger = logging.getLogger(__name__)


class ClientManager:
    """Manages connections and sessions for all backend MCP servers."""

    def __init__(self) -> None:
        self._sessions: Dict[str, ClientSession] = {}
        self._pending_tasks: Dict[str, asyncio.Task[Any]] = {}
        self._exit_stack = AsyncExitStack()
        self._backend_stacks: Dict[str, AsyncExitStack] = {}
        self._devnull = open(os.devnull, "w")  # noqa: SIM115  # single shared devnull for errlog
        self._status_records: Dict[str, Any] = {}
        self._progress_cb: Optional[Callable[..., None]] = None
        self._shutdown_requested: bool = False
        self._discovered_auth: Dict[str, Dict[str, Any]] = {}
        self._auth_discovery_tasks: Dict[str, asyncio.Task[Any]] = {}
        self._auth_providers: Dict[str, Any] = {}
        self._refresh_service: Optional[Any] = None
        logger.info("ClientManager initialized.")

    def cancel_startup(self) -> None:
        """Cancel all pending startup tasks (safe to call from signal handler)."""
        self._shutdown_requested = True
        cancelled = 0
        for task in list(self._pending_tasks.values()):
            if not task.done():
                task.cancel()
                cancelled += 1
        if cancelled:
            logger.info("cancel_startup: cancelled %d pending startup task(s).", cancelled)

    @staticmethod
    def _apply_network_env(
        svr_name: str,
        svr_conf: Dict[str, Any],
        params: StdioServerParameters,
    ) -> StdioServerParameters:
        """Inject HTTP_PROXY / NO_PROXY env vars from network isolation config."""
        return bc.apply_network_env(svr_name, svr_conf, params)

    async def _start_backend_svr(self, svr_name: str, svr_conf: Dict[str, Any]) -> bool:
        """Start and initialize a single backend server connection."""
        return await bc.start_backend_svr(
            svr_name,
            svr_conf,
            sessions=self._sessions,
            backend_stacks=self._backend_stacks,
            devnull=self._devnull,
            status_records=self._status_records,
            discovered_auth=self._discovered_auth,
            auth_discovery_tasks=self._auth_discovery_tasks,
            progress_cb=self._progress_cb,
            shutdown_requested=self._shutdown_requested,
            auth_providers=self._auth_providers,
        )

    async def _pre_build_container_image(self, svr_name: str, svr_conf: Dict[str, Any]) -> None:
        """Pre-build the container image for a stdio backend."""
        await bc.pre_build_container_image(svr_name, svr_conf, self._progress_cb)

    async def start_all(
        self,
        config_data: Dict[str, Dict[str, Any]],
        progress_callback: Optional[Callable[..., None]] = None,
    ) -> None:
        """Start all backend server connections, retrying failures."""
        await sc.start_all(
            config_data=config_data,
            start_one=self._start_backend_svr,
            pre_build=self._pre_build_container_image,
            sessions=self._sessions,
            pending_tasks=self._pending_tasks,
            status_records=self._status_records,
            auth_discovery_tasks=self._auth_discovery_tasks,
            progress_cb_holder=self,
            progress_callback=progress_callback,
            shutdown_requested_fn=lambda: self._shutdown_requested,
        )

    def start_refresh_service(
        self,
        *,
        enabled: bool = True,
        interval: float = 60.0,
        on_reauth_required: "ReAuthCallback | None" = None,
    ) -> None:
        """Start the background token refresh service.

        Parameters
        ----------
        enabled:
            If ``False`` the service is not started (config opt-out).
        interval:
            Seconds between refresh sweeps.
        on_reauth_required:
            Optional callback invoked when a background refresh fails
            and interactive re-authentication is needed.
        """
        if not enabled:
            logger.info("Background token refresh disabled by configuration.")
            return
        if not self._auth_providers:
            logger.debug("No auth providers registered — skipping refresh service.")
            return
        from argus_mcp.bridge.auth.refresh_service import AuthRefreshService

        self._refresh_service = AuthRefreshService(
            self._auth_providers,
            interval=interval,
            on_reauth_required=on_reauth_required,
        )
        self._refresh_service.start()

    async def _stop_refresh_service(self) -> None:
        """Stop the background refresh service if running."""
        if self._refresh_service is not None:
            await self._refresh_service.stop()
            self._refresh_service = None

    async def _cancel_pending_startup_tasks(self) -> None:
        """Cancel and await all pending backend startup tasks."""
        if not self._pending_tasks:
            return
        logger.info("Cancelling %s pending startup tasks...", len(self._pending_tasks))
        for task in self._pending_tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._pending_tasks.values(), return_exceptions=True)
        self._pending_tasks.clear()
        logger.info("Pending startup tasks cancelled and cleaned up.")

    async def _close_backend_stacks(self) -> None:
        """Close per-backend exit stacks (transport + session + subprocess)."""
        for name, stack in list(self._backend_stacks.items()):
            try:
                await asyncio.wait_for(stack.aclose(), timeout=5.0)
                logger.debug("Backend '%s' stack closed.", name)
            except asyncio.TimeoutError:
                logger.warning("Backend '%s' stack close timed out.", name)
            except RuntimeError as e_rt:
                logger.debug("Cancel scope error closing '%s': %s", name, e_rt)
            except Exception:  # noqa: BLE001
                logger.debug("Error closing backend '%s' stack.", name, exc_info=True)
        self._backend_stacks.clear()

    async def _close_global_exit_stack(self) -> None:
        """Close the global AsyncExitStack as a safety net."""
        logger.debug("Closing global AsyncExitStack as safety net...")
        try:
            await asyncio.wait_for(self._exit_stack.aclose(), timeout=10.0)
            logger.info("Global AsyncExitStack closed.")
        except asyncio.TimeoutError:
            logger.warning("Global AsyncExitStack.aclose() timed out after 10s.")
        except RuntimeError as e_rt:
            logger.warning("Cancel scope error during shutdown (safe to ignore): %s", e_rt)
        except Exception as e_aclose:  # noqa: BLE001
            logger.warning("Error while closing global AsyncExitStack: %s.", e_aclose)

    async def stop_all(self) -> None:
        """Close all active sessions and subprocesses started by the manager."""
        logger.info("Stopping all backend connections and local processes...")

        # Transition operational backends to SHUTTING_DOWN
        from argus_mcp.runtime.models import BackendPhase

        for name, rec in self._status_records.items():
            if rec.is_operational:
                try:
                    rec.transition(BackendPhase.SHUTTING_DOWN, "Graceful shutdown")
                except ValueError:
                    pass

        # Stop background token refresh before tearing down connections.
        await self._stop_refresh_service()

        await self._cancel_pending_startup_tasks()
        await self._close_backend_stacks()
        await self._close_global_exit_stack()

        self._sessions.clear()
        self._auth_providers.clear()

        # Remove any pre-created Docker containers
        try:
            from argus_mcp.bridge.container.wrapper import cleanup_all_containers

            await cleanup_all_containers()
        except Exception:  # noqa: BLE001
            logger.debug("Container cleanup during shutdown failed.", exc_info=True)

        # Close the shared devnull file
        if self._devnull is not None:
            try:
                self._devnull.close()
            except OSError:
                pass
            self._devnull = None

        logger.info("ClientManager closed, all sessions cleared.")

    async def disconnect_one(self, name: str) -> None:
        """Disconnect and clean up a single backend by name.

        Closes the per-backend :class:`AsyncExitStack` which tears down
        the transport, session, and any subprocess created for this
        backend.  This is the correct way to disconnect an individual
        backend (e.g. during reconnect) without leaking child processes.

        If no per-backend stack exists (legacy path), only the session
        reference is removed — a warning is logged since this may leak.
        """
        backend_stack = self._backend_stacks.pop(name, None)
        if backend_stack is not None:
            try:
                await asyncio.wait_for(backend_stack.aclose(), timeout=10.0)
                logger.info(
                    "Backend '%s' disconnected (stack closed, subprocess terminated).", name
                )
            except asyncio.TimeoutError:
                logger.warning("Backend '%s' disconnect timed out after 10s.", name)
            except RuntimeError as e_rt:
                logger.debug(
                    "Cancel scope error disconnecting '%s' (benign): %s",
                    name,
                    e_rt,
                )
            except Exception:  # noqa: BLE001
                logger.warning("Error disconnecting backend '%s'.", name, exc_info=True)
        else:
            logger.warning(
                "Backend '%s' has no per-backend exit stack — "
                "subprocess may leak (legacy code path).",
                name,
            )

        # Remove any pre-created Docker container for this backend.
        try:
            from argus_mcp.bridge.container.wrapper import cleanup_container

            await cleanup_container(name)
        except Exception:  # noqa: BLE001
            logger.debug(
                "Container cleanup for '%s' failed.",
                name,
                exc_info=True,
            )

        self._sessions.pop(name, None)
        self._auth_providers.pop(name, None)

    def get_session(self, svr_name: str) -> Optional[ClientSession]:
        """Get an active backend session by server name."""
        return self._sessions.get(svr_name)

    def get_active_session_count(self) -> int:
        """Get the number of active sessions."""
        return len(self._sessions)

    def get_all_sessions(self) -> Dict[str, ClientSession]:
        """Get a dictionary copy of all active sessions."""
        return self._sessions.copy()

    def get_status_record(self, svr_name: str) -> Optional[Any]:
        """Get the status record for a backend (or ``None``)."""
        return self._status_records.get(svr_name)

    async def _resolve_auth_headers(
        self, svr_name: str, svr_conf: Dict[str, Any]
    ) -> Optional[Dict[str, str]]:
        """Resolve outgoing-auth headers for a backend, if configured."""
        return await ad.resolve_auth_headers(svr_name, svr_conf, self._discovered_auth)

    async def _attempt_auth_discovery_for_backend(
        self,
        svr_name: str,
        svr_conf: Dict[str, Any],
        svr_type: Optional[str],
        default_reason: str,
    ) -> str:
        """Run OAuth auto-discovery for a backend, shielded from cancellation."""
        return await ad.attempt_auth_discovery(
            svr_name,
            svr_conf,
            svr_type,
            default_reason,
            self._auth_discovery_tasks,
            self._discovered_auth,
            self._progress_cb,
        )

    async def _try_auth_discovery(
        self,
        svr_name: str,
        svr_conf: Dict[str, Any],
    ) -> bool:
        """Attempt OAuth auto-discovery for a backend."""
        return await ad.try_auth_discovery(
            svr_name,
            svr_conf,
            self._discovered_auth,
            self._progress_cb,
        )

    async def _dynamic_register(
        self,
        svr_name: str,
        registration_endpoint: str,
        backend_url: str,
        redirect_uri: str = "",
    ) -> Tuple[str, str]:
        """Register a dynamic OAuth client (RFC 7591)."""
        return await ad.dynamic_register(
            svr_name,
            registration_endpoint,
            backend_url,
            redirect_uri,
        )


_looks_like_auth_failure = ad.looks_like_auth_failure
