"""Elicitation modal screen — displays elicitation form over any mode.

Appears as a centered modal when a backend tool requests interactive
user input via the MCP elicitation protocol.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional

from textual.containers import Center, Vertical
from textual.screen import ModalScreen

from argus_cli.tui.widgets.elicitation_form import ElicitationFormWidget

if TYPE_CHECKING:
    from argus_mcp.bridge.elicitation import ElicitationRequest
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class ElicitationScreen(ModalScreen[Optional[dict[str, Any]]]):
    """Modal screen for elicitation forms.

    Returns the form data dict on submit, or ``None`` on cancel.
    """

    CSS = """
    ElicitationScreen {
        align: center middle;
    }

    #elicitation-container {
        width: 60;
        max-height: 80%;
        background: $surface;
        border: heavy $primary;
        padding: 1 2;
    }

    #elicit-title {
        text-style: bold;
        margin-bottom: 1;
    }

    .field-label {
        margin-top: 1;
    }

    .field-desc {
        color: $text-muted;
        margin-bottom: 0;
    }

    #elicit-actions {
        margin-top: 2;
        height: auto;
    }
    """

    def __init__(self, request: ElicitationRequest, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._request = request

    def compose(self) -> ComposeResult:
        with Center(), Vertical(id="elicitation-container"):
            yield ElicitationFormWidget(self._request)

    def on_elicitation_form_widget_form_submitted(
        self,
        event: ElicitationFormWidget.FormSubmitted,
    ) -> None:
        """Handle form submission — dismiss with data."""
        self.dismiss(event.data)

    def on_elicitation_form_widget_form_cancelled(
        self,
        event: ElicitationFormWidget.FormCancelled,
    ) -> None:
        """Handle form cancellation — dismiss with None."""
        self.dismiss(None)
