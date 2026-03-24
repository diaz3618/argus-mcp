"""Standard table formatters for the Argus CLI."""

from __future__ import annotations

__all__ = ["auto_table", "simple_table", "status_table"]

from collections.abc import Sequence
from typing import Any

from rich import box
from rich.table import Table

from argus_cli.theme import COLORS, STATUS_STYLES, status_markup


def simple_table(
    title: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[Any]],
    *,
    show_lines: bool = False,
) -> Table:
    """Create a plain table with no special styling."""
    table = Table(
        title=title,
        show_lines=show_lines,
        box=box.SIMPLE_HEAVY,
        border_style=COLORS["overlay"],
    )
    for col in columns:
        table.add_column(col.replace("_", " ").title(), style=COLORS["text"])
    for row in rows:
        table.add_row(*(str(cell) for cell in row))
    return table


def status_table(
    title: str,
    columns: Sequence[str],
    rows: Sequence[dict[str, Any]],
    *,
    key_field: str = "status",
) -> Table:
    """Create a table where one column is styled by status value."""
    table = Table(title=title, box=box.SIMPLE_HEAVY, border_style=COLORS["overlay"])
    for col in columns:
        table.add_column(col.replace("_", " ").title(), style=COLORS["text"])
    for row in rows:
        cells: list[str] = []
        for col in columns:
            val = str(row.get(col, ""))
            if col == key_field and val.lower() in STATUS_STYLES:
                val = status_markup(val)
            cells.append(val)
        table.add_row(*cells)
    return table


def auto_table(
    title: str,
    data: Sequence[dict[str, Any]],
    *,
    columns: Sequence[str] | None = None,
    key_field: str | None = None,
) -> Table:
    """Build a table automatically from a list of dicts.

    If *columns* is not given, uses the keys from the first row.
    If *key_field* is given, applies status styling to that column.
    """
    if not data:
        table = Table(title=title, box=box.SIMPLE_HEAVY, border_style=COLORS["overlay"])
        table.add_column("(empty)")
        return table

    cols = list(columns) if columns else list(data[0].keys())

    if key_field:
        return status_table(title, cols, list(data), key_field=key_field)
    return simple_table(
        title,
        cols,
        [[row.get(c, "") for c in cols] for row in data],
    )
