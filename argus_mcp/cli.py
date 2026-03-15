"""CLI argument parsing and main entry point.

Provides two modes of operation:

* ``argus-mcp server`` — run the headless Uvicorn server.
* ``argus-mcp tui``    — launch the Textual TUI against a running server.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import subprocess
import sys
from typing import TYPE_CHECKING, Optional

import uvicorn
import yaml

from argus_mcp.config.loader import find_config_file as _find_config_file
from argus_mcp.constants import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    SERVER_NAME,
    SERVER_VERSION,
)
from argus_mcp.display.logging_config import setup_logging

if TYPE_CHECKING:
    from argus_mcp.tui.client_config import ClientConfig
    from argus_mcp.tui.server_manager import ServerManager

module_logger = logging.getLogger(__name__)

uvicorn_svr_inst: Optional[uvicorn.Server] = None

# Legacy PID file location (kept for backward-compat cleanup)
_PID_FILE = os.path.join(
    os.path.expanduser("~"),
    ".argus",
    "argus-mcp.pid",
)


async def _run_server(
    host: str,
    port: int,
    log_lvl_cli: str,
    config_path: str | None = None,
    verbosity: int = 0,
    auto_reauth: bool = False,
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
                verbosity=getattr(args, "verbose", 0) or 0,
                auto_reauth=getattr(args, "auto_reauth", False),
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


def _cleanup_pid_file() -> None:
    """Remove the legacy PID file, ignoring missing files."""
    try:
        os.unlink(_PID_FILE)
    except FileNotFoundError:
        pass


def _stop_named_session(session_name: str) -> None:
    """Stop a specific named session by *session_name*."""
    from argus_mcp.sessions import load_session, remove_session, stop_session

    info = load_session(session_name)
    if info is None:
        print(f"No session named '{session_name}' found.", file=sys.stderr)
        sys.exit(1)
    if not info.is_alive():
        print(f"Session '{session_name}' (PID {info.pid}) is not running (stale). Cleaning up.")
        remove_session(session_name)
        return

    print(f"Sending SIGTERM to '{session_name}' (PID {info.pid})…")
    if stop_session(info):
        print(f"Session '{session_name}' stopped.")
    else:
        print(f"Session '{session_name}' did not exit cleanly.", file=sys.stderr)
        sys.exit(1)
    _cleanup_pid_file()


def _stop_legacy_pid() -> None:
    """Stop a server process tracked only via a legacy PID file."""
    try:
        with open(_PID_FILE) as f:
            pid = int(f.read().strip())
    except FileNotFoundError:
        print("No running server found.")
        sys.exit(1)
    except (ValueError, OSError) as exc:
        print(f"Error reading PID file: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        print(f"Server process {pid} is not running (stale PID file). Cleaning up.")
        _cleanup_pid_file()
        return
    except PermissionError:
        pass

    print(f"Sending SIGTERM to server (PID {pid})…")
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        print(f"Failed to stop server: {exc}", file=sys.stderr)
        sys.exit(1)

    import time

    for _ in range(30):
        time.sleep(0.1)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
    else:
        print(f"Server (PID {pid}) did not exit within 3 s — sending SIGKILL.")
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass

    _cleanup_pid_file()
    print("Server stopped.")


def _cmd_stop(args: argparse.Namespace) -> None:
    """Entry-point for ``argus-mcp stop [NAME]``."""
    from argus_mcp.sessions import find_session, list_sessions, stop_session

    session_name: Optional[str] = getattr(args, "session_name", None)

    if session_name:
        _stop_named_session(session_name)
        return

    # No name given — try to find the only running session
    info = find_session()
    if info is not None:
        print(f"Sending SIGTERM to '{info.name}' (PID {info.pid})…")
        if stop_session(info):
            print(f"Session '{info.name}' stopped.")
        else:
            print(f"Session '{info.name}' did not exit cleanly.", file=sys.stderr)
            sys.exit(1)
        _cleanup_pid_file()
        return

    # Multiple sessions running
    alive = list_sessions()
    if len(alive) > 1:
        print("Multiple sessions running. Specify which one to stop:", file=sys.stderr)
        for s in alive:
            print(f"  {s.name:20s}  PID {s.pid:>6d}  port {s.port}", file=sys.stderr)
        print("\nUsage: argus-mcp stop <name>", file=sys.stderr)
        sys.exit(1)

    # Fall back to legacy PID file
    _stop_legacy_pid()


def _cmd_status(_args: argparse.Namespace) -> None:
    """Entry-point for ``argus-mcp status``."""
    from argus_mcp.sessions import list_sessions

    sessions = list_sessions()

    if not sessions:
        print("No running Argus MCP sessions.")
        return

    # Header
    print(f"{'NAME':<20s}  {'PID':>6s}  {'PORT':>5s}  {'HOST':<15s}  {'CONFIG':<30s}  {'STARTED'}")
    print("─" * 100)

    for s in sessions:
        # Format started_at for display
        started = s.started_at[:19].replace("T", " ") if s.started_at else "unknown"
        config_display = os.path.basename(s.config) if s.config else "-"
        print(
            f"{s.name:<20s}  {s.pid:>6d}  {s.port:>5d}  {s.host:<15s}  "
            f"{config_display:<30s}  {started}"
        )

    print(f"\n{len(sessions)} session(s) running.")


def _load_client_config(
    args: argparse.Namespace,
) -> tuple["ClientConfig", Optional[str]]:
    """Load the client YAML config and resolve the config path.

    Returns ``(client_cfg, config_path)``.
    """
    from argus_mcp.config.schema import ClientConfig

    client_cfg = ClientConfig()  # safe defaults
    config_path = getattr(args, "config", None) or os.environ.get("ARGUS_CONFIG")
    if config_path is None:
        config_path = _find_config_file()
    if config_path and os.path.isfile(config_path):
        try:
            from argus_mcp.config.loader import load_argus_config

            client_cfg = load_argus_config(config_path).client
        except (OSError, yaml.YAMLError, AttributeError, KeyError, ValueError):
            module_logger.debug("Client config load failed, using defaults", exc_info=True)
    return client_cfg, config_path


def _resolve_tui_server_url(args: argparse.Namespace, client_cfg: "ClientConfig") -> str:
    """Determine the TUI server URL from CLI → env → config → default."""
    from argus_mcp.tui.app import _normalise_server_url

    default_url_str = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
    raw_server: str = args.server
    if raw_server == default_url_str:
        raw_server = os.environ.get("ARGUS_TUI_SERVER") or client_cfg.server_url or default_url_str
    return _normalise_server_url(raw_server) or raw_server


def _build_tui_server_manager(
    args: argparse.Namespace,
    client_cfg: "ClientConfig",
    clean_server: str,
    token: Optional[str],
) -> "ServerManager":
    """Build the :class:`ServerManager` for TUI mode."""
    from argus_mcp.tui.server_manager import ServerManager

    servers_config: Optional[str] = (
        getattr(args, "servers_config", None) or client_cfg.servers_config
    )
    if servers_config:
        return ServerManager.from_config(config_path=servers_config)
    mgr = ServerManager.from_config()
    if mgr.count == 0:
        mgr.add("default", clean_server, token, set_active=True)
    return mgr


def _cmd_tui(args: argparse.Namespace) -> None:
    """Entry-point for ``argus-mcp tui``."""
    client_cfg, _ = _load_client_config(args)

    token: Optional[str] = args.token or os.environ.get("ARGUS_MGMT_TOKEN") or client_cfg.token

    _saved_termios = None
    try:
        import termios

        _saved_termios = termios.tcgetattr(sys.stdin.fileno())
    except Exception:  # noqa: BLE001
        pass  # stdin may not be a real terminal

    try:
        from argus_mcp.tui.app import ArgusApp

        clean_server = _resolve_tui_server_url(args, client_cfg)
        mgr = _build_tui_server_manager(args, client_cfg, clean_server, token)

        tui_app = ArgusApp(
            server_url=clean_server if mgr.count <= 1 else None,
            token=token,
            server_manager=mgr,
        )
        tui_app.run()
    except ImportError as exc:
        print(
            f"Error: Textual is required for TUI mode but could not be "
            f"imported ({exc}). Install with:  pip install textual",
            file=sys.stderr,
        )
        sys.exit(1)
    except KeyboardInterrupt:
        module_logger.info("%s TUI interrupted by KeyboardInterrupt.", SERVER_NAME)
    except Exception as exc:  # noqa: BLE001
        module_logger.exception("%s TUI encountered an uncaught fatal error: %s", SERVER_NAME, exc)
        sys.exit(1)
    finally:
        _restore_terminal(_saved_termios)
        module_logger.info("%s TUI finished.", SERVER_NAME)


def _restore_terminal(saved_termios: object | None) -> None:
    """Best-effort terminal restoration after Textual exits.

    Terminal restoration is inherently best-effort -- catch broadly
    to avoid masking the real exit reason.  See cli.py docstring.
    """
    module_logger.debug(
        "Attempting terminal restoration (saved_termios=%s)", saved_termios is not None
    )
    sys.stdout = sys.__stdout__
    sys.stderr = sys.__stderr__

    if saved_termios is not None:
        try:
            import termios

            fd = sys.stdin.fileno()
            termios.tcsetattr(fd, termios.TCSANOW, saved_termios)  # type: ignore[arg-type]
        except Exception:  # noqa: BLE001
            pass

    import subprocess as _sp

    try:
        _sp.run(
            ["stty", "sane"],
            stdin=sys.stdin,
            stdout=_sp.DEVNULL,
            stderr=_sp.DEVNULL,
            timeout=2,
        )
    except Exception:  # noqa: BLE001
        pass

    try:
        import termios

        fd = sys.stdin.fileno()
        attrs = termios.tcgetattr(fd)
        attrs[3] |= termios.ECHO | termios.ICANON
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
    except Exception:  # noqa: BLE001
        pass

    try:
        print()
    except Exception:  # noqa: BLE001
        pass


def _cmd_build(args: argparse.Namespace) -> None:
    """Pre-build container images for all stdio backends.

    Builds images **sequentially** (one at a time) so Docker/Podman
    are not overwhelmed with concurrent pulls + layer installs.

    This should be run once before ``argus-mcp server`` when container
    isolation is enabled (the default).
    """
    config_path = getattr(args, "config", None) or _find_config_file()
    setup_logging("info")

    log = logging.getLogger("argus_mcp.build")
    log.info("Loading config from %s", config_path)

    from argus_mcp.config.loader import load_and_validate_config

    backend_map = load_and_validate_config(config_path)

    # Identify stdio backends
    stdio_backends = {
        name: conf for name, conf in backend_map.items() if conf.get("type") == "stdio"
    }

    if not stdio_backends:
        print("No stdio backends found in config — nothing to build.")
        return

    print(f"Building container images for {len(stdio_backends)} stdio backend(s)...\n")

    async def _build_all() -> None:
        from mcp import StdioServerParameters

        from argus_mcp.bridge.container import wrap_backend

        ok, skip, fail = 0, 0, 0
        for name, conf in stdio_backends.items():
            params = conf.get("params")
            if not isinstance(params, StdioServerParameters):
                log.warning("[%s] Invalid params — skipping.", name)
                skip += 1
                continue

            container_cfg = conf.get("container") or {}
            net_override = container_cfg.get("network") or (
                (conf.get("network") or {}).get("network_mode")
            )

            print(f"  [{name}] Building image for '{params.command}' ...", end=" ", flush=True)
            try:
                _wrapped, was_isolated = await wrap_backend(
                    name,
                    params,
                    enabled=container_cfg.get("enabled", True),
                    runtime_override=container_cfg.get("runtime"),
                    network=net_override,
                    memory=container_cfg.get("memory"),
                    cpus=container_cfg.get("cpus"),
                    volumes=container_cfg.get("volumes"),
                    extra_args=container_cfg.get("extra_args"),
                    build_if_missing=True,
                    system_deps=container_cfg.get("system_deps"),
                    builder_image=container_cfg.get("builder_image"),
                    additional_packages=container_cfg.get("additional_packages"),
                    transport_override=container_cfg.get("transport"),
                    go_package=container_cfg.get("go_package"),
                )
                if was_isolated:
                    print("OK (containerised)")
                    ok += 1
                else:
                    print("skipped (not wrappable or disabled)")
                    skip += 1
            except Exception as exc:  # noqa: BLE001
                print(f"FAILED ({exc})")
                log.error("[%s] Build failed: %s", name, exc, exc_info=True)
                fail += 1

        print(f"\nDone: {ok} built, {skip} skipped, {fail} failed.")
        if fail > 0:
            sys.exit(1)

    asyncio.run(_build_all())


def _cmd_secret(args: argparse.Namespace) -> None:
    """Entry-point for ``argus-mcp secret set/get/list/delete``."""
    from argus_mcp.secrets.store import SecretStore

    provider = getattr(args, "provider", "file")
    store_kwargs: dict[str, str] = {}
    if provider == "file":
        path = getattr(args, "path", None) or "secrets.enc"
        store_kwargs["path"] = path

    store = SecretStore(provider_type=provider, **store_kwargs)
    action = args.secret_action

    if action == "set":
        import getpass as _gp

        value = getattr(args, "value", None)
        if value is None:
            value = _gp.getpass(f"Value for '{args.name}': ")
        store.set(args.name, value)
        print(f"Secret '{args.name}' stored.")

    elif action == "get":
        val = store.get(args.name)
        if val is None:
            print(f"Secret '{args.name}' not found.", file=sys.stderr)
            sys.exit(1)
        print(val)

    elif action == "list":
        names = store.list_names()
        if not names:
            print("No secrets stored.")
        else:
            for n in sorted(names):
                print(n)

    elif action == "delete":
        store.delete(args.name)
        print(f"Secret '{args.name}' deleted.")


def _cmd_clean(args: argparse.Namespace) -> None:
    """Remove containers and images created by argus-mcp.

    Finds containers whose image starts with ``arguslocal/`` and
    removes them.  Optionally removes the ``arguslocal/`` images
    and the ``argus-mcp`` Docker network as well.
    """
    import subprocess

    from argus_mcp.bridge.container.templates import IMAGE_PREFIX

    images_flag: bool = getattr(args, "images", False)
    network_flag: bool = getattr(args, "network", False)
    all_flag: bool = getattr(args, "all", False)
    if all_flag:
        images_flag = network_flag = True

    runtime = "docker"
    for candidate in ("docker", "podman"):
        try:
            subprocess.run(
                [candidate, "version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=10,
            )
            runtime = candidate
            break
        except (FileNotFoundError, subprocess.SubprocessError):
            continue

    # Find all containers (running + stopped) whose image starts
    # with the arguslocal/ prefix.
    result = subprocess.run(
        [
            runtime,
            "ps",
            "-a",
            "--filter",
            f"ancestor={IMAGE_PREFIX}/",
            "--format",
            "{{.ID}} {{.Names}} {{.Image}} {{.Status}}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    # The ancestor filter alone is imprecise — also list by name pattern
    result2 = subprocess.run(
        [
            runtime,
            "ps",
            "-a",
            "--format",
            "{{.ID}} {{.Names}} {{.Image}} {{.Status}}",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    # Collect container IDs whose image starts with arguslocal/
    container_lines: list[str] = []
    container_ids: list[str] = []
    seen: set[str] = set()
    for line in (result.stdout + "\n" + result2.stdout).strip().splitlines():
        parts = line.split(None, 3)
        if len(parts) < 3:
            continue
        cid, _name, image = parts[0], parts[1], parts[2]
        if cid in seen:
            continue
        if image.startswith(f"{IMAGE_PREFIX}/"):
            seen.add(cid)
            container_ids.append(cid)
            container_lines.append(line)

    if container_ids:
        print(f"Removing {len(container_ids)} argus-mcp container(s):")
        for line in container_lines:
            print(f"  {line}")
        subprocess.run(
            [runtime, "rm", "-f", *container_ids],
            capture_output=True,
            timeout=60,
        )
        print("Containers removed.")
    else:
        print("No argus-mcp containers found.")

    if images_flag:
        img_result = subprocess.run(
            [
                runtime,
                "images",
                "--format",
                "{{.ID}} {{.Repository}}:{{.Tag}}",
                f"{IMAGE_PREFIX}/*",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        image_ids: list[str] = []
        image_lines: list[str] = []
        for line in img_result.stdout.strip().splitlines():
            parts = line.split(None, 1)
            if parts:
                image_ids.append(parts[0])
                image_lines.append(line)

        if image_ids:
            print(f"\nRemoving {len(image_ids)} arguslocal image(s):")
            for line in image_lines:
                print(f"  {line}")
            subprocess.run(
                [runtime, "rmi", "-f", *image_ids],
                capture_output=True,
                timeout=120,
            )
            print("Images removed.")
        else:
            print("\nNo arguslocal images found.")

    if network_flag:
        from argus_mcp.bridge.container.network import ARGUS_NETWORK

        net_result = subprocess.run(
            [runtime, "network", "ls", "--filter", f"name={ARGUS_NETWORK}", "-q"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        net_ids = net_result.stdout.strip().splitlines()
        if net_ids:
            print(f"\nRemoving '{ARGUS_NETWORK}' network…")
            subprocess.run(
                [runtime, "network", "rm", ARGUS_NETWORK],
                capture_output=True,
                timeout=30,
            )
            print("Network removed.")
        else:
            print(f"\nNo '{ARGUS_NETWORK}' network found.")


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser with server/tui subcommands."""
    parser = argparse.ArgumentParser(
        description=f"{SERVER_NAME} v{SERVER_VERSION}",
    )

    subparsers = parser.add_subparsers(dest="command")

    sp_server = subparsers.add_parser(
        "server",
        help="Run the headless Argus server (Uvicorn + MCP bridge, with container isolation)",
    )
    sp_server.add_argument(
        "--host",
        type=str,
        default=DEFAULT_HOST,
        help=f"Host address (default: {DEFAULT_HOST})",
    )
    sp_server.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port (default: {DEFAULT_PORT})",
    )
    sp_server.add_argument(
        "--log-level",
        type=str,
        default="info",
        choices=["debug", "info", "warning", "error", "critical"],
        help="Set file logging level (default: info)",
    )
    sp_server.add_argument(
        "--config",
        type=str,
        default=None,
        metavar="PATH",
        help=("Path to configuration file (YAML). Default: auto-detect config.yaml/config.yml"),
    )
    sp_server.add_argument(
        "-d",
        "--detach",
        action="store_true",
        default=False,
        help="Run the server as a detached background process",
    )
    sp_server.add_argument(
        "--name",
        type=str,
        default=None,
        metavar="NAME",
        help=(
            "Session name for detached mode (default: 'default' or 'argus-PORT'). "
            "Lowercase alphanumeric + hyphens, max 32 chars."
        ),
    )
    sp_server.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help=(
            "Increase startup verbosity. "
            "-v shows connection progress and streaming docker build output; "
            "-vv adds full subprocess/debug output."
        ),
    )
    sp_server.add_argument(
        "--auto-reauth",
        action="store_true",
        default=False,
        help=(
            "Automatically open the browser for re-authentication when an "
            "OAuth backend's refresh token is expired or revoked."
        ),
    )
    sp_server.set_defaults(func=_cmd_server)

    sp_build = subparsers.add_parser(
        "build",
        help="Pre-build container images for all stdio backends",
    )
    sp_build.add_argument(
        "--config",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to configuration file (YAML). Default: auto-detect.",
    )
    sp_build.set_defaults(func=_cmd_build)

    sp_stop = subparsers.add_parser(
        "stop",
        help="Stop a detached Argus server",
    )
    sp_stop.add_argument(
        "session_name",
        nargs="?",
        default=None,
        metavar="NAME",
        help="Session name to stop (optional if only one session is running)",
    )
    sp_stop.set_defaults(func=_cmd_stop)

    sp_status = subparsers.add_parser(
        "status",
        help="List all running Argus server sessions",
    )
    sp_status.set_defaults(func=_cmd_status)

    sp_tui = subparsers.add_parser(
        "tui",
        help="Launch the Textual TUI connected to a running Argus server",
    )
    default_url = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
    sp_tui.add_argument(
        "--server",
        type=str,
        default=default_url,
        help=f"Server URL (default: {default_url})",
    )
    sp_tui.add_argument(
        "--token",
        type=str,
        default=None,
        help="Bearer token for management API (or set ARGUS_MGMT_TOKEN env var)",
    )
    sp_tui.add_argument(
        "--servers-config",
        type=str,
        default=None,
        metavar="PATH",
        help=(
            "Path to servers.json for multi-server mode. Default: ~/.config/argus-mcp/servers.json"
        ),
    )
    sp_tui.set_defaults(func=_cmd_tui)

    sp_secret = subparsers.add_parser(
        "secret",
        help="Manage encrypted secrets (set, get, list, delete)",
    )
    sp_secret.add_argument(
        "--provider",
        type=str,
        default="file",
        choices=["env", "file", "keyring"],
        help="Secret provider backend (default: file)",
    )
    sp_secret.add_argument(
        "--path",
        type=str,
        default=None,
        help="Path to encrypted secrets file (file provider only)",
    )
    secret_sub = sp_secret.add_subparsers(dest="secret_action")

    sp_set = secret_sub.add_parser("set", help="Store a secret")
    sp_set.add_argument("name", help="Secret name")
    sp_set.add_argument("value", nargs="?", default=None, help="Secret value (prompted if omitted)")

    sp_get = secret_sub.add_parser("get", help="Retrieve a secret value")
    sp_get.add_argument("name", help="Secret name")

    secret_sub.add_parser("list", help="List all secret names")

    sp_del = secret_sub.add_parser("delete", help="Delete a secret")
    sp_del.add_argument("name", help="Secret name")

    sp_secret.set_defaults(func=_cmd_secret)

    sp_clean = subparsers.add_parser(
        "clean",
        help="Remove containers and images created by argus-mcp",
    )
    sp_clean.add_argument(
        "--images",
        action="store_true",
        default=False,
        help="Also remove arguslocal/* container images",
    )
    sp_clean.add_argument(
        "--network",
        action="store_true",
        default=False,
        help="Also remove the argus-mcp Docker network",
    )
    sp_clean.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Remove containers, images, and network (equivalent to --images --network)",
    )
    sp_clean.set_defaults(func=_cmd_clean)

    return parser


def main() -> None:
    """Program entry point: parse arguments and dispatch to subcommand."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)
    else:
        args.func(args)
