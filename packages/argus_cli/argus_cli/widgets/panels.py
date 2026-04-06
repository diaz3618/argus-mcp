"""Info panels and detail views for the Argus CLI."""

from __future__ import annotations

__all__ = ["detail_panel", "info_panel", "key_value_panel"]

from collections.abc import Sequence
from typing import Any

from rich.panel import Panel
from rich.text import Text

from argus_cli.theme import COLORS


def info_panel(title: str, content: str, *, subtitle: str | None = None) -> Panel:
    """Render a styled informational panel."""
    return Panel(
        content,
        title=f"[bold {COLORS['highlight']}]{title}[/]",
        subtitle=subtitle,
        border_style=COLORS["overlay"],
        padding=(1, 2),
    )


def key_value_panel(
    title: str,
    items: dict[str, Any] | Sequence[tuple[str, Any]],
    *,
    subtitle: str | None = None,
) -> Panel:
    """Render a panel of key-value pairs with aligned keys."""
    pairs = list(items.items()) if isinstance(items, dict) else list(items)
    if not pairs:
        return info_panel(title, "(empty)", subtitle=subtitle)

    max_key = max(len(str(k)) for k, _ in pairs)
    lines = Text()
    for i, (key, value) in enumerate(pairs):
        lines.append(f"{key!s:<{max_key}}", style=f"bold {COLORS['accent']}")
        lines.append("  ")
        lines.append(str(value), style=COLORS["text"])
        if i < len(pairs) - 1:
            lines.append("\n")

    return Panel(
        lines,
        title=f"[bold {COLORS['highlight']}]{title}[/]",
        subtitle=subtitle,
        border_style=COLORS["overlay"],
        padding=(1, 2),
    )


def detail_panel(
    title: str,
    header: dict[str, Any],
    sections: dict[str, str] | None = None,
) -> Panel:
    """Render a multi-section detail panel with a key-value header."""
    parts: list[str] = []

    # Header key-values
    if header:
        max_key = max(len(str(k)) for k in header)
        for key, value in header.items():
            parts.append(f"[bold {COLORS['accent']}]{key!s:<{max_key}}[/]  {value}")
    if sections:
        for section_title, body in sections.items():
            parts.append("")
            parts.append(f"[bold {COLORS['warning']}]{section_title}[/]")
            parts.append(body)

    return Panel(
        "\n".join(parts),
        title=f"[bold {COLORS['highlight']}]{title}[/]",
        border_style=COLORS["overlay"],
        padding=(1, 2),
    )
