"""Server lifecycle management for ``argus-mcp server``."""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import subprocess
import sys
from typing import Optional

import uvicorn
import yaml

from argus_mcp.cli._common import _PID_FILE, module_logger
from argus_mcp.config.loader import find_config_file as _find_config_file
from argus_mcp.constants import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    SERVER_NAME,
    SERVER_VERSION,
)
from argus_mcp.display.logging_config import setup_logging

uvicorn_svr_inst: Optional[uvicorn.Server] = None


async def _run_server(
    host: str,
    port: int,
    log_lvl_cli: str,
    config_path: str | None = None,
    verbosity: int = 0,
    auto_reauth: bool = False,
    parallel: bool = False,
) -> None:
    """Async main for the headless server subcommand."""
    global uvicorn_svr_inst

    log_fpath, cfg_log_lvl = setup_logging(log_lvl_cli)

    module_logger.info(
        "---- %s v%s starting (file log level: %s) ----",
        SERVER_NAME,
        SERVER_VERSION,
        cfg_log_lvl,
    )

    # Resolve config path: CLI flag → env var → auto-detect
    if config_path is None:
        config_path = os.environ.get("ARGUS_CONFIG")
    if config_path is None:
        config_path = _find_config_file()
    resolved_config_path = os.path.abspath(config_path)
    module_logger.info("Configuration file path resolved to: %s", resolved_config_path)

    # Import app here to avoid circular imports at module level
    from argus_mcp.server.app import app

    app_state = app.state
    app_state.host = host
    app_state.port = port
    app_state.actual_log_file = log_fpath
    app_state.file_log_level_configured = cfg_log_lvl
    app_state.config_file_path = resolved_config_path
    app_state.verbosity = verbosity
    app_state.auto_reauth = auto_reauth
    app_state.parallel = parallel

    # Read server settings from config so host/port/transport are honoured.
    try:
        from argus_mcp.config.loader import load_argus_config

        _argus_cfg = load_argus_config(resolved_config_path)
        app_state.transport_type = _argus_cfg.server.transport

        # Apply config host/port when the CLI values are still the defaults.
        if host == DEFAULT_HOST and _argus_cfg.server.host != DEFAULT_HOST:
            host = _argus_cfg.server.host
            app_state.host = host
            module_logger.info("Host overridden by config: %s", host)
        if port == DEFAULT_PORT and _argus_cfg.server.port != DEFAULT_PORT:
            port = _argus_cfg.server.port
            app_state.port = port
            module_logger.info("Port overridden by config: %s", port)
    except (OSError, yaml.YAMLError, AttributeError, KeyError, ValueError):
        app_state.transport_type = "streamable-http"
        module_logger.debug(
            "Transport type detection failed, defaulting to streamable-http", exc_info=True
        )

    module_logger.debug("Configuration parameters stored in app.state.")

    uvicorn_cfg = uvicorn.Config(
        app="argus_mcp.server.app:app",
        host=host,
        port=port,
        log_config=None,
        log_level=cfg_log_lvl.lower() if cfg_log_lvl == "DEBUG" else "warning",
    )
    uvicorn_svr_inst = uvicorn.Server(uvicorn_cfg)

    # Pre-flight: verify port is available before doing expensive backend
    # connections during lifespan startup.  This avoids the confusing
    # scenario where all backends connect successfully but then uvicorn
    # fails to bind the port and everything shuts down immediately.
    import socket as _socket

    _probe = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    try:
        _probe.bind((host, port))
    except OSError as exc:
        module_logger.error("Port %s on %s is already in use: %s", port, host, exc)
        print(
            f"\n❌ Error: Port {port} on {host} is already in use.\n"
            f"   Release the port or choose a different one with --port.\n"
        )
        return
    finally:
        _probe.close()

    module_logger.info("Preparing to start Uvicorn server: http://%s:%s", host, port)
    try:
        await uvicorn_svr_inst.serve()
    except (KeyboardInterrupt, SystemExit) as exc:
        module_logger.info("Server stopped due to '%s'.", type(exc).__name__)
    except Exception as exc:  # noqa: BLE001
        module_logger.exception("Unexpected error while running Uvicorn server: %s", exc)
        raise
    finally:
        module_logger.info("%s has shut down or is shutting down.", SERVER_NAME)


def _write_pid_file(
    session_name: str = "default",
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    config: str = "",
) -> None:
    """Write session metadata via the sessions module (+ legacy PID file)."""
    from argus_mcp.sessions import SessionInfo, save_session

    info = SessionInfo(
        name=session_name,
        pid=os.getpid(),
        host=host,
        port=port,
        config=config,
    )
    save_session(info)
    # Legacy PID file for backward compatibility
    with open(_PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def _remove_pid_file(session_name: str = "default") -> None:
    """Remove session metadata and legacy PID file."""
    from argus_mcp.sessions import load_session, remove_session

    info = load_session(session_name)
    if info is not None and info.pid == os.getpid():
        remove_session(session_name)
    # Legacy cleanup
    try:
        with open(_PID_FILE) as f:
            stored_pid = int(f.read().strip())
        if stored_pid == os.getpid():
            os.unlink(_PID_FILE)
    except (FileNotFoundError, ValueError, OSError):
        pass


def _detach_server(args: argparse.Namespace) -> None:
    """Re-launch the server command as a detached background process."""
    from argus_mcp.sessions import (
        SessionInfo,
        auto_name,
        check_port_conflict,
        save_session,
        validate_name,
    )

    # Resolve session name
    explicit_name = getattr(args, "name", None)
    if explicit_name:
        session_name = validate_name(explicit_name)
    else:
        session_name = auto_name(args.port, DEFAULT_PORT)

    # Check for port conflict with existing sessions
    conflict = check_port_conflict(args.host, args.port)
    if conflict is not None:
        print(
            f"❌ Error: Port {args.port} on {args.host} is already used by "
            f"session '{conflict.name}' (PID {conflict.pid}).\n"
            f"  Stop it first: argus-mcp stop {conflict.name}",
            file=sys.stderr,
        )
        sys.exit(1)

    cmd = [sys.executable, "-m", "argus_mcp", "server", "--name", session_name]
    if args.host != DEFAULT_HOST:
        cmd += ["--host", args.host]
    if args.port != DEFAULT_PORT:
        cmd += ["--port", str(args.port)]
    if args.log_level != "info":
        cmd += ["--log-level", args.log_level]
    cfg = getattr(args, "config", None)
    if cfg is not None:
        cmd += ["--config", cfg]

    # Open the log directory for stdout/stderr redirection
    from argus_mcp.constants import LOG_DIR

    log_dir = os.path.join(os.path.expanduser("~"), ".argus", LOG_DIR)
    os.makedirs(log_dir, exist_ok=True)
    out_path = os.path.join(  # nosemgrep: injection-path-traversal-join
        log_dir, f"detached-{session_name}.log"
    )
    out_fd = open(out_path, "a")

    # Ensure the child process flushes stdout/stderr immediately so
    # the detached.log is populated in real-time, not buffered.
    child_env = os.environ.copy()
    child_env["PYTHONUNBUFFERED"] = "1"

    proc = subprocess.Popen(
        cmd,
        stdout=out_fd,
        stderr=out_fd,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env=child_env,
    )
    out_fd.close()

    # Save session metadata immediately (the child will also save on startup)
    info = SessionInfo(
        name=session_name,
        pid=proc.pid,
        host=args.host,
        port=args.port,
        config=getattr(args, "config", None) or "",
        log_file=out_path,
    )
    save_session(info)

    print(
        f"Argus MCP server '{session_name}' started in background (PID {proc.pid}).\n"
        f"  Logs: {out_path}\n"
        f"  Stop: argus-mcp stop {session_name}"
    )


def _cmd_server(args: argparse.Namespace) -> None:
    """Entry-point for ``argus-mcp server``."""
    if getattr(args, "detach", False):
        _detach_server(args)
        return
    _force_exit_count = 0

    def _sigint_handler(sig: int, _frame: object) -> None:
        """Pre-uvicorn SIGINT handler (active only until uvicorn starts).

        Once uvicorn calls ``Server.capture_signals()`` this handler is
        replaced by uvicorn's ``handle_exit()``.  During the lifespan,
        a *different* temporary override (in ``lifespan.py``) takes
        over so that Ctrl+C can cancel in-flight startup tasks.

        This handler remains useful for the brief window between
        ``signal.signal(...)`` here and the ``await uvicorn_svr.serve()``
        call (e.g. config loading, port probe).
        """
        nonlocal _force_exit_count
        _force_exit_count += 1
        if _force_exit_count >= 2:
            module_logger.info("Force exit requested (double Ctrl+C).")
            os._exit(1)
        module_logger.info("Ctrl+C received — shutting down…")
        print("\n[Ctrl+C] Shutting down gracefully… (press again to force)")
        if uvicorn_svr_inst is not None:
            uvicorn_svr_inst.should_exit = True

    def _sigterm_handler(sig: int, _frame: object) -> None:
        """Pre-uvicorn SIGTERM handler (see _sigint_handler docstring)."""
        module_logger.info("SIGTERM received — shutting down gracefully…")
        if uvicorn_svr_inst is not None:
            uvicorn_svr_inst.should_exit = True

    signal.signal(signal.SIGINT, _sigint_handler)
    signal.signal(signal.SIGTERM, _sigterm_handler)
    # Ignore SIGHUP so terminal hangup doesn't kill a detached server.
    signal.signal(signal.SIGHUP, signal.SIG_IGN)

    # Resolve session name for PID/session tracking
    from argus_mcp.sessions import auto_name

    session_name = getattr(args, "name", None) or auto_name(args.port, DEFAULT_PORT)
    config_path = getattr(args, "config", None) or ""

    _write_pid_file(session_name, args.host, args.port, config_path)
    try:
        asyncio.run(
            _run_server(
                host=args.host,
                port=args.port,
                log_lvl_cli=args.log_level,
                config_path=getattr(args, "config", None),
                verbosity=-1
                if getattr(args, "quiet", False)
                else (getattr(args, "verbose", 0) or 0),
                auto_reauth=getattr(args, "auto_reauth", False),
                parallel=getattr(args, "parallel", False),
            )
        )
    except KeyboardInterrupt:
        module_logger.info("%s main program interrupted by KeyboardInterrupt.", SERVER_NAME)
    except SystemExit as exc:
        if exc.code is None or exc.code == 0:
            module_logger.info(
                "%s main program exited normally (code: %s).",
                SERVER_NAME,
                exc.code,
            )
        else:
            module_logger.error(
                "%s main program exited with SystemExit (code: %s).",
                SERVER_NAME,
                exc.code,
            )
    except Exception as exc:  # noqa: BLE001
        module_logger.exception(
            "%s main program encountered an uncaught fatal error: %s",
            SERVER_NAME,
            exc,
        )
        sys.exit(1)
    finally:
        _remove_pid_file(session_name)
        module_logger.info("%s application finished.", SERVER_NAME)
