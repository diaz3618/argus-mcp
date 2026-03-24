"""OpenTelemetry metrics and traces panel.

Displays request metrics, per-backend breakdown, and recent trace
waterfall when OTel integration is enabled.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import DataTable, Label, Static

from argus_cli.tui._error_utils import safe_query

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)


class OTelPanel(Widget):
    """OpenTelemetry metrics and trace display widget."""

    DEFAULT_CSS = """
    OTelPanel {
        height: auto;
        max-height: 24;
        border: round $accent;
        padding: 0 1;
    }
    #otel-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 0;
    }
    #otel-status {
        height: 1;
        color: $text-muted;
    }
    #otel-metrics {
        height: auto;
        max-height: 4;
        padding: 0 1;
        margin: 1 0;
    }
    #otel-backend-table {
        height: auto;
        max-height: 8;
    }
    #otel-trace {
        height: auto;
        max-height: 6;
        padding: 0 1;
        margin-top: 1;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._enabled: bool = False

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label("[b]Telemetry[/b] — OpenTelemetry Integration", id="otel-title")
            yield Static("OTel: [dim]● inactive[/dim]", id="otel-status")

            yield Static("[b]Request Metrics[/b]")
            yield Static(
                "  Total requests: —     Errors: —\n"
                "  Avg latency: —        P99: —\n"
                "  Active sessions: —",
                id="otel-metrics",
            )

            yield Static("[b]Per-Backend Breakdown[/b]")
            yield DataTable(id="otel-backend-table")

            yield Static("[b]Last Trace[/b]")
            yield Static("(no traces captured)", id="otel-trace")

    def on_mount(self) -> None:
        if table := safe_query(self, "#otel-backend-table", DataTable):
            table.add_columns("Backend", "Calls", "Avg ms", "Err%", "Health")
            table.cursor_type = "row"
            table.zebra_stripes = True

    def update_otel_status(
        self,
        enabled: bool = False,
        exporter: str = "",
        prometheus_url: str = "",
    ) -> None:
        """Update OTel connection status."""
        self._enabled = enabled
        if enabled:
            status = f"OTel: [green]● active[/green]    Exporter: {exporter}"
            if prometheus_url:
                status += f"    Prometheus: {prometheus_url}"
        else:
            status = "OTel: [dim]● inactive[/dim]    (enable in config)"

        if w := safe_query(self, "#otel-status", Static):
            w.update(status)

    def update_metrics(
        self,
        total_requests: int = 0,
        errors: int = 0,
        avg_latency_ms: float = 0,
        p99_latency_ms: float = 0,
        active_sessions: int = 0,
    ) -> None:
        """Update aggregate request metrics."""
        err_pct = (errors / total_requests * 100) if total_requests > 0 else 0
        text = (
            f"  Total requests (1h): {total_requests:,}     Errors: {errors} ({err_pct:.1f}%)\n"
            f"  Avg latency: {avg_latency_ms:.0f}ms        P99: {p99_latency_ms:.0f}ms\n"
            f"  Active sessions: {active_sessions}"
        )
        if w := safe_query(self, "#otel-metrics", Static):
            w.update(text)

    def update_backend_breakdown(self, backends: list[dict[str, Any]]) -> None:
        """Update the per-backend metrics table."""
        if table := safe_query(self, "#otel-backend-table", DataTable):
            table.clear()
            for b in backends:
                name = b.get("name", "?")
                calls = b.get("calls", 0)
                avg_ms = b.get("avg_latency_ms", 0)
                err_pct = b.get("error_percent", 0)
                health = b.get("health", {})
                health_status = (
                    health.get("status", "unknown") if isinstance(health, dict) else str(health)
                )

                if health_status == "healthy":
                    health_display = "[green]●[/green]"
                elif health_status == "degraded":
                    health_display = "[yellow]◑[/yellow]"
                else:
                    health_display = "[red]✕[/red]"

                table.add_row(
                    name,
                    str(calls),
                    f"{avg_ms:.0f}",
                    f"{err_pct:.1f}%",
                    health_display,
                )

    def update_trace(self, trace_info: dict[str, Any]) -> None:
        """Display a trace waterfall for the last request."""
        tool = trace_info.get("tool", "—")
        spans = trace_info.get("spans", [])
        total_ms = trace_info.get("total_ms", 0)
        lines = [f"  {tool} — Total: {total_ms}ms"]
        for span in spans:
            name = span.get("name", "?")
            duration = span.get("duration_ms", 0)
            bar_len = max(1, int(duration / max(total_ms, 1) * 30))
            bar = "█" * bar_len + "░" * (30 - bar_len)
            lines.append(f"  ├── {name:<18} {bar}  {duration}ms")
        if w := safe_query(self, "#otel-trace", Static):
            w.update("\n".join(lines))
