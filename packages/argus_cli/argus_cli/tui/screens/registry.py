"""Registry mode — browse, search, and install MCP servers from registries.

Provides:
* A :class:`RegistryBrowserWidget` with search bar and ``DataTable``
* A :class:`InstallPanelWidget` showing server details and install button
* Async loading from configured registries via :class:`RegistryClient`
* Install-to-config with hot-reload support
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from typing import TYPE_CHECKING, Any

from argus_mcp.registry.cache import RegistryCache
from argus_mcp.registry.client import RegistryClient
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import Static

from argus_cli.tui._config_ops import resolve_config_path, trigger_reload, write_backend_to_config
from argus_cli.tui.screens.backend_config import BackendConfigModal
from argus_cli.tui.screens.base import ArgusScreen
from argus_cli.tui.screens.server_detail import (
    ServerDetailModal,  # noqa: F401 — kept for external refs
)
from argus_cli.tui.widgets.install_panel import InstallConfirmed, InstallPanelWidget
from argus_cli.tui.widgets.registry_browser import (
    InstallRequested,
    RegistryBrowserWidget,
    RegistryServerHighlighted,
)

if TYPE_CHECKING:
    from argus_mcp.registry.models import ServerEntry
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class RegistryScreen(ArgusScreen):
    """Registry mode — server browser and install panel.

    On mount, fetches the server catalog from configured registries
    (with cache fallback) and populates the browser widget.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._installed_names: set[str] = set()

    def compose_content(self) -> ComposeResult:
        with Vertical(id="registry-content"):
            yield Static(
                "[b]Registry[/b]  •  Browse and install MCP servers",
                id="registry-header",
            )
            yield Static("", id="registry-status-bar")
            with Horizontal(id="registry-layout"):
                yield RegistryBrowserWidget(id="registry-browser")
                yield InstallPanelWidget(id="install-panel")

    def on_mount(self) -> None:
        """Kick off async registry fetch."""
        self._cache = RegistryCache()
        self._clients: list[RegistryClient] = []
        self._load_task: asyncio.Task[None] | None = asyncio.create_task(self._load_registry())
        self._load_task.add_done_callback(self._on_load_task_done)

    @staticmethod
    def _on_load_task_done(task: asyncio.Task[None]) -> None:
        """Log unhandled exceptions from the registry load task."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("Registry load failed: %s", exc)

    async def _load_registry(self) -> None:
        """Fetch servers from all configured registries."""
        browser = self.query_one("#registry-browser", RegistryBrowserWidget)
        browser.set_status("Loading registry…")

        registry_configs = self._get_registry_configs()

        if not registry_configs:
            browser.set_status(
                "[yellow]No registries configured.[/yellow]  "
                "Add one in Settings → Registries or in config.yaml under 'registries:'."
            )
            self._set_status("No registries configured")
            return

        all_entries: list[ServerEntry] = []
        ok_count = 0

        for rcfg in registry_configs:
            url = rcfg["url"]
            rtype = rcfg.get("type", "auto")
            client = RegistryClient(url, registry_type=rtype, cache=self._cache)
            self._clients.append(client)
            entries = await client.list_all_servers()
            if entries:
                all_entries.extend(entries)
                ok_count += 1

        browser.entries = all_entries
        if all_entries:
            status_msg = (
                f"Loaded {len(all_entries)} servers from "
                f"{ok_count}/{len(registry_configs)} registries"
            )
        elif registry_configs:
            status_msg = (
                "No servers found — registries may be unavailable.  Check logs for details."
            )
        else:
            status_msg = "No registries configured."
        browser.set_status(status_msg)
        self._set_status(status_msg)

    def _get_registry_configs(self) -> list[dict[str, Any]]:
        """Retrieve configured registry entries as dicts with url and type.

        Merges registries from all sources, deduplicating by URL:
        1. ``registries`` list in TUI settings (``settings.json``)
        2. ``registries`` section in the loaded ``ArgusConfig``
        3. Default well-known MCP registries (only if no other source found)
        """
        seen_urls: set[str] = set()
        configs: list[dict[str, Any]] = []

        def _add(url: str, rtype: str = "auto") -> None:
            normalized = url.rstrip("/").lower()
            if normalized not in seen_urls:
                seen_urls.add(normalized)
                configs.append({"url": url.rstrip("/"), "type": rtype})

        # 1. TUI settings.json registries
        try:
            from argus_cli.tui.settings import load_settings

            settings = load_settings()
            cfg_registries = settings.get("registries", [])
            if cfg_registries:
                sorted_regs = sorted(cfg_registries, key=lambda r: r.get("priority", 100))
                for r in sorted_regs:
                    if r.get("url"):
                        _add(r["url"], r.get("type", "auto"))
        except (KeyError, ValueError, OSError):
            logger.debug("Could not read registries from settings", exc_info=True)

        # 2. ArgusConfig registries from config.yaml (merge, not override)
        try:
            from argus_mcp.config.loader import find_config_file, load_argus_config

            cfg_path = find_config_file()
            argus_cfg = load_argus_config(cfg_path)
            sorted_regs = sorted(argus_cfg.registries, key=lambda r: r.priority)
            for r in sorted_regs:
                _add(r.url, getattr(r, "type", "auto"))
        except Exception:
            logger.debug("Could not read registries from config.yaml", exc_info=True)

        # 3. Fall back to well-known registries only if nothing found
        if not configs:
            _add("https://glama.ai/api/mcp", "glama")
            _add("https://registry.smithery.ai", "smithery")

        return configs

    def _set_status(self, text: str) -> None:
        """Update the status bar below the header."""
        with contextlib.suppress(NoMatches):
            self.query_one("#registry-status-bar", Static).update(text)

    def on_registry_server_highlighted(self, event: RegistryServerHighlighted) -> None:
        """Update the install panel when a server is highlighted."""
        panel = self.query_one("#install-panel", InstallPanelWidget)
        panel.selected_entry = event.entry

    def on_install_requested(self, event: InstallRequested) -> None:
        """Handle Enter key on a server row — open config modal."""
        entry = event.entry

        def _on_config_result(result: tuple | None) -> None:
            if result is not None:
                name, config = result
                self._do_install(name, entry, config)

        self.app.push_screen(BackendConfigModal(entry=entry), _on_config_result)

    def on_install_confirmed(self, event: InstallConfirmed) -> None:
        """Side panel install — open config modal for review/edit."""
        entry = event.entry

        def _on_config_result(result: tuple | None) -> None:
            if result is not None:
                name, config = result
                self._do_install(name, entry, config)

        self.app.push_screen(BackendConfigModal(entry=entry), _on_config_result)

    def _do_install(
        self,
        name: str,
        entry: ServerEntry,
        config: dict[str, Any],
    ) -> None:
        """Shared install logic for both panel and modal flows."""
        logger.info("Install confirmed: %s → %s", name, json.dumps(config))

        # Write to config file
        config_path = self._resolve_config_path()
        if config_path is None:
            self.notify(
                "Cannot determine config file path. Add manually.",
                severity="warning",
                title="Install Skipped",
            )
            return

        success = self._write_backend_to_config(config_path, name, config)
        if not success:
            return

        self._installed_names.add(name)
        self.notify(
            f"Added [b]{name}[/b] to {os.path.basename(config_path)}",
            title="Server Installed",
        )
        self._set_status(f"Installed '{name}' — triggering reload…")

        # Trigger config hot-reload via the management API
        self._trigger_reload()

    def _resolve_config_path(self) -> str | None:
        return resolve_config_path(self.app)

    def _write_backend_to_config(
        self, config_path: str, backend_name: str, backend_config: dict[str, Any]
    ) -> bool:
        return write_backend_to_config(
            config_path, backend_name, backend_config, notify=self.notify
        )

    def _trigger_reload(self) -> None:
        trigger_reload(
            self.app,
            status_callback=self._set_status,
            notify=self.notify,
            worker_name="registry-reload",
        )
