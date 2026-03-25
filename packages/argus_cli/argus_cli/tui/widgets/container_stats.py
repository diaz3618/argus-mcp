"""Container stats panel — reactive CPU/memory bars and time-series charts."""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any

from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

from argus_cli.tui.widgets.percentage_bar import PercentageBar

if TYPE_CHECKING:
    from textual.app import ComposeResult


# Maximum data points to keep in time-series history
_MAX_HISTORY = 120


class ContainerStatsPanel(Widget):
    """Live resource usage panel for a single container.

    Shows reactive CPU and memory percentage bars that update
    in real-time from argusd push events, plus a scrolling
    time-series buffer for charting.
    """

    DEFAULT_CSS = """
    ContainerStatsPanel {
        height: auto;
        min-height: 8;
    }
    ContainerStatsPanel #stats-header {
        height: 1;
        padding: 0 1;
    }
    ContainerStatsPanel .stats-bars {
        height: auto;
        padding: 0 1;
    }
    ContainerStatsPanel .stats-detail {
        height: auto;
        padding: 0 1;
    }
    """

    cpu_percent: reactive[float] = reactive(0.0)
    mem_percent: reactive[float] = reactive(0.0)
    container_name: reactive[str] = reactive("")

    def __init__(self, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self._cpu_history: deque[float] = deque(maxlen=_MAX_HISTORY)
        self._mem_history: deque[float] = deque(maxlen=_MAX_HISTORY)
        self._net_rx: str = "—"
        self._net_tx: str = "—"
        self._mem_usage: str = "—"
        self._mem_limit: str = "—"

    def compose(self) -> ComposeResult:
        yield Static("[b]Container Stats[/b]", id="stats-header")
        with Vertical(classes="stats-bars"):
            with Horizontal():
                yield Static("CPU ", classes="stats-label")
                yield PercentageBar(id="stats-cpu-bar")
            with Horizontal():
                yield Static("MEM ", classes="stats-label")
                yield PercentageBar(id="stats-mem-bar")
        yield Static("", id="stats-detail-text", classes="stats-detail")

    def update_stats(self, stats: dict[str, Any]) -> None:
        """Push a new stats snapshot from the daemon stream."""
        cpu = float(stats.get("cpu_percent", 0.0))
        mem = float(stats.get("mem_percent", 0.0))
        self.cpu_percent = cpu
        self.mem_percent = mem
        self._cpu_history.append(cpu)
        self._mem_history.append(mem)

        # Update detail text
        self._mem_usage = stats.get("mem_usage", "—")
        self._mem_limit = stats.get("mem_limit", "—")
        self._net_rx = stats.get("net_rx", "—")
        self._net_tx = stats.get("net_tx", "—")
        self._update_detail()

    def watch_cpu_percent(self, value: float) -> None:
        try:
            bar = self.query_one("#stats-cpu-bar", PercentageBar)
            bar.value = value
            bar.label_text = f"{value:.1f}%"
        except Exception:
            pass

    def watch_mem_percent(self, value: float) -> None:
        try:
            bar = self.query_one("#stats-mem-bar", PercentageBar)
            bar.value = value
            bar.label_text = f"{value:.1f}%"
        except Exception:
            pass

    def _update_detail(self) -> None:
        parts = []
        if self._mem_usage != "—":
            parts.append(f"Mem: {self._mem_usage}/{self._mem_limit}")
        if self._net_rx != "—":
            parts.append(f"Net ↓{self._net_rx} ↑{self._net_tx}")
        try:
            detail = self.query_one("#stats-detail-text", Static)
            detail.update("  │  ".join(parts) if parts else "")
        except Exception:
            pass

    @property
    def cpu_history(self) -> list[float]:
        """CPU usage history for charting."""
        return list(self._cpu_history)

    @property
    def mem_history(self) -> list[float]:
        """Memory usage history for charting."""
        return list(self._mem_history)
