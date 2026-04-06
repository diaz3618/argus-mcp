"""Terminal chart widgets using textual-plotext.

Provides reusable chart components for the Argus TUI:
- LatencyChart: time-series line chart for request latency
- FrequencyChart: bar chart for tool invocation counts
- UptimeChart: bar chart for connection uptime per backend
- HealthTrendChart: multi-line trend chart for backend health
"""

from __future__ import annotations

import logging
from collections import deque
from typing import TYPE_CHECKING, Any

from textual.containers import Horizontal
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult

logger = logging.getLogger(__name__)

try:
    from textual_plotext import PlotextPlot

    _HAS_PLOTEXT = True
except ImportError:  # pragma: no cover
    _HAS_PLOTEXT = False

# Maximum data points to keep in time-series charts
_MAX_POINTS = 60


class _BasePlotWidget(Widget):
    """Base class for Argus chart widgets with zoom controls."""

    DEFAULT_CSS = """
    _BasePlotWidget {
        height: 1fr;
        min-height: 10;
    }
    """

    class ZoomChanged(Message):
        """Posted when zoom level changes."""

        def __init__(self, zoom: int) -> None:
            self.zoom = zoom
            super().__init__()

    def __init__(
        self,
        title: str = "",
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._title = title
        self._zoom: int = 0  # 0 = default, positive = zoom in, negative = zoom out
        self._plot_widget: PlotextPlot | None = None

    def compose(self) -> ComposeResult:
        if not _HAS_PLOTEXT:
            yield Static("[dim]Install textual-plotext for charts[/dim]")
            return
        plot = PlotextPlot(id=f"{self.id or 'chart'}-plot")
        self._plot_widget = plot
        yield plot
        with Horizontal(classes="chart-controls"):
            yield Button("+", id=f"{self.id or 'chart'}-zoom-in", classes="chart-zoom-btn")
            yield Button("-", id=f"{self.id or 'chart'}-zoom-out", classes="chart-zoom-btn")
            yield Button("⟲", id=f"{self.id or 'chart'}-zoom-reset", classes="chart-zoom-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id or ""
        if btn_id.endswith("-zoom-in"):
            self._zoom = min(self._zoom + 1, 5)
        elif btn_id.endswith("-zoom-out"):
            self._zoom = max(self._zoom - 1, -3)
        elif btn_id.endswith("-zoom-reset"):
            self._zoom = 0
        else:
            return
        self.post_message(self.ZoomChanged(self._zoom))
        self.redraw()

    def _visible_window(self, total: int) -> int:
        """Return how many data points to show based on zoom level."""
        base = total
        if self._zoom > 0:
            base = max(5, total // (2**self._zoom))
        elif self._zoom < 0:
            base = min(total * (2 ** abs(self._zoom)), _MAX_POINTS * 4)
        return max(5, int(base))

    def redraw(self) -> None:
        """Subclasses implement this to re-render the plot."""
        if self._plot_widget is not None:
            self._plot_widget.refresh()


class LatencyChart(_BasePlotWidget):
    """Time-series line chart for request latency over time."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(title="Latency Over Time", **kwargs)
        self._timestamps: deque[str] = deque(maxlen=_MAX_POINTS)
        self._latencies: deque[float] = deque(maxlen=_MAX_POINTS)

    def add_point(self, timestamp: str, latency_ms: float) -> None:
        """Append a latency data point and redraw."""
        self._timestamps.append(timestamp)
        self._latencies.append(latency_ms)
        self.redraw()

    def set_data(self, timestamps: list[str], latencies: list[float]) -> None:
        """Replace all data and redraw."""
        self._timestamps.clear()
        self._latencies.clear()
        self._timestamps.extend(timestamps[-_MAX_POINTS:])
        self._latencies.extend(latencies[-_MAX_POINTS:])
        self.redraw()

    def on_mount(self) -> None:
        self.redraw()

    def redraw(self) -> None:
        if self._plot_widget is None or not self._latencies:
            return
        plt = self._plot_widget.plt
        plt.clear_data()
        plt.clear_figure()

        window = self._visible_window(len(self._latencies))
        lats = list(self._latencies)[-window:]
        labels = list(self._timestamps)[-window:]

        plt.plot(lats, marker="braille")
        plt.title(self._title)
        plt.ylabel("ms")
        plt.xlabel("time")

        # Show sparse x-tick labels to avoid crowding
        step = max(1, len(labels) // 8)
        xticks = list(range(0, len(labels), step))
        xlabels = [labels[i] for i in xticks]
        plt.xticks(xticks, xlabels)

        self._plot_widget.refresh()


class FrequencyChart(_BasePlotWidget):
    """Bar chart for tool invocation frequency."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(title="Tool Invocation Frequency", **kwargs)
        self._tool_names: list[str] = []
        self._counts: list[int] = []

    def set_data(self, tool_names: list[str], counts: list[int]) -> None:
        """Replace all data and redraw."""
        self._tool_names = list(tool_names)
        self._counts = list(counts)
        self.redraw()

    def on_mount(self) -> None:
        self.redraw()

    def redraw(self) -> None:
        if self._plot_widget is None or not self._counts:
            return
        plt = self._plot_widget.plt
        plt.clear_data()
        plt.clear_figure()

        window = self._visible_window(len(self._counts))
        # Sort by count descending and take top N
        pairs = sorted(zip(self._counts, self._tool_names, strict=False), reverse=True)[:window]
        if not pairs:
            return
        counts, names = zip(*pairs, strict=False)

        plt.bar(list(names), list(counts))
        plt.title(self._title)
        plt.ylabel("calls")

        self._plot_widget.refresh()


class UptimeChart(_BasePlotWidget):
    """Bar chart for backend connection uptime."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(title="Connection Uptime", **kwargs)
        self._backend_names: list[str] = []
        self._uptime_pct: list[float] = []

    def set_data(self, backend_names: list[str], uptime_pct: list[float]) -> None:
        """Replace all data and redraw."""
        self._backend_names = list(backend_names)
        self._uptime_pct = list(uptime_pct)
        self.redraw()

    def on_mount(self) -> None:
        self.redraw()

    def redraw(self) -> None:
        if self._plot_widget is None or not self._uptime_pct:
            return
        plt = self._plot_widget.plt
        plt.clear_data()
        plt.clear_figure()

        plt.bar(self._backend_names, self._uptime_pct)
        plt.title(self._title)
        plt.ylabel("uptime %")
        plt.ylim(0, 100)

        self._plot_widget.refresh()


class HealthTrendChart(_BasePlotWidget):
    """Multi-line trend chart showing backend health over time."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(title="Backend Health Trends", **kwargs)
        # backend_name -> deque of (timestamp, latency) pairs
        self._series: dict[str, deque[float]] = {}
        self._timestamps: deque[str] = deque(maxlen=_MAX_POINTS)

    def add_snapshot(self, timestamp: str, backends: dict[str, float]) -> None:
        """Add a time-point with latency values for each backend."""
        self._timestamps.append(timestamp)
        for name, latency in backends.items():
            if name not in self._series:
                self._series[name] = deque(maxlen=_MAX_POINTS)
            self._series[name].append(latency)
        self.redraw()

    def set_data(
        self,
        timestamps: list[str],
        series: dict[str, list[float]],
    ) -> None:
        """Replace all data and redraw."""
        self._timestamps.clear()
        self._timestamps.extend(timestamps[-_MAX_POINTS:])
        self._series.clear()
        for name, values in series.items():
            self._series[name] = deque(values[-_MAX_POINTS:], maxlen=_MAX_POINTS)
        self.redraw()

    def on_mount(self) -> None:
        self.redraw()

    def redraw(self) -> None:
        if self._plot_widget is None or not self._series:
            return
        plt = self._plot_widget.plt
        plt.clear_data()
        plt.clear_figure()

        window = self._visible_window(len(self._timestamps))
        timestamps = list(self._timestamps)[-window:]

        for name, values in self._series.items():
            data = list(values)[-window:]
            # Pad shorter series with 0
            if len(data) < len(timestamps):
                data = [0.0] * (len(timestamps) - len(data)) + data
            plt.plot(data, label=name, marker="braille")

        plt.title(self._title)
        plt.ylabel("ms")
        plt.xlabel("time")

        # Sparse x-tick labels
        step = max(1, len(timestamps) // 8)
        xticks = list(range(0, len(timestamps), step))
        xlabels = [timestamps[i] for i in xticks]
        plt.xticks(xticks, xlabels)

        self._plot_widget.refresh()
