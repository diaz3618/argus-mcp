"""Security mode — authentication, authorization, secrets, and network.

Consolidates all security-related configuration that was previously
scattered across Settings tabs into a single focused mode.
"""

from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.widgets import (
    Button,
    Input,
    Label,
    Select,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)

from argus_mcp.tui.screens.base import ArgusScreen

logger = logging.getLogger(__name__)


class SecurityScreen(ArgusScreen):
    """Security configuration mode — auth, policies, secrets, network."""

    def compose_content(self) -> ComposeResult:
        with TabbedContent(id="security-tabs"):
            with TabPane("Authentication", id="tab-sec-auth"):
                with Vertical(id="sec-auth-section"):
                    yield Static("[b]Incoming Authentication[/b]", id="sec-incoming-title")
                    with Horizontal(classes="setting-row"):
                        yield Label("Auth Mode:", classes="setting-label")
                        yield Select(
                            [
                                ("none — open access", "none"),
                                ("bearer — static token", "bearer"),
                                ("oidc — OpenID Connect", "oidc"),
                            ],
                            value="none",
                            id="sec-auth-mode-select",
                            allow_blank=False,
                        )
                    with Vertical(id="sec-bearer-section"):
                        with Horizontal(classes="setting-row"):
                            yield Label("Bearer Token:", classes="setting-label")
                            yield Input(
                                placeholder="(static token for incoming requests)",
                                id="sec-bearer-token-input",
                                password=True,
                            )
                    with Vertical(id="sec-oidc-section"):
                        with Horizontal(classes="setting-row"):
                            yield Label("OIDC Issuer:", classes="setting-label")
                            yield Input(
                                placeholder="https://accounts.example.com",
                                id="sec-oidc-issuer-input",
                            )
                        with Horizontal(classes="setting-row"):
                            yield Label("OIDC Audience:", classes="setting-label")
                            yield Input(
                                placeholder="argus-mcp",
                                id="sec-oidc-audience-input",
                            )
                        with Horizontal(classes="setting-row"):
                            yield Label("JWKS URI:", classes="setting-label")
                            yield Input(
                                placeholder="(auto-discovered from issuer)",
                                id="sec-oidc-jwks-input",
                            )

                    yield Static(
                        "[b]Outgoing Authentication (per server)[/b]",
                        id="sec-outgoing-title",
                    )
                    yield Static(
                        "[dim]Configure authentication for each backend server connection.[/dim]",
                        id="sec-outgoing-hint",
                    )
                    with Horizontal(classes="setting-row"):
                        yield Label("Backend:", classes="setting-label")
                        yield Select([], id="sec-backend-select", allow_blank=True)
                    with Horizontal(classes="setting-row"):
                        yield Label("Auth Type:", classes="setting-label")
                        yield Select(
                            [
                                ("none", "none"),
                                ("bearer", "bearer"),
                                ("api-key", "api-key"),
                                ("basic", "basic"),
                            ],
                            value="none",
                            id="sec-outgoing-type-select",
                            allow_blank=False,
                        )
                    with Horizontal(classes="setting-row"):
                        yield Label("Credential:", classes="setting-label")
                        yield Input(
                            placeholder="token / api-key / user:pass",
                            id="sec-outgoing-credential-input",
                            password=True,
                        )

            with TabPane("Policies", id="tab-sec-policies"):
                with Vertical(id="sec-authz-section"):
                    yield Static("[b]Authorization Policies[/b]", id="sec-authz-title")
                    yield Static(
                        "[dim]Define RBAC rules for tool/resource access control.[/dim]",
                        id="sec-authz-hint",
                    )
                    yield TextArea(
                        "# Authorization policies (YAML)\n"
                        "# Example:\n"
                        "# policies:\n"
                        "#   - role: admin\n"
                        '#     allow: ["*"]\n'
                        "#   - role: reader\n"
                        '#     allow: ["read_*", "list_*"]\n'
                        '#     deny: ["delete_*"]\n',
                        id="sec-authz-policies-editor",
                        language="yaml",
                    )
                    with Horizontal(classes="setting-row"):
                        yield Button(
                            "Apply Policies",
                            id="btn-apply-policies",
                            variant="primary",
                        )

            with TabPane("Secrets", id="tab-sec-secrets"):
                from argus_mcp.tui.widgets.secrets_panel import SecretsPanel

                yield SecretsPanel(id="secrets-panel-widget")

            with TabPane("Network", id="tab-sec-network"):
                from argus_mcp.tui.widgets.network_panel import (
                    NetworkIsolationPanel,
                )

                yield NetworkIsolationPanel(id="network-panel-widget")

    def on_show(self) -> None:
        """Populate backend selector for outgoing auth."""
        self._refresh_security()

    def _refresh_security(self) -> None:
        """Populate selectors from cached app state."""
        caps = self.app.last_caps
        if caps is None:
            return
        route_map = getattr(caps, "route_map", {})
        options = [(name, name) for name in sorted(route_map.keys())]
        try:
            self.query_one("#sec-backend-select", Select).set_options(options)
        except NoMatches:
            pass

        status = self.app.last_status
        if status is not None:
            ff = getattr(status, "feature_flags", {}) or {}
            outgoing_auth = ff.get("outgoing_auth", False)
            # If the TUI is connected with a token, the server uses bearer auth
            mgr = self.app.server_manager
            if mgr and mgr.active_entry and mgr.active_entry.token:
                try:
                    self.query_one("#sec-auth-mode-select", Select).value = "bearer"
                except NoMatches:
                    pass
            outgoing_label = "enabled" if outgoing_auth else "disabled"
            try:
                self.query_one("#sec-outgoing-hint", Static).update(
                    f"[dim]Outgoing auth: {outgoing_label}. "
                    f"Configure authentication for each backend server connection.[/dim]"
                )
            except NoMatches:
                pass

            container_isolation = ff.get("container_isolation", False)
            try:
                from argus_mcp.tui.widgets.network_panel import NetworkIsolationPanel

                net_panel = self.query_one(NetworkIsolationPanel)
                net_panel.load_config(
                    {
                        "network_mode": "bridge" if container_isolation else "host",
                    }
                )
            except NoMatches:
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-apply-policies":
            self._do_apply_policies()

    def _do_apply_policies(self) -> None:
        """Validate authorization policies YAML.

        The management API does not support remote policy writes.
        Policies must be configured in the server config file.
        """
        try:
            editor = self.query_one("#sec-authz-policies-editor", TextArea)
            text = editor.text.strip()
            if not text or text.startswith("#"):
                self.notify("No policies to validate", severity="warning")
                return
            try:
                import yaml

                data = yaml.safe_load(text)
                policies = data.get("policies", []) if isinstance(data, dict) else []
                self.notify(
                    f"Validated {len(policies)} policy rules. "
                    f"Copy to server config and reload to apply.",
                    title="Policies",
                    timeout=5,
                )
            except ImportError:
                self.notify(
                    "YAML parser not available — install PyYAML",
                    severity="error",
                )
            except yaml.YAMLError as exc:
                self.notify(f"Invalid YAML: {exc}", severity="error")
        except NoMatches:
            logger.debug("Could not apply policies", exc_info=True)
