"""Argus-MCP CLI – package entry point.

Re-exports every public helper so that ``from argus_mcp.cli import X``
continues to work for all existing call-sites and tests.
"""

from __future__ import annotations

import argparse
import sys

from argus_mcp.cli._build import _cmd_build  # noqa: F401
from argus_mcp.cli._clean import (  # noqa: F401
    _clean_images,
    _clean_network,
    _cmd_clean,
    _detect_container_runtime,
    _find_argus_containers,
)

# Re-export symbols that tests / other modules expect under ``argus_mcp.cli.*``.
from argus_mcp.cli._common import _PID_FILE, module_logger  # noqa: F401
from argus_mcp.cli._secret import _cmd_secret  # noqa: F401
from argus_mcp.cli._server import (  # noqa: F401
    _cmd_server,
    _detach_server,
    _remove_pid_file,
    _run_server,
    _write_pid_file,
)
from argus_mcp.cli._stop import (  # noqa: F401
    _cleanup_pid_file,
    _cmd_status,
    _cmd_stop,
    _stop_all_servers,
    _stop_legacy_pid,
    _stop_named_session,
)
from argus_mcp.cli._tui import (  # noqa: F401
    _build_tui_server_manager,
    _cmd_tui,
    _load_client_config,
    _resolve_tui_server_url,
    _restore_terminal,
)
from argus_mcp.constants import DEFAULT_HOST, DEFAULT_PORT, SERVER_NAME, SERVER_VERSION


def __getattr__(name: str):  # noqa: ANN001
    if name == "uvicorn_svr_inst":
        from argus_mcp.cli import _server

        return _server.uvicorn_svr_inst
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
        "-c",
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
    _server_verbosity = sp_server.add_mutually_exclusive_group()
    _server_verbosity.add_argument(
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
    _server_verbosity.add_argument(
        "-q",
        "--quiet",
        "--silent",
        action="store_true",
        default=False,
        help="Suppress normal output (errors still shown).",
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
    sp_server.add_argument(
        "--parallel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Build and connect stdio backends concurrently instead of sequentially.",
    )
    sp_server.set_defaults(func=_cmd_server)

    sp_build = subparsers.add_parser(
        "build",
        help="Pre-build container images for all stdio backends",
    )
    sp_build.add_argument(
        "-c",
        "--config",
        type=str,
        default=None,
        metavar="PATH",
        help="Path to configuration file (YAML). Default: auto-detect.",
    )
    sp_build.add_argument(
        "--parallel",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Build all container images concurrently instead of sequentially.",
    )
    _build_verbosity = sp_build.add_mutually_exclusive_group()
    _build_verbosity.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Increase build verbosity (-v, -vv).",
    )
    _build_verbosity.add_argument(
        "-q",
        "--quiet",
        "--silent",
        action="store_true",
        default=False,
        help="Suppress normal output (errors still shown).",
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
        metavar="NAME_OR_PID",
        help="Session name or PID to stop (optional if only one session is running)",
    )
    sp_stop.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Stop all running Argus servers (registered sessions and orphan processes)",
    )
    sp_stop.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Use SIGKILL immediately instead of SIGTERM",
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


__all__ = [
    # _common
    "_PID_FILE",
    "module_logger",
    # _server
    "_cmd_server",
    "_detach_server",
    "_remove_pid_file",
    "_run_server",
    "_write_pid_file",
    # _stop
    "_cleanup_pid_file",
    "_cmd_status",
    "_cmd_stop",
    "_stop_all_servers",
    "_stop_legacy_pid",
    "_stop_named_session",
    # _tui
    "_build_tui_server_manager",
    "_cmd_tui",
    "_load_client_config",
    "_resolve_tui_server_url",
    "_restore_terminal",
    # _build
    "_cmd_build",
    # _clean
    "_clean_images",
    "_clean_network",
    "_cmd_clean",
    "_detect_container_runtime",
    "_find_argus_containers",
    # _secret
    "_cmd_secret",
    # local
    "_build_parser",
    "main",
]
