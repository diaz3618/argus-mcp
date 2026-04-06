"""Shared config operations for TUI screens.

Consolidates config-file discovery, backend-writing, and hot-reload
logic that was previously duplicated across multiple screen files.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

import yaml  # type: ignore[import-untyped]
from argus_mcp.config.loader import find_config_file

from argus_cli.tui.api_client import ApiClientError

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


def resolve_config_path(app: Any) -> str | None:
    """Find the config file path from server status or defaults.

    Checks ``app.last_status.config.file_path`` first, then falls
    back to :func:`find_config_file`.
    """
    status = app.last_status
    if status is not None:
        path = getattr(status.config, "file_path", None)
        if path and os.path.isfile(path):
            return path
    path = find_config_file()
    return path if os.path.isfile(path) else None


def write_backend_to_config(
    config_path: str,
    backend_name: str,
    backend_config: dict[str, Any],
    *,
    notify: Callable[..., None] | None = None,
) -> bool:
    """Append a backend entry to the YAML config file.

    Returns ``True`` on success, ``False`` on duplicate or error.
    """
    try:
        with open(config_path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}

        backends: dict[str, Any] = data.setdefault("backends", {})
        if backend_name in backends:
            if notify:
                notify(
                    f"Backend '{backend_name}' already exists in config",
                    severity="warning",
                )
            return False

        backends[backend_name] = backend_config

        with open(config_path, "w", encoding="utf-8") as fh:
            yaml.dump(data, fh, default_flow_style=False, sort_keys=False)

        logger.info("Wrote backend '%s' to %s", backend_name, config_path)
        return True

    except (OSError, yaml.YAMLError) as exc:
        logger.error("Failed to write config: %s", exc)
        if notify:
            notify(f"Failed to write config: {exc}", severity="error")
        return False


def trigger_reload(
    app: Any,
    *,
    status_callback: Callable[[str], None] | None = None,
    notify: Callable[..., None] | None = None,
    worker_name: str = "config-reload",
) -> None:
    """Post a config reload request via the active server's management API.

    Runs the reload in a Textual worker so callers don't need to manage
    the async lifecycle themselves.
    """
    mgr = app.server_manager
    if mgr is None:
        return
    client = getattr(mgr, "active_client", None)
    if client is None:
        if status_callback:
            status_callback("Cannot reload — not connected to server")
        return

    async def _do_reload() -> None:
        try:
            result = await client.post_reload()
            if result.reloaded:
                added = ", ".join(result.backends_added) or "none"
                if status_callback:
                    status_callback(f"Reload complete — added: {added}")
                if notify:
                    notify("Config reloaded successfully", title="Reload")
            else:
                errors = "; ".join(result.errors) if result.errors else "unknown"
                if status_callback:
                    status_callback(f"Reload failed: {errors}")
                if notify:
                    notify(f"Reload errors: {errors}", severity="warning")
        except (OSError, ConnectionError, ApiClientError) as exc:
            logger.warning("Reload request failed: %s", exc)
            if status_callback:
                status_callback(f"Reload failed: {exc}")

    app.run_worker(_do_reload(), exclusive=True, name=worker_name)
