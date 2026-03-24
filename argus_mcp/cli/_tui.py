"""TUI launch helpers for ``argus-mcp tui``."""

from __future__ import annotations

import argparse
import os
import sys
from typing import TYPE_CHECKING, Optional

import yaml

from argus_mcp.cli._common import module_logger
from argus_mcp.config.loader import find_config_file as _find_config_file
from argus_mcp.constants import DEFAULT_HOST, DEFAULT_PORT, SERVER_NAME

if TYPE_CHECKING:
    from argus_mcp.config.schema import ClientConfig
    from argus_mcp.tui.server_manager import ServerManager


def _load_client_config(
    args: argparse.Namespace,
) -> tuple[ClientConfig, Optional[str]]:
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


def _resolve_tui_server_url(args: argparse.Namespace, client_cfg: ClientConfig) -> str:
    """Determine the TUI server URL from CLI → env → config → default."""
    from argus_mcp.tui.app import _normalise_server_url

    default_url_str = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
    raw_server: str = args.server
    if raw_server == default_url_str:
        raw_server = os.environ.get("ARGUS_TUI_SERVER") or client_cfg.server_url or default_url_str
    return _normalise_server_url(raw_server) or raw_server


def _build_tui_server_manager(
    args: argparse.Namespace,
    client_cfg: ClientConfig,
    clean_server: str,
    token: Optional[str],
) -> ServerManager:
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
