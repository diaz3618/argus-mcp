"""Server selector widget for multi-server TUI support.

Displays a compact list of named Argus servers with connection-status
indicators.  Clicking a server (or using the keyboard) emits a
:class:`ServerSelected` message so the parent app can switch the active
connection.
"""

from __future__ import annotations

import logging
from typing import Optional

from textual.app import ComposeResult
from textual.message import Message
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import OptionList, Static
from textual.widgets.option_list import Option

logger = logging.getLogger(__name__)

_ICON_CONNECTED = "●"  # green dot (styled via Rich markup)
_ICON_DISCONNECTED = "○"  # hollow dot
_ICON_ACTIVE = "▸"  # pointer showing active


class ServerSelected(Message):
    """Emitted when the user picks a different server."""

    def __init__(self, server_name: str) -> None:
        self.server_name = server_name
        super().__init__()


class ServerSelectorWidget(Widget):
    """Compact server list in the sidebar.

    Each row shows:  ``▸ ● server-name  (url)``

    The pointer (▸) indicates the *active* server.  The dot colour
    reflects connection health.
    """

    # Reactive: number of servers (triggers re-render on change)
    server_count: reactive[int] = reactive(0)

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._server_data: list[dict[str, object]] = []
        self._active_name: Optional[str] = None

    def compose(self) -> ComposeResult:
        yield Static("[b]Servers[/b]", id="srv-selector-title")
        yield OptionList(id="srv-option-list")

    def on_mount(self) -> None:
        option_list = self.query_one("#srv-option-list", OptionList)
        option_list.can_focus = True

    def refresh_servers(
        self,
        servers: list[dict[str, object]],
        active_name: Optional[str] = None,
    ) -> None:
        """Rebuild the option list from the current server entries.

        Parameters
        ----------
        servers:
            List of dicts with keys ``name``, ``url``, ``connected`` (bool).
        active_name:
            The currently active server name.
        """
        self._server_data = servers
        self._active_name = active_name
        self.server_count = len(servers)

        option_list = self.query_one("#srv-option-list", OptionList)
        option_list.clear_options()

        for srv in servers:
            name = str(srv.get("name", ""))
            url = str(srv.get("url", ""))
            connected = bool(srv.get("connected", False))

            pointer = _ICON_ACTIVE if name == active_name else " "
            dot = (
                f"[green]{_ICON_CONNECTED}[/green]"
                if connected
                else f"[red]{_ICON_DISCONNECTED}[/red]"
            )
            label = f"{pointer} {dot} {name}  [dim]{url}[/dim]"
            option_list.add_option(Option(label, id=name))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """User clicked / pressed Enter on a server entry."""
        option_id = event.option.id
        if option_id and option_id != self._active_name:
            self.post_message(ServerSelected(str(option_id)))
