"""Launcher for Textual dev tools — adds project root to sys.path.

The Textual MCP server is a long-running process that caches modules in
``sys.modules``.  To ensure every ``textual run`` invocation picks up the
latest source code we purge all ``argus_mcp`` sub-modules before
re-importing ``ArgusApp``.
"""

import glob  # noqa: I001
import importlib
import os
import sys

# Add both the project root and the .venv site-packages to sys.path
# so the Textual MCP server can resolve the package and its dependencies.
_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Also add the venv site-packages for dependencies like mcp, starlette, etc.
_venv_sp = glob.glob(os.path.join(_project_root, ".venv", "lib", "python*", "site-packages"))
for sp in _venv_sp:
    if sp not in sys.path:
        sys.path.insert(1, sp)

# Purge cached argus_mcp modules so the MCP server always uses fresh code.
_stale = [k for k in sys.modules if k == "argus_mcp" or k.startswith("argus_mcp.")]
for _k in _stale:
    del sys.modules[_k]

import argus_mcp.tui.app  # noqa: E402

importlib.reload(argus_mcp.tui.app)


def _resolve_server_url() -> str:
    """Resolve the Argus server URL from (highest priority first):

    1. ``ARGUS_TUI_SERVER`` environment variable
    2. ``client.server_url`` in ``config.yaml`` (searched in CWD)
    3. Hard-coded default ``http://127.0.0.1:9000``
    """
    env_url = os.environ.get("ARGUS_TUI_SERVER")
    if env_url:
        return env_url

    # Try loading the client section from config.yaml
    from argus_mcp.config.loader import find_config_file, load_argus_config

    candidate = find_config_file()
    if os.path.isfile(candidate):
        try:
            cfg = load_argus_config(candidate)
            return cfg.client.server_url
        except (OSError, ValueError):
            pass  # Fall through to default

    return "http://127.0.0.1:9000"


class DevArgusApp(argus_mcp.tui.app.ArgusApp):
    """Thin subclass so that the Textual MCP ``textual_launch`` tool can
    discover an ``App`` subclass in this module while passing our dev-time
    ``--server`` URL automatically.
    """

    def __init__(self) -> None:
        super().__init__(server_url=_resolve_server_url())
