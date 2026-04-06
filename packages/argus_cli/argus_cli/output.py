"""Output formatter — 4 modes: rich, json, table, text.

Each command returns data as a dict/list, and the formatter
renders it according to the active output mode.
"""

from __future__ import annotations

__all__ = [
    "OutputOption",
    "OutputSpec",
    "apply_output_option",
    "get_console",
    "output",
    "print_error",
    "print_info",
    "print_success",
    "print_warning",
    "render_json_data",
    "render_yaml",
    "reset_console",
]

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal

import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from argus_cli._console import get_console, reset_console
from argus_cli.theme import status_markup

# ── Shared --output option for commands ────────────────────────────────

OutputOption = Annotated[
    str | None,
    typer.Option("--output", "-o", help="Output format: rich, json, table, text."),
]


def apply_output_option(fmt: str | None) -> None:
    """Apply --output override to the active config."""
    if fmt:
        from argus_cli.config import get_config

        get_config().output_format = fmt


# ── Format dispatch ────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class OutputSpec:
    """Display metadata for the output formatter."""

    title: str | None = None
    columns: list[str] | None = field(default=None)
    key_field: str | None = None


def output(
    data: Any,
    *,
    fmt: str = "rich",
    spec: OutputSpec | None = None,
    rich_fn: Callable[[Console, Any], None] | None = None,
) -> None:
    """Render data in the specified output format.

    Args:
        data: The data to render (dict, list, or string).
        fmt: Output format — rich, json, table, text.
        spec: Display metadata (title, columns, key_field).
        rich_fn: Optional callable(console, data) for custom rich rendering.
    """
    title = spec.title if spec else None
    columns = spec.columns if spec else None
    key_field = spec.key_field if spec else None

    if fmt == "json":
        _output_json(data)
    elif fmt == "table":
        _output_table(data, columns=columns)
    elif fmt == "text":
        if isinstance(data, list) and not data:
            typer.echo("No items found.")
            return
        _output_text(data, title=title)
    elif fmt == "rich":
        if isinstance(data, list) and not data:
            get_console().print("[muted]No items found.[/]")
            return
        _output_rich(data, title=title, columns=columns, key_field=key_field, rich_fn=rich_fn)
    else:
        raise typer.BadParameter(
            f"Unknown output format: '{fmt}'. Supported: rich, json, table, text."
        )


# ── JSON output ────────────────────────────────────────────────────────


def _output_json(data: Any) -> None:
    """Machine-readable JSON to stdout."""
    typer.echo(json.dumps(data, indent=2, default=str))


# ── Table output ───────────────────────────────────────────────────────


def _output_table(data: Any, *, columns: list[str] | None = None) -> None:
    """Formatted plain-text table via tabulate."""
    from tabulate import tabulate

    if isinstance(data, list) and data:
        cols = columns or list(data[0].keys())
        rows = [[str(row.get(c, "")) for c in cols] for row in data]
        typer.echo(tabulate(rows, headers=cols, tablefmt="simple"))
    elif isinstance(data, dict):
        rows = [[k, v] for k, v in data.items()]
        typer.echo(tabulate(rows, headers=["Key", "Value"], tablefmt="simple"))
    else:
        typer.echo(str(data))


# ── Text output (plain) ───────────────────────────────────────────────


def _output_text(data: Any, *, title: str | None = None) -> None:
    """Human-readable plain text without color or boxes."""
    if title:
        typer.echo(f"--- {title} ---")
    if isinstance(data, list) and data:
        cols = list(data[0].keys())
        widths = {c: max(len(c), *(len(str(row.get(c, ""))) for row in data)) for c in cols}
        header = "  ".join(c.ljust(widths[c]) for c in cols)
        typer.echo(header)
        typer.echo("  ".join("-" * widths[c] for c in cols))
        for row in data:
            line = "  ".join(str(row.get(c, "")).ljust(widths[c]) for c in cols)
            typer.echo(line)
    elif isinstance(data, dict):
        max_key_len = max(len(str(k)) for k in data) if data else 0
        for key, value in data.items():
            typer.echo(f"  {str(key).ljust(max_key_len)}  {value}")
    else:
        typer.echo(str(data))


# ── Rich output ────────────────────────────────────────────────────────


def _output_rich(
    data: Any,
    *,
    title: str | None = None,
    columns: list[str] | None = None,
    key_field: str | None = None,
    rich_fn: Callable[[Console, Any], None] | None = None,
) -> None:
    """Full Rich rendering with tables, panels, colors."""
    console = get_console()

    # Custom renderer takes priority
    if rich_fn is not None:
        rich_fn(console, data)
        return

    if isinstance(data, list) and data:
        _rich_table(console, data, title=title, columns=columns, key_field=key_field)
    elif isinstance(data, dict):
        _rich_panel(console, data, title=title)
    elif isinstance(data, str):
        if title:
            console.print(Panel(data, title=title, border_style="cyan"))
        else:
            console.print(data)
    else:
        console.print(data)


def _rich_table(
    console: Console,
    rows: list[dict[str, Any]],
    *,
    title: str | None = None,
    columns: list[str] | None = None,
    key_field: str | None = None,
) -> None:
    """Render a list of dicts as a Rich table."""
    cols = columns or list(rows[0].keys())
    table = Table(box=box.SIMPLE_HEAVY, title=title, show_edge=True)

    for col in cols:
        justify: Literal["left", "right"] = (
            "right" if col in ("port", "tools", "resources", "prompts", "latency_ms") else "left"
        )
        no_wrap = col in ("name", "type", "state", "status", "phase", "group")
        table.add_column(col.upper().replace("_", " "), justify=justify, no_wrap=no_wrap)

    for row in rows:
        cells = []
        for col in cols:
            value = row.get(col, "")
            if col == key_field or col in ("status", "state", "phase", "health"):
                cells.append(status_markup(str(value)))
            else:
                cells.append(str(value))
        table.add_row(*cells)

    console.print(table)


def _rich_panel(
    console: Console,
    data: dict[str, Any],
    *,
    title: str | None = None,
) -> None:
    """Render a dict as a Rich panel with key: value pairs."""
    lines: list[str] = []
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"[argus.key]{key}:[/]")
            for k, v in value.items():
                lines.append(f"  [argus.key]{k}:[/] [argus.value]{v}[/]")
        elif isinstance(value, list):
            lines.append(f"[argus.key]{key}:[/] {len(value)} items")
        else:
            lines.append(f"[argus.key]{key}:[/] [argus.value]{value}[/]")

    panel = Panel(
        "\n".join(lines),
        title=title or "Details",
        box=box.ROUNDED,
        border_style="cyan",
        expand=False,
    )
    console.print(panel)


# ── Helpers for commands ───────────────────────────────────────────────


def print_success(message: str) -> None:
    """Print a green success message."""
    get_console().print(f"  [success]✓[/] {message}")


def print_error(message: str) -> None:
    """Print a red error message."""
    get_console().print(f"  [error]✗[/] {message}", style="error")


def print_warning(message: str) -> None:
    """Print a yellow warning message."""
    get_console().print(f"  [warning]![/] {message}", style="warning")


def print_info(message: str) -> None:
    """Print a cyan info message."""
    get_console().print(f"  [info]i[/] {message}")


def render_yaml(content: str, *, title: str | None = None) -> None:
    """Render YAML content with syntax highlighting."""
    console = get_console()
    syntax = Syntax(content, "yaml", theme="monokai", line_numbers=True)
    if title:
        console.print(Panel(syntax, title=title, border_style="cyan"))
    else:
        console.print(syntax)


def render_json_data(data: Any, *, title: str | None = None) -> None:
    """Render JSON data with syntax highlighting."""
    console = get_console()
    formatted = json.dumps(data, indent=2, default=str)
    if title:
        console.print(
            Panel(Syntax(formatted, "json", theme="monokai"), title=title, border_style="cyan")
        )
    else:
        console.print_json(formatted)
