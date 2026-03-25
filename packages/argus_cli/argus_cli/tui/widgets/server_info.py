"""Server information panel widget."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from argus_mcp.constants import SERVER_NAME, SERVER_VERSION
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from argus_cli.tui._error_utils import safe_query

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class ServerInfoWidget(Widget):
    """Displays server metadata in a compact panel."""

    server_name: reactive[str] = reactive(SERVER_NAME)
    server_version: reactive[str] = reactive(SERVER_VERSION)
    sse_url: reactive[str] = reactive("N/A")
    streamable_http_url: reactive[str] = reactive("N/A")
    transport_type: reactive[str] = reactive("streamable-http")
    status_text: reactive[str] = reactive("Initializing\u2026")

    # Kept internally for the command-palette detail view but not shown
    # in the sidebar panel.
    config_file: str = "N/A"
    log_file: str = "N/A"
    log_level: str = "INFO"

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        # Render cache: skip Static.update() when text unchanged
        self._cached_title: str = ""
        self._cached_body: str = ""
        self._refresh_pending: bool = False

    def compose(self) -> ComposeResult:
        yield Static("", id="title-row")
        yield Static("", id="info-body")

    def _render_title(self) -> str:
        return f"{self.server_name} v{self.server_version}"

    def _render_body(self) -> str:
        if self.transport_type == "streamable-http":
            url_label = "Endpoint"
            url_value = self.streamable_http_url
        else:
            url_label = "SSE"
            url_value = self.sse_url

        lines = [
            f"[b]{url_label}:[/b]  {url_value}",
            "",
            f"[b]Status:[/b]  {self.status_text}",
        ]
        return "\n".join(lines)

    def _refresh_display(self) -> None:
        title = self._render_title()
        if title != self._cached_title:
            self._cached_title = title
            if w := safe_query(self, "#title-row", Static):
                w.update(title)
        body = self._render_body()
        if body != self._cached_body:
            self._cached_body = body
            if w := safe_query(self, "#info-body", Static):
                w.update(body)

    def _schedule_refresh(self) -> None:
        """Coalesce multiple watcher calls into a single refresh."""
        if not self._refresh_pending:
            self._refresh_pending = True
            self.call_later(self._do_deferred_refresh)

    def _do_deferred_refresh(self) -> None:
        self._refresh_pending = False
        self._refresh_display()

    # Watchers – coalesce into a single deferred refresh
    def watch_server_name(self) -> None:
        self._schedule_refresh()

    def watch_server_version(self) -> None:
        self._schedule_refresh()

    def watch_sse_url(self) -> None:
        self._schedule_refresh()

    def watch_streamable_http_url(self) -> None:
        self._schedule_refresh()

    def watch_transport_type(self) -> None:
        self._schedule_refresh()

    def watch_status_text(self) -> None:
        self._schedule_refresh()

    def on_mount(self) -> None:
        self._refresh_display()

    def apply_status_info(self, info: dict) -> None:
        """Bulk-update from a ``gen_status_info`` dict."""
        import os

        if info.get("sse_url"):
            self.sse_url = info["sse_url"]
        if info.get("streamable_http_url"):
            self.streamable_http_url = info["streamable_http_url"]
        if info.get("transport_type"):
            self.transport_type = info["transport_type"]
        if info.get("cfg_fpath"):
            self.config_file = os.path.basename(info["cfg_fpath"])
        if info.get("log_fpath"):
            self.log_file = info["log_fpath"]
        if info.get("log_lvl_cfg"):
            self.log_level = info["log_lvl_cfg"]
        if info.get("status_msg"):
            self.status_text = info["status_msg"]
