"""Server information panel widget."""

from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from argus_mcp._error_utils import safe_query
from argus_mcp.constants import SERVER_NAME, SERVER_VERSION

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
        if w := safe_query(self, "#title-row", Static):
            w.update(self._render_title())
        if w := safe_query(self, "#info-body", Static):
            w.update(self._render_body())

    # Watchers – auto-refresh on any reactive change
    def watch_server_name(self) -> None:
        self._refresh_display()

    def watch_server_version(self) -> None:
        self._refresh_display()

    def watch_sse_url(self) -> None:
        self._refresh_display()

    def watch_streamable_http_url(self) -> None:
        self._refresh_display()

    def watch_transport_type(self) -> None:
        self._refresh_display()

    def watch_status_text(self) -> None:
        self._refresh_display()

    def on_mount(self) -> None:
        self._refresh_display()

    # ── Public helpers ──────────────────────────────────────────

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
