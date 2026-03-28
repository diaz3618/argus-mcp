"""Progress indicators and spinners for the Argus CLI."""

from __future__ import annotations

__all__ = ["live_status", "progress_bar", "step_progress"]

from collections.abc import Generator, Sequence
from contextlib import contextmanager

from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from argus_cli.output import get_console
from argus_cli.theme import COLORS


@contextmanager
def live_status(message: str, *, console: Console | None = None) -> Generator[None, None, None]:
    """Show a spinner while a block of work executes.

    Usage::

        with live_status("Connecting..."):
            result = client.health()
    """
    con = console or get_console()
    with con.status(f"[bold {COLORS['highlight']}]{message}[/]", spinner="dots"):
        yield


def progress_bar(
    total: int,
    *,
    description: str = "Processing",
    console: Console | None = None,
) -> Progress:
    """Return a configured Rich Progress bar.

    Usage::

        with progress_bar(total=len(items)) as progress:
            task = progress.add_task("Working...", total=len(items))
            for item in items:
                process(item)
                progress.advance(task)
    """
    con = console or get_console()
    return Progress(
        SpinnerColumn(style=COLORS["highlight"]),
        TextColumn(f"[bold {COLORS['text']}]{description}[/]"),
        BarColumn(complete_style=COLORS["success"], finished_style=COLORS["success"]),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=con,
    )


def step_progress(
    steps: Sequence[tuple[str, object]],
    *,
    console: Console | None = None,
) -> list[object]:
    """Execute a sequence of named steps with spinner → ✓ feedback.

    Each step is a ``(label, callable)`` pair.  While a step runs the
    console shows a spinner; on completion it is replaced with a green
    checkmark.

    Usage::

        results = step_progress([
            ("Connecting to server", lambda: client.health()),
            ("Fetching backends",   lambda: client.backends()),
        ])
    """
    con = console or get_console()
    results: list[object] = []
    for label, fn in steps:
        with con.status(f"[bold {COLORS['highlight']}]{label}…[/]", spinner="dots"):
            result = fn() if callable(fn) else fn
            results.append(result)
        con.print(f"  [{COLORS['success']}]✓[/] {label}")
    return results
