"""Container overview table — lists Argus-managed containers with status."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import DataTable, Static

if TYPE_CHECKING:
    from textual.app import ComposeResult

_COLUMNS = ("Name", "ID", "Status", "Image", "CPU %", "Mem %", "Uptime")


class ContainerTable(Widget):
    """DataTable showing all Argus-managed containers.

    Call :meth:`refresh_containers` with a list of container dicts
    from the daemon client to update the table.
    """

    DEFAULT_CSS = """
    ContainerTable {
        height: 1fr;
    }
    ContainerTable DataTable {
        height: 1fr;
    }
    """

    container_count: reactive[int] = reactive(0)

    def compose(self) -> ComposeResult:
        yield DataTable(id="container-dt", cursor_type="row")

    def on_mount(self) -> None:
        table = self.query_one("#container-dt", DataTable)
        for col in _COLUMNS:
            table.add_column(col, key=col.lower().replace(" ", "_"))

    def refresh_containers(self, containers: list[dict[str, Any]]) -> None:
        """Rebuild the table from daemon container data."""
        table = self.query_one("#container-dt", DataTable)
        table.clear()
        for c in containers:
            short_id = str(c.get("id", ""))[:12]
            name = c.get("name", c.get("names", short_id))
            if isinstance(name, list):
                name = name[0] if name else short_id
            status = c.get("status", "unknown")
            image = c.get("image", "")
            cpu = c.get("cpu_percent", "—")
            mem = c.get("mem_percent", "—")
            uptime = c.get("uptime", c.get("running_for", "—"))
            if isinstance(cpu, float | int):
                cpu = f"{cpu:.1f}"
            if isinstance(mem, float | int):
                mem = f"{mem:.1f}"
            table.add_row(
                str(name),
                short_id,
                str(status),
                str(image),
                str(cpu),
                str(mem),
                str(uptime),
                key=str(c.get("id", short_id)),
            )
        self.container_count = len(containers)

    def update_stats(self, container_id: str, stats: dict[str, Any]) -> None:
        """Update CPU/mem columns for a single container from a stats event."""
        table = self.query_one("#container-dt", DataTable)
        short_id = container_id[:12]
        try:
            cpu = stats.get("cpu_percent", "—")
            mem = stats.get("mem_percent", stats.get("mem_mb", "—"))
            if isinstance(cpu, float | int):
                cpu = f"{cpu:.1f}"
            if isinstance(mem, float | int):
                mem = f"{mem:.1f}"
            table.update_cell(short_id, "cpu_%", str(cpu))
            table.update_cell(short_id, "mem_%", str(mem))
        except Exception:
            pass


class ContainerStatusBar(Static):
    """One-line status bar showing container counts."""

    def update_counts(
        self,
        total: int = 0,
        running: int = 0,
        stopped: int = 0,
    ) -> None:
        parts = [f"[b]{total}[/b] containers"]
        if running:
            parts.append(f"[green]{running} running[/green]")
        if stopped:
            parts.append(f"[red]{stopped} stopped[/red]")
        self.update("  │  ".join(parts))
