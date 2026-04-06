"""Pod table and status bar widgets for the Kubernetes screen."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import DataTable, Static

if TYPE_CHECKING:
    pass


class PodStatusBar(Static):
    """Single-line summary of pod counts."""

    def update_counts(self, *, total: int, running: int, pending: int, failed: int) -> None:
        markup = (
            f"[bold]{total}[/] pods  |  "
            f"[green]{running}[/] running  |  "
            f"[yellow]{pending}[/] pending  |  "
            f"[red]{failed}[/] failed"
        )
        self.update(markup)


class PodTable(DataTable):
    """DataTable pre-configured with pod columns."""

    _COLUMNS = ("Name", "Namespace", "Status", "Node", "IP", "Restarts", "Age")

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.zebra_stripes = True
        for col in self._COLUMNS:
            self.add_column(col, key=col.lower())

    def refresh_pods(self, pods: list[dict[str, Any]]) -> None:
        """Replace all rows with fresh data."""
        self.clear()
        for p in pods:
            self.add_row(
                p.get("name", ""),
                p.get("namespace", ""),
                p.get("status", ""),
                p.get("node", ""),
                p.get("ip", p.get("pod_ip", "")),
                str(p.get("restarts", 0)),
                p.get("age", ""),
                key=f"{p.get('namespace', '')}/{p.get('name', '')}",
            )
