"""Launcher for Textual dev tools — adds project root to sys.path.

The Textual MCP server is a long-running process that caches modules in
``sys.modules``.  To ensure every ``textual run`` invocation picks up the
latest source code we purge all ``argus_mcp`` sub-modules before
re-importing ``ArgusApp``.
"""

import glob
import importlib
import os
import sys

# Add both the argus_cli package root and the workspace root to sys.path
# so the Textual MCP server can resolve both packages and their dependencies.
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# The workspace root is two levels above _project_root (packages/argus_cli/ -> argus-mcp/)
_workspace_root = os.path.dirname(os.path.dirname(_project_root))
if _workspace_root not in sys.path:
    sys.path.insert(0, _workspace_root)

# Also add the venv site-packages for dependencies like mcp, starlette, etc.
_venv_sp = glob.glob(os.path.join(_workspace_root, ".venv", "lib", "python*", "site-packages"))
for sp in _venv_sp:
    if sp not in sys.path:
        sys.path.insert(1, sp)

# Purge cached argus_cli and argus_mcp modules so the MCP server always uses fresh code.
_stale = [
    k
    for k in sys.modules
    if k in ("argus_cli", "argus_mcp") or k.startswith(("argus_cli.", "argus_mcp."))
]
for _k in _stale:
    del sys.modules[_k]

import argus_cli.tui.app  # noqa: E402

importlib.reload(argus_cli.tui.app)


def _resolve_client_settings() -> tuple[str, str | None]:
    """Resolve the Argus server URL and token from (highest priority first):

    1. ``ARGUS_TUI_SERVER`` / ``ARGUS_MGMT_TOKEN`` environment variables
    2. ``client.server_url`` / ``client.token`` in ``config.yaml`` (searched in CWD)
    3. Hard-coded default ``http://127.0.0.1:9000`` / ``None``
    """
    env_url = os.environ.get("ARGUS_TUI_SERVER")
    env_token = os.environ.get("ARGUS_MGMT_TOKEN")
    if env_url:
        return env_url, env_token

    # Try loading the client section from config.yaml
    from argus_mcp.config.loader import find_config_file, load_argus_config

    candidate = find_config_file()
    if os.path.isfile(candidate):
        try:
            cfg = load_argus_config(candidate)
            url = cfg.client.server_url
            token = getattr(cfg.client, "token", None) or env_token
            return url, token
        except (OSError, ValueError):
            pass  # Fall through to default

    return "http://127.0.0.1:9000", env_token


class DevArgusApp(argus_cli.tui.app.ArgusApp):
    """Thin subclass so that the Textual MCP ``textual_launch`` tool can
    discover an ``App`` subclass in this module while passing our dev-time
    ``--server`` URL and token automatically.
    """

    def __init__(self) -> None:
        url, token = _resolve_client_settings()
        super().__init__(server_url=url, token=token)
