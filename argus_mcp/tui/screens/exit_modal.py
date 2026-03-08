"""Graceful exit confirmation modal.

Displays running server count and offers save-state-and-restore,
stop-all-and-exit, or cancel options.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import Button, Label, RadioButton, RadioSet, Static

logger = logging.getLogger(__name__)


class ExitModal(ModalScreen[Optional[str]]):
    """Exit confirmation dialog with resume options."""

    DEFAULT_CSS = """
    ExitModal {
        align: center middle;
    }
    #exit-dialog {
        width: 56;
        height: auto;
        max-height: 18;
        border: thick $error;
        background: $surface;
        padding: 1 2;
    }
    #exit-title {
        text-style: bold;
        color: $error;
        text-align: center;
        margin-bottom: 1;
    }
    #exit-info {
        margin-bottom: 1;
    }
    #exit-choices {
        margin-bottom: 1;
    }
    #exit-actions {
        height: 3;
        align: center middle;
    }
    #exit-actions Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "confirm", "Confirm"),
    ]

    def __init__(self, running_count: int = 0, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._running_count = running_count

    def compose(self) -> ComposeResult:
        with Vertical(id="exit-dialog"):
            yield Label("[b]Exiting Argus MCP[/b]", id="exit-title")
            yield Static(
                f"{self._running_count} server(s) currently connected.",
                id="exit-info",
            )
            with RadioSet(id="exit-choices"):
                yield RadioButton("Save state and restore on next launch", value=True, id="rb-save")
                yield RadioButton("Stop all servers and exit", id="rb-stop")
                yield RadioButton("Cancel", id="rb-cancel")
            with Vertical(id="exit-actions"):
                yield Button("Confirm", variant="error", id="btn-exit-confirm")
                yield Button("Cancel", variant="default", id="btn-exit-cancel")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-exit-confirm":
            self.action_confirm()
        elif event.button.id == "btn-exit-cancel":
            self.action_cancel()

    def action_confirm(self) -> None:
        """Determine selected choice and dismiss."""
        try:
            radio_set = self.query_one("#exit-choices", RadioSet)
            idx = radio_set.pressed_index
            if idx == 0:
                self.dismiss("save-and-exit")
            elif idx == 1:
                self.dismiss("stop-and-exit")
            else:
                self.dismiss(None)
        except NoMatches:
            self.dismiss("stop-and-exit")

    def action_cancel(self) -> None:
        self.dismiss(None)
