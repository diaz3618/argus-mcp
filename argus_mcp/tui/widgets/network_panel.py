"""Network isolation configuration widget — per-server network policy controls.

Displays allowed outbound hosts, environment restrictions,
and network mode picker for container-isolated MCP server execution.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Input, Label, Select, TextArea

logger = logging.getLogger(__name__)


class NetworkIsolationPanel(Widget):
    """Per-server network isolation configuration."""

    DEFAULT_CSS = """
    NetworkIsolationPanel {
        height: auto;
        max-height: 20;
        padding: 0 1;
    }
    #net-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 0;
    }
    #net-mode-row {
        height: 3;
        align: left middle;
    }
    #net-hosts-area {
        height: 6;
        margin: 1 0;
    }
    #net-env-section {
        margin-top: 1;
    }
    """

    def __init__(self, server_name: str = "", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._server_name = server_name

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(
                f"[b]Network Isolation — {self._server_name or 'Select Server'}[/b]",
                id="net-title",
            )

            with Horizontal(id="net-mode-row"):
                yield Label("Network Mode:", classes="setting-label")
                yield Select(
                    [
                        ("host — no isolation", "host"),
                        ("bridge — filtered outbound", "bridge"),
                        ("none — fully offline", "none"),
                    ],
                    value="host",
                    id="net-mode-select",
                    allow_blank=False,
                )

            yield Label("[b]Allowed Outbound Hosts:[/b]")
            yield TextArea(
                "# One host per line\n# e.g. api.github.com\n# * = all hosts",
                id="net-hosts-area",
                language="text",
            )

            with Vertical(id="net-env-section"):
                yield Label("[b]Environment Restrictions:[/b]")
                with Horizontal(classes="setting-row"):
                    yield Label("HTTP_PROXY:", classes="setting-label")
                    yield Input(placeholder="(blank = inherit host)", id="net-proxy-input")
                with Horizontal(classes="setting-row"):
                    yield Label("NO_PROXY:", classes="setting-label")
                    yield Input(placeholder="localhost,127.0.0.1", id="net-noproxy-input")
                with Horizontal(classes="setting-row"):
                    yield Label("DNS:", classes="setting-label")
                    yield Select(
                        [("system", "system"), ("custom", "custom"), ("cloudflare", "cloudflare")],
                        value="system",
                        id="net-dns-select",
                        allow_blank=False,
                    )

    def load_config(self, config: Dict[str, Any]) -> None:
        """Load network isolation settings from config dict."""
        try:
            mode = config.get("network_mode", "host")
            self.query_one("#net-mode-select", Select).value = mode

            hosts = config.get("allowed_hosts", [])
            if hosts:
                self.query_one("#net-hosts-area", TextArea).load_text("\n".join(hosts))

            proxy = config.get("http_proxy", "")
            self.query_one("#net-proxy-input", Input).value = proxy

            noproxy = config.get("no_proxy", "localhost,127.0.0.1")
            self.query_one("#net-noproxy-input", Input).value = noproxy
        except Exception:
            logger.debug("Cannot load network config", exc_info=True)

    def get_config(self) -> Dict[str, Any]:
        """Collect current network isolation settings."""
        result: Dict[str, Any] = {}
        try:
            result["network_mode"] = self.query_one("#net-mode-select", Select).value
            hosts_text = self.query_one("#net-hosts-area", TextArea).text
            result["allowed_hosts"] = [
                h.strip()
                for h in hosts_text.splitlines()
                if h.strip() and not h.strip().startswith("#")
            ]
            result["http_proxy"] = self.query_one("#net-proxy-input", Input).value
            result["no_proxy"] = self.query_one("#net-noproxy-input", Input).value
            result["dns"] = self.query_one("#net-dns-select", Select).value
        except Exception:
            logger.debug("Cannot read network config", exc_info=True)
        return result
