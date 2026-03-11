"""Argus runtime service — lifecycle management with state machine.

ArgusService owns the ClientManager and CapabilityRegistry instances and
manages the full startup/shutdown sequence.  It does NOT import the display
layer; status information is available via properties so that callers
(lifespan.py, management API) can render it however they choose.
"""

import asyncio
import logging
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

import yaml
from mcp import types as mcp_types

from argus_mcp.bridge.capability_registry import CapabilityRegistry
from argus_mcp.bridge.client_manager import ClientManager
from argus_mcp.bridge.conflict import create_strategy
from argus_mcp.bridge.health import HealthChecker
from argus_mcp.config import load_and_validate_config
from argus_mcp.config.diff import compute_diff
from argus_mcp.config.loader import load_argus_config
from argus_mcp.constants import RECONNECT_TIMEOUT, SERVER_NAME, SERVER_VERSION, SHUTDOWN_TIMEOUT
from argus_mcp.errors import BackendServerError
from argus_mcp.runtime.models import (
    BackendInfo,
    CapabilityInfo,
    ServiceState,
    ServiceStatus,
    is_valid_transition,
)

logger = logging.getLogger(__name__)


class _InvalidStateTransition(Exception):
    """Raised internally when an illegal state transition is attempted."""

    def __init__(self, current: ServiceState, target: ServiceState) -> None:
        super().__init__(f"Invalid state transition: {current.value} → {target.value}")
        self.current = current
        self.target = target


class ArgusService:
    """Manages the full lifecycle of the Argus MCP server.

    State machine::

        PENDING ─► STARTING ─► RUNNING ─► STOPPING ─► STOPPED
                       │                                  │
                       └──────► ERROR ◄───────────────────┘
                                  │
                                  └──► STARTING  (restart)

    Usage::

        service = ArgusService()
        await service.start(config_path="/path/to/config.yaml")
        # ... server is running ...
        await service.stop()
    """

    # ── Initialisation ──────────────────────────────────────────────

    def __init__(self) -> None:
        self._state: ServiceState = ServiceState.PENDING
        self._started_at: Optional[datetime] = None
        self._error_message: Optional[str] = None
        self._config_path: Optional[str] = None
        self._config_data: Optional[Dict[str, Any]] = None

        # Bridge components
        self._manager: ClientManager = ClientManager()
        self._registry: CapabilityRegistry = CapabilityRegistry()
        self._health_checker: Optional[HealthChecker] = None
        self._group_manager: Optional[object] = None  # GroupManager, set during start

        # Config file watcher (started after RUNNING)
        self._config_watcher: Optional[Any] = None

        # Readiness signaling
        self._ready_event: asyncio.Event = asyncio.Event()

        # Reload lock (prevents concurrent reload/reconnect operations)
        self._reload_lock: asyncio.Lock = asyncio.Lock()

        # Capability snapshots (populated after discovery)
        self._tools: List[mcp_types.Tool] = []
        self._resources: List[mcp_types.Resource] = []
        self._prompts: List[mcp_types.Prompt] = []

        # Backend metadata (populated after connection)
        self._backends_total: int = 0
        self._backends_connected: int = 0

        # Event system
        self._events: deque[Dict[str, Any]] = deque(maxlen=500)
        self._event_subscribers: List[asyncio.Queue[Dict[str, Any]]] = []
        # Event IDs use uuid4 to avoid race conditions across concurrent callers

        logger.info("ArgusService initialized (state=%s).", self._state.value)

    # ── Properties ─────────────────────────────────────────────────

    @property
    def state(self) -> ServiceState:
        """Current service state."""
        return self._state

    @property
    def manager(self) -> ClientManager:
        """The underlying ClientManager instance."""
        return self._manager

    @property
    def registry(self) -> CapabilityRegistry:
        """The underlying CapabilityRegistry instance."""
        return self._registry

    @property
    def health_checker(self) -> Optional[HealthChecker]:
        """The background health checker (``None`` until service starts)."""
        return self._health_checker

    @property
    def group_manager(self) -> Optional[object]:
        """The GroupManager instance (``None`` until service starts)."""
        return self._group_manager

    @property
    def tools(self) -> List[mcp_types.Tool]:
        return list(self._tools)

    @property
    def resources(self) -> List[mcp_types.Resource]:
        return list(self._resources)

    @property
    def prompts(self) -> List[mcp_types.Prompt]:
        return list(self._prompts)

    @property
    def backends_total(self) -> int:
        return self._backends_total

    @property
    def backends_connected(self) -> int:
        return self._backends_connected

    @property
    def config_data(self) -> Optional[Dict[str, Any]]:
        """Raw config data loaded from disk (read-only snapshot)."""
        return self._config_data

    @property
    def started_at(self) -> Optional[datetime]:
        return self._started_at

    @property
    def error_message(self) -> Optional[str]:
        return self._error_message

    @property
    def is_running(self) -> bool:
        return self._state == ServiceState.RUNNING

    # ── State Machine ──────────────────────────────────────────────

    def _build_registry(self) -> CapabilityRegistry:
        """Create a new CapabilityRegistry with the current conflict strategy."""
        if self._config_path:
            try:
                full_cfg = load_argus_config(self._config_path)
                cr = full_cfg.conflict_resolution
                strategy = create_strategy(
                    strategy=cr.strategy,
                    separator=cr.separator,
                    priority_order=cr.order if cr.order else None,
                )

                filters = self._build_capability_filters(full_cfg)
                rename_maps = self._build_rename_maps(full_cfg)
                cap_fetch_timeouts = self._build_cap_fetch_timeouts(full_cfg)

                return CapabilityRegistry(
                    conflict_strategy=strategy,
                    filters=filters if filters else None,
                    rename_maps=rename_maps if rename_maps else None,
                    cap_fetch_timeouts=cap_fetch_timeouts if cap_fetch_timeouts else None,
                )
            except (OSError, yaml.YAMLError, AttributeError, KeyError, ValueError):
                logger.warning(
                    "Failed to load conflict strategy/filters from config; using defaults.",
                    exc_info=True,
                )
        return CapabilityRegistry()

    @staticmethod
    def _build_capability_filters(
        full_cfg: Any,
    ) -> Dict[str, Any]:
        """Build per-server, per-capability-type filters from config."""
        from argus_mcp.bridge.filter import CapabilityFilter

        filters: Dict[str, Dict[str, CapabilityFilter]] = {}
        for name, backend in full_cfg.backends.items():
            f = backend.filters
            svr_filters: Dict[str, CapabilityFilter] = {}
            if f.tools.allow or f.tools.deny:
                svr_filters["tools"] = CapabilityFilter(allow=f.tools.allow, deny=f.tools.deny)
            if f.resources.allow or f.resources.deny:
                svr_filters["resources"] = CapabilityFilter(
                    allow=f.resources.allow, deny=f.resources.deny
                )
            if f.prompts.allow or f.prompts.deny:
                svr_filters["prompts"] = CapabilityFilter(
                    allow=f.prompts.allow, deny=f.prompts.deny
                )
            if svr_filters:
                filters[name] = svr_filters
        return filters

    @staticmethod
    def _build_rename_maps(full_cfg: Any) -> Dict[str, Any]:
        """Build per-server rename maps from tool_overrides."""
        from argus_mcp.bridge.rename import RenameMap

        rename_maps: Dict[str, RenameMap] = {}
        for name, backend in full_cfg.backends.items():
            if backend.tool_overrides:
                overrides: Dict[str, Dict[str, str]] = {}
                for k, v in backend.tool_overrides.items():
                    entry: Dict[str, str] = {}
                    if v.name is not None:
                        entry["name"] = v.name
                    if v.description is not None:
                        entry["description"] = v.description
                    overrides[k] = entry
                rename_maps[name] = RenameMap(overrides=overrides)
        return rename_maps

    @staticmethod
    def _build_cap_fetch_timeouts(full_cfg: Any) -> Dict[str, float]:
        """Build per-server capability fetch timeouts."""
        cap_fetch_timeouts: Dict[str, float] = {}
        for name, backend in full_cfg.backends.items():
            if backend.timeouts.cap_fetch is not None:
                cap_fetch_timeouts[name] = backend.timeouts.cap_fetch
        return cap_fetch_timeouts

    def _build_group_manager(self, config: Dict[str, Any]) -> object:
        """Build a :class:`GroupManager` from per-backend ``group`` fields."""
        from argus_mcp.bridge.groups import GroupManager

        if self._config_path:
            try:
                full_cfg = load_argus_config(self._config_path)
                return GroupManager(full_cfg.backends)
            except (OSError, yaml.YAMLError, AttributeError, KeyError, ValueError):
                logger.warning(
                    "Failed to build GroupManager from config; using empty.",
                    exc_info=True,
                )
        return GroupManager({})

    def _transition(self, target: ServiceState) -> None:
        """Transition to *target* state if the move is valid."""
        if not is_valid_transition(self._state, target):
            raise _InvalidStateTransition(self._state, target)
        prev = self._state
        self._state = target
        logger.info("Service state: %s → %s", prev.value, target.value)
        self.emit_event(
            "status",
            f"State changed: {prev.value} → {target.value}",
            severity="info",
        )

    # ── Lifecycle: start ───────────────────────────────────────────

    async def start(
        self,
        config_path: str,
        progress_callback: "Callable[..., None] | None" = None,
    ) -> None:
        """Execute the full startup sequence.

        1. Load and validate configuration
        2. Connect to backend MCP servers
        3. Discover and register capabilities

        Parameters
        ----------
        config_path:
            Path to the YAML configuration file.
        progress_callback:
            Optional callback ``(name, phase, message=None)`` invoked on
            backend phase transitions (used by the verbose installer display).

        Raises:
            ConfigurationError: If config loading/validation fails.
            BackendServerError: If no backends can be connected.
            _InvalidStateTransition: If called in a state that cannot transition to STARTING.
        """
        self._transition(ServiceState.STARTING)
        self._error_message = None
        self._config_path = config_path

        try:
            # --- Phase 1: Config ------------------------------------------
            logger.info("Loading configuration: %s", config_path)
            self.emit_event("config", f"Loading configuration: {config_path}")
            config = await asyncio.to_thread(load_and_validate_config, config_path)
            self._config_data = config
            self._backends_total = len(config)
            logger.info("Configuration loaded: %d backend(s) defined.", self._backends_total)
            self.emit_event(
                "config",
                f"Configuration loaded: {self._backends_total} backend(s) defined.",
            )

            # Build conflict strategy from full config (needs v1 envelope).
            self._registry = self._build_registry()

            # Build server group manager from per-backend group fields.
            self._group_manager = self._build_group_manager(config)

            # --- Phase 2: Connect backends --------------------------------
            logger.info("Connecting %d backend service(s)...", self._backends_total)
            self.emit_event(
                "backend_init",
                f"Connecting {self._backends_total} backend service(s)...",
            )

            # Wrap progress_callback to also emit events for TUI visibility
            def _event_progress_cb(name: str, phase: str, message: str | None = None) -> None:
                """Bridge backend progress to the event system."""
                severity = "info"
                if phase == "failed":
                    severity = "error"
                elif phase == "retrying":
                    severity = "warning"
                stage = f"backend_{phase}"
                msg = message or phase
                self.emit_event(stage, f"[{name}] {msg}", severity=severity, backend=name)
                # Also call original callback if provided
                if progress_callback is not None:
                    progress_callback(name, phase, message)

            await self._manager.start_all(config, progress_callback=_event_progress_cb)
            active_sessions = self._manager.get_all_sessions()
            self._backends_connected = len(active_sessions)

            if self._backends_connected == 0 and self._backends_total > 0:
                raise BackendServerError(
                    f"Unable to connect to any backend server "
                    f"({self._backends_total} configured). Server cannot start."
                )

            logger.info(
                "Backend connections: %d/%d active.",
                self._backends_connected,
                self._backends_total,
            )
            self.emit_event(
                "backend_connected",
                f"Backend connections: {self._backends_connected}/{self._backends_total} active.",
            )

            # --- Start background token refresh service -------------------
            try:
                full_cfg = load_argus_config(self._config_path)
                server_settings = full_cfg.server
                self._manager.start_refresh_service(
                    enabled=server_settings.auth_background_refresh_enabled,
                    interval=server_settings.auth_background_refresh_interval_seconds,
                )
            except Exception:  # noqa: BLE001
                logger.debug("Could not start background token refresh.", exc_info=True)

            # --- Phase 3: Discover capabilities ---------------------------
            if self._backends_connected > 0:
                logger.info("Discovering capabilities...")
                await self._registry.discover_and_register(active_sessions)
                self._tools = self._registry.get_aggregated_tools()
                self._resources = self._registry.get_aggregated_resources()
                self._prompts = self._registry.get_aggregated_prompts()
                logger.info(
                    "Capabilities discovered: %d tool(s), %d resource(s), %d prompt(s).",
                    len(self._tools),
                    len(self._resources),
                    len(self._prompts),
                )
                self.emit_event(
                    "capability_change",
                    f"Capabilities: {len(self._tools)} tools, "
                    f"{len(self._resources)} resources, {len(self._prompts)} prompts.",
                )
            else:
                logger.info("No active backends — skipping capability discovery.")

            # --- Transition to RUNNING ------------------------------------
            self._started_at = datetime.now(timezone.utc)
            self._transition(ServiceState.RUNNING)
            self._ready_event.set()

            # --- Start health checker ------------------------------------
            self._health_checker = HealthChecker(
                manager=self._manager,
                registry=self._registry,
                on_state_change=self._on_health_change,
            )
            self._health_checker.start()

            # --- Start config file watcher --------------------------------
            if self._config_path:
                from argus_mcp.config.watcher import ConfigWatcher

                self._config_watcher = ConfigWatcher(
                    config_path=self._config_path,
                    on_change=self._on_config_file_changed,
                )
                self._config_watcher.start()

            logger.info("ArgusService is RUNNING.")

        except Exception as exc:  # noqa: BLE001
            self._error_message = f"{type(exc).__name__}: {exc}"
            self._transition(ServiceState.ERROR)
            self._ready_event.clear()
            raise

    # ── Lifecycle: stop ────────────────────────────────────────────

    async def stop(self) -> None:
        """Execute the full shutdown sequence.

        Stops all backend connections and transitions to STOPPED.
        Safe to call even if the service never reached RUNNING (e.g. after
        a startup failure) — in that case, cleanup is still attempted.
        """
        # Allow stop from RUNNING or ERROR (cleanup after failed start).
        if self._state in (ServiceState.RUNNING, ServiceState.ERROR):
            self._transition(ServiceState.STOPPING)
        elif self._state == ServiceState.STARTING:
            # Edge case: stop called during startup (e.g. Ctrl-C).
            # Force transition through ERROR first to reach STOPPING.
            self._state = ServiceState.ERROR
            logger.warning("Stop requested while still STARTING — forcing ERROR state.")
            self._transition(ServiceState.STOPPING)
        elif self._state in (ServiceState.STOPPED, ServiceState.PENDING):
            logger.info(
                "Stop requested but service is already %s — nothing to do.",
                self._state.value,
            )
            return
        elif self._state == ServiceState.STOPPING:
            logger.warning("Stop already in progress — ignoring duplicate call.")
            return

        try:
            logger.info("Stopping all backend connections...")
            if self._config_watcher is not None:
                await self._config_watcher.stop()
                self._config_watcher = None
            if self._health_checker is not None:
                await self._health_checker.stop()
                self._health_checker = None
            await self._manager.stop_all()
            logger.info("All backend connections stopped.")
            self._transition(ServiceState.STOPPED)
        except RuntimeError as e_rt:
            # anyio cancel-scope cross-task errors during forced shutdown
            logger.warning("Cancel scope error during shutdown (safe to ignore): %s", e_rt)
            self._transition(ServiceState.STOPPED)
        except Exception as exc:  # noqa: BLE001
            self._error_message = f"Shutdown error: {type(exc).__name__}: {exc}"
            logger.exception("Error during shutdown: %s", exc)
            self._transition(ServiceState.ERROR)
        finally:
            self._ready_event.clear()

    # ── Lifecycle: reload ──────────────────────────────────────────

    async def reload(self) -> Dict[str, Any]:
        """Hot-reload config: re-read from disk, diff, and reconnect changed backends.

        Returns a dict with keys: reloaded, backends_added, backends_removed,
        backends_changed, errors.
        """
        if self._state != ServiceState.RUNNING:
            return {
                "reloaded": False,
                "backends_added": [],
                "backends_removed": [],
                "backends_changed": [],
                "errors": [f"Cannot reload in state: {self._state.value}"],
            }

        if self._config_path is None:
            return {
                "reloaded": False,
                "backends_added": [],
                "backends_removed": [],
                "backends_changed": [],
                "errors": ["No config path available."],
            }

        async with self._reload_lock:
            result: Dict[str, Any] = {
                "reloaded": False,
                "backends_added": [],
                "backends_removed": [],
                "backends_changed": [],
                "errors": [],
            }

            try:
                self.emit_event("config_reloaded", "Reloading configuration...")
                new_config = await asyncio.to_thread(load_and_validate_config, self._config_path)
            except (OSError, yaml.YAMLError, AttributeError, KeyError, ValueError) as exc:
                msg = f"Config reload failed: {type(exc).__name__}: {exc}"
                logger.error(msg)
                result["errors"].append(msg)
                self.emit_event("config_reloaded", msg, severity="error")
                return result

            old_config = self._config_data or {}

            diff = compute_diff(old_config, new_config)

            result["backends_added"] = sorted(diff.added)
            result["backends_removed"] = sorted(diff.removed)
            result["backends_changed"] = sorted(diff.changed)

            # Remove old backends
            for name in diff.removed:
                logger.info("Removing backend '%s' (no longer in config).", name)
                await self._disconnect_backend(name)

            # Reconnect changed backends
            for name in diff.changed:
                logger.info("Reconnecting changed backend '%s'.", name)
                await self._disconnect_backend(name)
                success = await self._connect_backend(name, new_config[name])
                if not success:
                    result["errors"].append(f"Failed to reconnect backend '{name}'.")

            # Add new backends
            for name in diff.added:
                logger.info("Adding new backend '%s'.", name)
                success = await self._connect_backend(name, new_config[name])
                if not success:
                    result["errors"].append(f"Failed to connect new backend '{name}'.")

            # Update internal state
            self._config_data = new_config
            self._backends_total = len(new_config)
            self._backends_connected = self._manager.get_active_session_count()

            # Re-discover capabilities
            active_sessions = self._manager.get_all_sessions()
            if active_sessions:
                self._registry = self._build_registry()
                await self._registry.discover_and_register(active_sessions)
                self._tools = self._registry.get_aggregated_tools()
                self._resources = self._registry.get_aggregated_resources()
                self._prompts = self._registry.get_aggregated_prompts()

            result["reloaded"] = True
            self.emit_event(
                "config_reloaded",
                f"Config reloaded: {diff.summary()}",
            )
            logger.info(
                "Config reloaded: added=%s removed=%s changed=%s errors=%s",
                result["backends_added"],
                result["backends_removed"],
                result["backends_changed"],
                result["errors"],
            )
            return result

    async def _on_config_file_changed(self) -> None:
        """Callback for :class:`ConfigWatcher` — triggers a reload."""
        import hashlib
        from pathlib import Path

        logger.info("Config file change detected by watcher, invoking reload...")

        # Compute config hash for the sync widget
        config_hash = ""
        if self._config_path:
            try:
                raw = await asyncio.to_thread(Path(self._config_path).read_bytes)
                config_hash = hashlib.sha256(raw).hexdigest()
            except OSError:
                pass

        result = await self.reload()

        # Emit a config_sync event for the TUI SyncStatusWidget
        has_errors = bool(result.get("errors"))
        self.emit_event(
            stage="config_sync",
            message=(
                "Config reloaded with errors" if has_errors else "Config reloaded successfully"
            ),
            severity="warning" if has_errors else "info",
            details={
                "type": "changed" if not has_errors else "error",
                "config_file": self._config_path or "",
                "config_hash": config_hash,
                "reloaded": result.get("reloaded", False),
                "backends_added": result.get("backends_added", []),
                "backends_removed": result.get("backends_removed", []),
                "errors": result.get("errors", []),
            },
        )

        if has_errors:
            logger.warning("Auto-reload completed with errors: %s", result["errors"])

    # ── Lifecycle: reconnect single backend ────────────────────────

    async def reconnect_backend(self, name: str) -> Dict[str, Any]:
        """Disconnect and reconnect a single backend by name.

        Returns a dict with keys: name, reconnected, error.
        Applies a configurable timeout (``server.management.reconnect_timeout``
        in config, falling back to :data:`RECONNECT_TIMEOUT`).
        """
        if self._state != ServiceState.RUNNING:
            return {
                "name": name,
                "reconnected": False,
                "error": f"Cannot reconnect in state: {self._state.value}",
            }

        if not self._config_data or name not in self._config_data:
            return {
                "name": name,
                "reconnected": False,
                "error": f"Backend '{name}' not found in configuration.",
            }

        timeout: float = RECONNECT_TIMEOUT
        if self._config_path:
            try:
                cfg = load_argus_config(self._config_path)
                if cfg.server.management.reconnect_timeout is not None:
                    timeout = cfg.server.management.reconnect_timeout
            except Exception:  # noqa: BLE001
                pass  # fall back to constant

        async with self._reload_lock:
            try:
                return await asyncio.wait_for(
                    self._do_reconnect(name),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    "Reconnect '%s' timed out after %.1fs.",
                    name,
                    timeout,
                )
                try:
                    await self._disconnect_backend(name)
                except Exception:  # noqa: BLE001
                    pass
                self._backends_connected = self._manager.get_active_session_count()
                return {
                    "name": name,
                    "reconnected": False,
                    "error": f"Reconnect timed out after {timeout}s.",
                }
            except Exception as exc:  # noqa: BLE001
                msg = f"{type(exc).__name__}: {exc}"
                logger.error("Reconnect '%s' failed: %s", name, msg)
                return {"name": name, "reconnected": False, "error": msg}

    async def _do_reconnect(self, name: str) -> Dict[str, Any]:
        """Inner reconnect logic — must be called under ``_reload_lock``."""
        self.emit_event(
            "backend_disconnected",
            f"Reconnecting backend '{name}'...",
            backend=name,
        )
        await self._disconnect_backend(name)
        assert self._config_data is not None  # guard: caller checks
        success = await self._connect_backend(name, self._config_data[name])

        if success:
            active_sessions = self._manager.get_all_sessions()
            self._registry = self._build_registry()
            await self._registry.discover_and_register(active_sessions)
            self._tools = self._registry.get_aggregated_tools()
            self._resources = self._registry.get_aggregated_resources()
            self._prompts = self._registry.get_aggregated_prompts()
            self._backends_connected = self._manager.get_active_session_count()
            self.emit_event(
                "backend_connected",
                f"Backend '{name}' reconnected.",
                backend=name,
            )
            return {"name": name, "reconnected": True, "error": None}

        self._backends_connected = self._manager.get_active_session_count()
        return {
            "name": name,
            "reconnected": False,
            "error": f"Failed to reconnect backend '{name}'.",
        }

    # ── Lifecycle: re-authenticate single backend ──────────────────

    async def reauth_backend(self, name: str) -> Dict[str, Any]:
        """Trigger interactive re-authentication for a single backend.

        Returns a dict with keys: name, reauth_initiated, error.
        Only PKCE-based providers support interactive re-auth.
        """
        if self._state != ServiceState.RUNNING:
            return {
                "name": name,
                "reauth_initiated": False,
                "error": f"Cannot re-authenticate in state: {self._state.value}",
            }

        if not self._config_data or name not in self._config_data:
            return {
                "name": name,
                "reauth_initiated": False,
                "error": f"Backend '{name}' not found in configuration.",
            }

        provider = self._manager._auth_providers.get(name)
        if provider is None:
            return {
                "name": name,
                "reauth_initiated": False,
                "error": f"Backend '{name}' has no auth provider.",
            }

        if not hasattr(provider, "trigger_reauth"):
            return {
                "name": name,
                "reauth_initiated": False,
                "error": f"Backend '{name}' does not support interactive re-auth.",
            }

        try:
            await provider.trigger_reauth()
            self.emit_event(
                "backend_reauth",
                f"Re-authentication completed for backend '{name}'.",
                backend=name,
            )
            return {"name": name, "reauth_initiated": True, "error": None}
        except Exception as exc:  # noqa: BLE001
            msg = f"{type(exc).__name__}: {exc}"
            logger.error("Re-auth for '%s' failed: %s", name, msg)
            return {"name": name, "reauth_initiated": False, "error": msg}

    # ── Lifecycle: shutdown (from API) ─────────────────────────────

    async def shutdown(self, timeout_seconds: int = SHUTDOWN_TIMEOUT) -> None:
        """Initiate graceful shutdown from the management API.

        Calls ``stop()`` with a timeout wrapper. If the stop doesn't
        complete in time, forces transition to ERROR state.
        """
        self.emit_event("status", "Shutdown requested via management API.")
        try:
            await asyncio.wait_for(self.stop(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            logger.error("Shutdown timed out after %ds — forcing ERROR state.", timeout_seconds)
            self._error_message = f"Shutdown timed out after {timeout_seconds}s"
            self._state = ServiceState.ERROR

    # ── Internal: backend connect/disconnect helpers ──────────────

    async def _disconnect_backend(self, name: str) -> None:
        """Disconnect a single backend by name.

        Delegates to ``ClientManager.disconnect_one()`` which properly
        closes the per-backend ``AsyncExitStack`` — tearing down the MCP
        session, transport streams, and any subprocess spawned for this
        backend.  This prevents the subprocess / resource leak identified
        the subprocess / resource leak that occurs without proper cleanup.
        """
        session = self._manager.get_session(name)
        if session is not None:
            await self._manager.disconnect_one(name)
        else:
            logger.debug("Backend '%s' was not connected — nothing to disconnect.", name)

    async def _connect_backend(self, name: str, config: Dict[str, Any]) -> bool:
        """Connect a single backend. Returns True on success."""
        try:
            success = await self._manager._start_backend_svr(name, config)
            return success
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to connect backend '%s': %s", name, exc)
            return False

    # ── Status reporting ──────────────────────────────────────────

    def get_status(self) -> ServiceStatus:
        """Build a snapshot of the current service status."""
        caps = CapabilityInfo(
            tools_count=len(self._tools),
            resources_count=len(self._resources),
            prompts_count=len(self._prompts),
            tool_names=[t.name for t in self._tools],
            resource_names=[r.name if hasattr(r, "name") else str(r.uri) for r in self._resources],
            prompt_names=[p.name for p in self._prompts],
            route_map=self._registry.get_route_map(),
        )

        backends: List[BackendInfo] = []
        if self._config_data:
            active_sessions = self._manager.get_all_sessions()
            for svr_name, svr_conf in self._config_data.items():
                backends.append(
                    BackendInfo(
                        name=svr_name,
                        type=svr_conf.get("type", "unknown"),
                        connected=svr_name in active_sessions,
                    )
                )

        status = ServiceStatus(
            state=self._state,
            server_name=SERVER_NAME,
            server_version=SERVER_VERSION,
            started_at=self._started_at,
            backends_total=self._backends_total,
            backends_connected=self._backends_connected,
            backends=backends,
            capabilities=caps,
            error_message=self._error_message,
            config_path=self._config_path,
        )
        status.compute_uptime()
        return status

    # ── Health change callback ────────────────────────────────────

    def _on_health_change(self, backend: str, old_state: Any, new_state: Any) -> None:
        """Called by HealthChecker when a backend's health state changes."""
        sev = "warning" if new_state.value == "unhealthy" else "info"
        self.emit_event(
            stage="health",
            message=f"Backend '{backend}': {old_state.value} → {new_state.value}",
            severity=sev,
            backend=backend,
            details={"old": old_state.value, "new": new_state.value},
        )

    # ── Event system ──────────────────────────────────────────────

    def emit_event(
        self,
        stage: str,
        message: str,
        *,
        severity: str = "info",
        backend: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Emit an event to the buffer and all subscribers."""
        event: Dict[str, Any] = {
            "id": f"evt-{uuid.uuid4().hex[:12]}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stage": stage,
            "message": message,
            "severity": severity,
            "backend": backend,
            "details": details,
        }
        self._events.append(event)
        for queue in self._event_subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # drop events for slow consumers
        return event

    def get_events(
        self,
        *,
        limit: int = 100,
        since: Optional[str] = None,
        severity: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Return recent events, optionally filtered."""
        result = list(self._events)
        if since:
            result = [e for e in result if e["timestamp"] > since]
        if severity:
            result = [e for e in result if e["severity"] == severity]
        return result[-limit:]

    def subscribe(self) -> asyncio.Queue[Dict[str, Any]]:
        """Create a new event subscriber queue."""
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue(maxsize=256)
        self._event_subscribers.append(queue)
        logger.debug("Event subscriber added (total: %d).", len(self._event_subscribers))
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Dict[str, Any]]) -> None:
        """Remove an event subscriber queue."""
        try:
            self._event_subscribers.remove(queue)
            logger.debug("Event subscriber removed (total: %d).", len(self._event_subscribers))
        except ValueError:
            pass

    # ── Readiness ─────────────────────────────────────────────────

    async def wait_until_ready(self, timeout: Optional[float] = None) -> bool:
        """Block until the service reaches RUNNING state.

        Returns ``True`` if the service is ready, ``False`` on timeout.
        """
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False
