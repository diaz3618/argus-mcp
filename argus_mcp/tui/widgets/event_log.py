"""Scrollable event log widget using RichLog."""

from __future__ import annotations

import logging
from datetime import datetime

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import RichLog

# Stage → colour mapping
_STAGE_COLOURS: dict[str, str] = {
    "Initialization": "bright_cyan",
    "Config Load": "bright_blue",
    "Backend Connection": "bright_magenta",
    "Capability Discovery": "bright_yellow",
    "✅ Service Ready": "green",
    "Startup Failed": "red",
    "🛑 Shutting Down": "dark_orange",
    "✅ Final Status": "green",
    "❌ Final Status": "red",
}


class _CaptureRichLog(RichLog):
    """RichLog subclass that captures print() output.

    Follows the canonical Textual pattern:
    ``widget.begin_capture_print()`` routes stray ``print()`` calls
    to an ``on_print`` handler so they appear inside the Events panel
    instead of corrupting the terminal.
    """

    def on_print(self, event: events.Print) -> None:  # noqa: D401
        """Receive a captured print event and write it to the log."""
        text = event.text.rstrip("\n")
        if text:
            ts = datetime.now().strftime("%H:%M:%S")
            line = Text.assemble(
                (f"[{ts}] ", "dim"),
                (text, "dim italic"),
            )
            self.write(line)


class EventLogWidget(Widget):
    """Real-time scrolling log of server lifecycle events."""

    BORDER_TITLE = "Events"

    def compose(self) -> ComposeResult:
        yield _CaptureRichLog(
            highlight=True,
            markup=True,
            wrap=True,
            auto_scroll=True,
            id="event-rich-log",
        )

    @property
    def log_widget(self) -> _CaptureRichLog:
        return self.query_one("#event-rich-log", _CaptureRichLog)

    def start_capture(self) -> None:
        """Begin capturing ``print()`` output into this log.

        Uses ``call_after_refresh`` to ensure the widget tree is fully
        composed before activating the capture, which avoids a race
        condition where the ``RichLog`` widget is not yet associated with
        the running ``App`` instance.
        """

        def _begin() -> None:
            try:
                self.log_widget.begin_capture_print()
            except Exception:  # noqa: BLE001
                logging.getLogger(__name__).debug("begin_capture_print failed", exc_info=True)

        self.call_after_refresh(_begin)

    def stop_capture(self) -> None:
        """Stop capturing ``print()`` output."""
        try:
            self.log_widget.end_capture_print()
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).debug("end_capture_print failed", exc_info=True)

    def add_event(
        self,
        stage: str,
        message: str,
        *,
        timestamp: str | None = None,
        extra_lines: list[str] | None = None,
    ) -> None:
        """Append a formatted event entry to the log."""
        ts = timestamp or datetime.now().strftime("%H:%M:%S")
        colour = _STAGE_COLOURS.get(stage, "white")

        header = Text.assemble(
            (f"[{ts}] ", "dim"),
            (f"{stage}: ", colour),
            (message, "bold"),
        )
        self.log_widget.write(header)

        if extra_lines:
            for line in extra_lines:
                indent = Text.assemble(("    ", ""), (line, ""))
                self.log_widget.write(indent)

    def add_raw(self, text: str) -> None:
        """Append a plain text line."""
        self.log_widget.write(text)

    def add_separator(self) -> None:
        """Write a visual separator."""
        self.log_widget.write(Text("─" * 60, style="dim"))
