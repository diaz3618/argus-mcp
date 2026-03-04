"""Application lifespan management - startup and shutdown sequences.

This module provides the Starlette ``lifespan`` async context manager that
delegates lifecycle management to :class:`~argus_mcp.runtime.ArgusService`.

The display/console status callbacks are kept here so that the runtime service
layer (``runtime/service.py``) remains presentation-agnostic and can be reused
by the management API (Phase 0.2).

**Signal Handling Note (Ctrl+C)**

Uvicorn's ``Server.capture_signals()`` context manager replaces *all*
SIGINT/SIGTERM handlers with its own ``handle_exit()`` before the lifespan
runs.  That means any signal handlers registered in ``cli.py`` are silently
overwritten and never fire.  Worse, ``handle_exit()`` merely sets boolean
flags (``should_exit`` / ``force_exit``) that are only polled in the main
serve-loop — they are *not* checked during the blocking
``await startup() → lifespan.startup()`` call.

The fix is the **Temporary Signal Override** pattern: inside ``app_lifespan``
we save uvicorn's current handler, install our own handler that (a) cancels
in-flight startup tasks and (b) raises ``SystemExit`` via ``os._exit`` on a
second press, then restore uvicorn's original handler before ``yield`` so
that normal graceful shutdown continues to work.

**Thread-safety**: Per the Python asyncio documentation
(https://docs.python.org/3/library/asyncio-dev.html#signals), calling
``task.cancel()`` from a POSIX signal handler installed via
``signal.signal()`` is **unsafe** because POSIX handlers execute in an
arbitrary thread context.  We therefore use ``loop.add_signal_handler()``
which schedules the callback within the event loop's thread.  On platforms
where ``loop.add_signal_handler()`` is unavailable (Windows), we fall back
to ``signal.signal()`` — acceptable since Windows SIGINT handling is
fundamentally different (Ctrl+C raises ``KeyboardInterrupt``).
"""

import asyncio
import logging
import os
import signal
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any, AsyncIterator, Optional

from starlette.applications import Starlette

from argus_mcp.constants import SERVER_NAME, SERVER_VERSION
from argus_mcp.display.console import (
    disp_console_status,
    gen_status_info,
    log_file_status,
)
from argus_mcp.display.installer import InstallerDisplay
from argus_mcp.errors import BackendServerError, ConfigurationError
from argus_mcp.runtime.service import ArgusService

logger = logging.getLogger(__name__)

DEFAULT_LOG_FPATH = "unknown_argus.log"
DEFAULT_LOG_LVL = "INFO"

# Directories to scan for workflow YAML files (relative to cwd or project root).
_WORKFLOW_YAML_DIRS = ("workflows", "examples/workflows")
_YAML_EXTS = (".yaml", ".yml")


def _discover_workflow_yamls() -> list[dict]:
    """Scan known directories for workflow YAML files and return parsed dicts."""
    from pathlib import Path

    results: list[dict] = []
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        logger.debug("pyyaml not installed — skipping YAML workflow discovery.")
        return results

    for rel_dir in _WORKFLOW_YAML_DIRS:
        d = Path(rel_dir)
        if not d.is_dir():
            d = Path(__file__).resolve().parents[2] / rel_dir
        if not d.is_dir():
            continue
        for fpath in sorted(d.iterdir()):
            if fpath.suffix in _YAML_EXTS and fpath.is_file():
                try:
                    data = yaml.safe_load(fpath.read_text(encoding="utf-8"))
                    if isinstance(data, dict) and data.get("name"):
                        data.setdefault("_source", str(fpath))
                        results.append(data)
                except Exception:
                    logger.debug("Failed to parse workflow YAML: %s", fpath, exc_info=True)
    return results


def _load_composite_workflows(mcp_svr_instance: Any, chain: Any) -> None:
    """Discover workflow YAML files and register them as composite tools.

    The ``invoke_tool`` callback delegates to the middleware chain so that
    composite tool steps benefit from audit, recovery, and routing middleware.
    """
    from argus_mcp.bridge.middleware.chain import RequestContext
    from argus_mcp.workflows.composite_tool import load_composite_tools

    wf_defs = _discover_workflow_yamls()
    if not wf_defs:
        mcp_svr_instance.composite_tools = []
        logger.debug("No composite workflow definitions found.")
        return

    async def _invoke_via_chain(tool_name: str, arguments: dict) -> Any:
        """Route a tool call through the middleware chain."""
        ctx = RequestContext(
            capability_name=tool_name,
            mcp_method="call_tool",
            arguments=arguments,
        )
        result = await chain(ctx)
        if ctx.error is not None:
            raise ctx.error
        return result

    tools = load_composite_tools(wf_defs, _invoke_via_chain)
    mcp_svr_instance.composite_tools = tools
    logger.info(
        "Loaded %d composite workflow tool(s): %s",
        len(tools),
        [t.name for t in tools],
    )


async def _attach_to_mcp_server(
    mcp_svr_instance: Any,
    service: ArgusService,
) -> None:
    """Attach bridge components from the service to the MCP server instance.

    This preserves the existing monkey-patch pattern (mcp_server.manager /
    mcp_server.registry) until it is properly replaced in a later phase.
    Also builds and attaches the middleware chain and optimizer index.
    """
    from argus_mcp.audit import AuditLogger
    from argus_mcp.bridge.middleware import (
        AuditMiddleware,
        RecoveryMiddleware,
        RoutingMiddleware,
        build_chain,
    )
    from argus_mcp.bridge.middleware.telemetry import TelemetryMiddleware
    from argus_mcp.bridge.optimizer import ToolIndex
    from argus_mcp.config.loader import load_argus_config
    from argus_mcp.config.schema import ArgusConfig

    mcp_svr_instance.manager = service.manager
    mcp_svr_instance.registry = service.registry

    # ── Load full config once (used by multiple sections below) ──────
    config_path = getattr(service, "_config_path", None)
    full_cfg: ArgusConfig | None = None
    if config_path:
        try:
            full_cfg = load_argus_config(config_path)
        except Exception:
            logger.debug(
                "Could not load full config; sub-features will use defaults.", exc_info=True
            )

    # ── Structured audit logger ──────────────────────────────────────
    audit_logger = AuditLogger()
    mcp_svr_instance.audit_logger = audit_logger

    # ── Telemetry initialization (Task 4.3 wiring) ───────────────────
    telemetry_enabled = False
    if full_cfg is not None and full_cfg.telemetry.enabled:
        try:
            from argus_mcp.telemetry.config import TelemetryConfig

            tel_config = TelemetryConfig(
                enabled=True,
                otlp_endpoint=full_cfg.telemetry.otlp_endpoint,
                service_name=full_cfg.telemetry.service_name,
            )
            tel_config.initialize()
            telemetry_enabled = True
            logger.info(
                "Telemetry initialized: endpoint=%s, service=%s",
                full_cfg.telemetry.otlp_endpoint,
                full_cfg.telemetry.service_name,
            )
        except Exception:
            logger.debug("Telemetry init failed; continuing without OTel.", exc_info=True)

    mcp_svr_instance.telemetry_enabled = telemetry_enabled

    # ── Middleware chain: Recovery → Telemetry (opt.) → Audit → Routing
    middlewares: list = [RecoveryMiddleware()]
    if telemetry_enabled:
        middlewares.append(TelemetryMiddleware())
    middlewares.append(AuditMiddleware(audit_logger=audit_logger))

    routing = RoutingMiddleware(service.registry, service.manager)
    chain = build_chain(middlewares=middlewares, handler=routing)
    mcp_svr_instance.middleware_chain = chain
    logger.info(
        "Middleware chain attached (telemetry=%s).",
        "enabled" if telemetry_enabled else "disabled",
    )

    # ── Optimizer ─────────────────────────────────────────
    optimizer_enabled = full_cfg.optimizer.enabled if full_cfg else False
    keep_list: list[str] = list(full_cfg.optimizer.keep_tools) if full_cfg else []

    mcp_svr_instance.optimizer_enabled = optimizer_enabled
    mcp_svr_instance.optimizer_keep_list = keep_list

    if optimizer_enabled:
        tool_index = ToolIndex()
        tools = service.registry.get_aggregated_tools()
        route_map = service.registry.get_route_map()
        await tool_index.store(tools, route_map)
        mcp_svr_instance.optimizer_index = tool_index
        logger.info(
            "Optimizer enabled: indexed %d tool(s), keep-list=%s.",
            tool_index.tool_count,
            keep_list or "(none)",
        )
    else:
        mcp_svr_instance.optimizer_index = None
        logger.debug("Optimizer disabled.")

    # ── Session Manager ───────────────────────────────────
    from argus_mcp.server.session import SessionManager

    session_manager = SessionManager()
    session_manager.start()
    mcp_svr_instance.session_manager = session_manager
    logger.info("SessionManager attached to mcp_server instance.")

    # ── Feature Flags ─────────────────────────────────────
    from argus_mcp.config.flags import FeatureFlags

    ff_overrides = dict(full_cfg.feature_flags) if full_cfg else {}
    mcp_svr_instance.feature_flags = FeatureFlags(ff_overrides)
    logger.info("Feature flags: %s", mcp_svr_instance.feature_flags)

    # Propagate container_isolation flag to env so the container
    # wrapper module can read it without direct FeatureFlags access.
    if not mcp_svr_instance.feature_flags.is_enabled("container_isolation"):
        os.environ.setdefault("ARGUS_CONTAINER_ISOLATION", "false")
        logger.info("Container isolation disabled via feature flag.")

    # ── Version Drift Detection (Task 5.4 wiring) ────────────────────
    from argus_mcp.bridge.version_checker import VersionChecker

    mcp_svr_instance.version_checker = VersionChecker()
    logger.info("VersionChecker attached (registry_client=None — drift available on demand).")

    # ── Skills Manager (Task 5.6 wiring) ─────────────────────────────
    from argus_mcp.skills.manager import SkillManager

    skill_manager = SkillManager()
    skill_manager.discover()
    mcp_svr_instance.skill_manager = skill_manager
    logger.info("SkillManager attached: %d skill(s) discovered.", len(skill_manager.list_skills()))

    # ── Composite Workflows (Task 6) ────────────────────────────────
    _load_composite_workflows(mcp_svr_instance, chain)


# ──────────────────────────────────────────────────────────────────────
# Startup-Phase Signal Override
# ──────────────────────────────────────────────────────────────────────

def _install_startup_signal_override(
    service: "ArgusService",
) -> tuple[Any, Any]:
    """Replace SIGINT/SIGTERM with handlers that cancel in-flight startup.

    Returns ``(original_sigint_handler, original_sigterm_handler)`` so the
    caller can restore them after startup completes.

    **Why this exists**: Uvicorn installs its own signal handlers *before*
    calling ``lifespan.startup()``.  Those handlers only set a flag that the
    main serve-loop polls — they do nothing while the lifespan is blocked
    on ``await service.start()``.  By temporarily overriding the handlers
    inside the lifespan we regain the ability to react to Ctrl+C during
    the (potentially very long) backend-connection phase.

    Behaviour:
    * **First Ctrl+C** — calls ``service._manager.cancel_startup()`` to
      cooperatively cancel all pending tasks, sets ``should_exit`` on the
      uvicorn server so it will exit after the lifespan returns, and prints
      a user-visible message.
    * **Second Ctrl+C** — calls ``os._exit(1)`` for an immediate hard exit,
      just like the user would expect from double Ctrl+C.

    **Thread-safety**: Uses ``loop.add_signal_handler()`` per Python asyncio
    docs (https://docs.python.org/3/library/asyncio-dev.html#signals) so
    that ``cancel_startup()`` / ``task.cancel()`` are called within the
    event-loop thread rather than from a POSIX signal context.  Falls back
    to ``signal.signal()`` on platforms without ``add_signal_handler``
    support (e.g. Windows / ProactorEventLoop).
    """
    _force_count = 0

    def _cancel_startup() -> None:
        """Cancel all pending startup tasks (runs in event-loop thread)."""
        mgr = getattr(service, "_manager", None)
        if mgr is not None and hasattr(mgr, "cancel_startup"):
            mgr.cancel_startup()

        # Tell uvicorn to exit once the lifespan returns
        import argus_mcp.cli as _cli_mod
        uvicorn_svr = getattr(_cli_mod, "uvicorn_svr_inst", None)
        if uvicorn_svr is not None:
            uvicorn_svr.should_exit = True

    def _handle_sigint() -> None:
        """SIGINT handler — first press cancels, second force-exits."""
        nonlocal _force_count
        _force_count += 1

        if _force_count >= 2:
            logger.warning("Force-exit requested (double Ctrl+C during startup).")
            print("\n[Ctrl+C] Force exit.")
            os._exit(1)

        logger.info("Ctrl+C received during startup — cancelling backend connections…")
        print("\n[Ctrl+C] Cancelling startup… (press again to force-quit)")
        _cancel_startup()

    def _handle_sigterm() -> None:
        """SIGTERM handler — cancel startup gracefully."""
        logger.info("SIGTERM received during startup — cancelling backend connections…")
        _cancel_startup()

    # Legacy-style signal handlers (fallback for Windows / non-Unix loops).
    def _startup_sigint_legacy(signum: int, frame: Any) -> None:
        _handle_sigint()

    def _startup_sigterm_legacy(signum: int, frame: Any) -> None:
        _handle_sigterm()

    # Save originals so we can restore them later.
    original_sigint = signal.getsignal(signal.SIGINT)
    original_sigterm = signal.getsignal(signal.SIGTERM)

    # Prefer loop.add_signal_handler (thread-safe, asyncio-native).
    # Per Python docs: "loop.add_signal_handler() is the preferred way
    # to register signal handlers in asyncio programs."
    try:
        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGINT, _handle_sigint)
        loop.add_signal_handler(signal.SIGTERM, _handle_sigterm)
        logger.debug(
            "Startup signal override installed via loop.add_signal_handler() "
            "(thread-safe, replaces uvicorn handlers temporarily)."
        )
    except (NotImplementedError, AttributeError, RuntimeError):
        # NotImplementedError / AttributeError → Windows ProactorEventLoop
        #   does not support add_signal_handler.
        # RuntimeError → No running event loop (e.g. sync test context).
        # Fall back to signal.signal() — acceptable on Windows where
        # SIGINT handling is fundamentally different (raises KeyboardInterrupt).
        signal.signal(signal.SIGINT, _startup_sigint_legacy)
        signal.signal(signal.SIGTERM, _startup_sigterm_legacy)
        logger.debug(
            "Startup signal override installed via signal.signal() "
            "(fallback — loop.add_signal_handler not available)."
        )

    return original_sigint, original_sigterm


def _restore_signal_handlers(
    original_sigint: Any,
    original_sigterm: Any,
) -> None:
    """Restore the signal handlers that were active before the override.

    Removes any ``loop.add_signal_handler`` registrations first, then
    restores the POSIX-level handlers saved during ``_install_…()``.
    """
    # Remove loop-level handlers (safe even if they were never installed —
    # remove_signal_handler returns False in that case).
    try:
        loop = asyncio.get_running_loop()
        loop.remove_signal_handler(signal.SIGINT)
        loop.remove_signal_handler(signal.SIGTERM)
    except (NotImplementedError, AttributeError, RuntimeError):
        pass

    # Restore the POSIX-level handlers to whatever uvicorn had installed.
    signal.signal(signal.SIGINT, original_sigint)
    signal.signal(signal.SIGTERM, original_sigterm)
    logger.debug("Signal handlers restored to uvicorn defaults.")


@asynccontextmanager
async def app_lifespan(app: Starlette) -> AsyncIterator[None]:
    """Application lifespan management: startup and shutdown.

    Creates a :class:`ArgusService`, drives its lifecycle, and decorates
    each phase with display/console status updates for the TUI / ``--no-tui``
    console.
    """
    from argus_mcp.server.app import mcp_server

    app_s = app.state
    logger.info(
        "Server '%s' v%s startup sequence started...",
        SERVER_NAME,
        SERVER_VERSION,
    )
    logger.debug(
        "Lifespan received host='%s', port=%s",
        getattr(app_s, "host", "N/A"),
        getattr(app_s, "port", 0),
    )
    logger.info(
        "Configured file log level: %s",
        getattr(app_s, "file_log_level_configured", DEFAULT_LOG_LVL),
    )
    logger.info(
        "Actual log file: %s",
        getattr(app_s, "actual_log_file", DEFAULT_LOG_FPATH),
    )

    config_path: str = getattr(app_s, "config_file_path", "")
    if not config_path:
        # Fallback auto-detect (should rarely hit — CLI sets this)
        from argus_mcp.cli import _find_config_file

        config_path = _find_config_file()
    logger.info("Configuration file in use: %s", config_path)

    service = ArgusService()
    # Store service on app.state so management API can access it later (0.2).
    app_s.argus_service = service  # type: ignore[attr-defined]

    # Also propagate to the management sub-app so its request handlers see
    # argus_service on *their* request.app.state (the sub-app's state).
    mgmt_app = getattr(app_s, "mgmt_app", None)
    if mgmt_app is not None:
        mgmt_app.state.argus_service = service  # type: ignore[attr-defined]
        # Forward host/port/transport so the status endpoint can build
        # correct URLs (the mgmt sub-app has its own State object).
        mgmt_app.state.host = getattr(app_s, "host", "127.0.0.1")  # type: ignore[attr-defined]
        mgmt_app.state.port = getattr(app_s, "port", 0)  # type: ignore[attr-defined]
        mgmt_app.state.transport_type = getattr(app_s, "transport_type", "streamable-http")  # type: ignore[attr-defined]

    startup_ok = False
    err_detail_msg: Optional[str] = None

    try:
        # ── Display: initializing ────────────────────────────────────
        status_info_init = gen_status_info(app_s, "Server is starting...")
        disp_console_status("Initialization", status_info_init)
        log_file_status(status_info_init)

        # ── Verbose installer display ────────────────
        verbosity: int = getattr(app_s, "verbosity", 0)
        installer_display: InstallerDisplay | None = None
        progress_callback = None

        if verbosity >= 1 and config_path:
            try:
                from argus_mcp.config.loader import load_and_validate_config

                raw_config = load_and_validate_config(config_path)
                installer_display = InstallerDisplay(raw_config)
                installer_display.render_initial()
                progress_callback = installer_display.make_callback()
            except Exception:
                # Non-fatal — fall back to normal (non-verbose) output
                logger.debug(
                    "Could not initialise installer display; " "falling back to standard output.",
                    exc_info=True,
                )
                installer_display = None

        # ── Delegate full startup to ArgusService ─────────────────
        # Install a temporary signal override so Ctrl+C works during
        # the (potentially very long) backend-connection phase.
        # See module docstring for the full rationale.
        orig_sigint, orig_sigterm = _install_startup_signal_override(service)
        try:
            await service.start(config_path, progress_callback=progress_callback)
        finally:
            # Always restore uvicorn's signal handlers — even if startup
            # was cancelled — so that normal graceful shutdown works for
            # the running server.
            _restore_signal_handlers(orig_sigint, orig_sigterm)

        # Finalize the installer display (print summary line)
        if installer_display is not None:
            installer_display.finalize()

        # ── Monkey-patch bridge components onto mcp_server ───────────
        await _attach_to_mcp_server(mcp_server, service)

        # ── Create & start the SDK streamable-HTTP session manager ───
        # This must happen *after* handlers are attached so that
        # mcp_server.run() (called internally per session) can serve
        # tools/resources/prompts.
        # Uses AsyncExitStack for robust cleanup (pattern from mcp-context-forge).
        import argus_mcp.server.app as app_module
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

        sm_http = StreamableHTTPSessionManager(app=mcp_server)
        app_module.streamable_session_manager = sm_http
        _exit_stack = AsyncExitStack()
        await _exit_stack.enter_async_context(sm_http.run())
        logger.info("SDK StreamableHTTPSessionManager started.")

        logger.info("Lifespan startup phase completed successfully.")
        startup_ok = True

        # ── Display: ready ───────────────────────────────────────────
        status_info_ready = gen_status_info(
            app_s,
            "Server started successfully and is ready.",
            tools=service.tools,
            resources=service.resources,
            prompts=service.prompts,
            conn_svrs_num=service.backends_connected,
            total_svrs_num=service.backends_total,
            route_map=service.registry.get_route_map(),
        )
        disp_console_status("✅ Service Ready", status_info_ready)
        log_file_status(status_info_ready)
        yield

    except ConfigurationError as e_cfg:
        logger.exception("Configuration error: %s", e_cfg)
        err_detail_msg = f"Configuration error: {e_cfg}"
        status_info_fail = gen_status_info(
            app_s,
            "Server startup failed.",
            err_msg=err_detail_msg,
            total_svrs_num=service.backends_total,
        )
        disp_console_status("❌ Startup Failed", status_info_fail)
        log_file_status(status_info_fail, log_lvl=logging.ERROR)
        raise
    except BackendServerError as e_backend:
        logger.exception("Backend error: %s", e_backend)
        err_detail_msg = f"Backend error: {e_backend}"
        status_info_fail = gen_status_info(
            app_s,
            "Server startup failed.",
            err_msg=err_detail_msg,
            conn_svrs_num=service.backends_connected,
            total_svrs_num=service.backends_total,
        )
        disp_console_status("❌ Startup Failed", status_info_fail)
        log_file_status(status_info_fail, log_lvl=logging.ERROR)
        raise
    except Exception as e_exc:
        logger.exception(
            "Unexpected error during lifespan startup: %s",
            e_exc,
        )
        err_detail_msg = f"Unexpected error: {type(e_exc).__name__} - {e_exc}"
        status_info_fail = gen_status_info(
            app_s,
            "Server startup failed.",
            err_msg=err_detail_msg,
            conn_svrs_num=service.backends_connected,
            total_svrs_num=service.backends_total,
        )
        disp_console_status("❌ Startup Failed", status_info_fail)
        log_file_status(status_info_fail, log_lvl=logging.ERROR)
        raise
    finally:
        logger.info(
            "Server '%s' shutdown sequence started...",
            SERVER_NAME,
        )
        status_info_shutdown = gen_status_info(
            app_s,
            "Server is shutting down...",
            tools=service.tools,
            resources=service.resources,
            prompts=service.prompts,
            conn_svrs_num=service.backends_connected,
            total_svrs_num=service.backends_total,
        )
        disp_console_status("🛑 Shutting Down", status_info_shutdown, is_final=False)
        log_file_status(status_info_shutdown, log_lvl=logging.WARNING)

        # ── Delegate shutdown to ArgusService ─────────────────────
        # Stop SDK streamable-HTTP session manager first (closes all
        # active MCP sessions and their task groups).
        if "_exit_stack" in dir() and _exit_stack is not None:
            try:
                await asyncio.wait_for(_exit_stack.aclose(), timeout=10.0)
                logger.info("SDK StreamableHTTPSessionManager stopped.")
            except asyncio.TimeoutError:
                logger.warning(
                    "StreamableHTTPSessionManager aclose() timed out after 10s."
                )
            except RuntimeError as e_rt:
                logger.debug(
                    "Cancel scope error during session manager shutdown: %s",
                    e_rt,
                )
            except Exception:
                logger.debug(
                    "Error stopping StreamableHTTPSessionManager",
                    exc_info=True,
                )
            # Clear the module-level reference
            try:
                import argus_mcp.server.app as app_module

                app_module.streamable_session_manager = None
            except Exception:
                pass

        # Stop Argus session manager before stopping backends
        sm = getattr(mcp_server, "session_manager", None)
        if sm is not None:
            await sm.stop()
        await service.stop()

        final_msg_short = (
            "Server shut down normally."
            if startup_ok
            else (
                f"Server exited abnormally"
                f"{(f' - Error: {err_detail_msg}' if err_detail_msg else '')}"
            )
        )
        final_icon = "✅" if startup_ok else "❌"
        final_log_lvl = logging.INFO if startup_ok else logging.ERROR

        status_info_final = gen_status_info(
            app_s,
            final_msg_short,
            err_msg=err_detail_msg if not startup_ok else None,
        )
        disp_console_status(f"{final_icon} Final Status", status_info_final, is_final=True)
        log_file_status(status_info_final, log_lvl=final_log_lvl)
        logger.info(
            "Server '%s' shutdown sequence completed.",
            SERVER_NAME,
        )
