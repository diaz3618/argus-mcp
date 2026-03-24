"""Shared UI constants for the TUI layer.

Centralises phase→icon/style mappings and transport badges that are
used across multiple widgets (backend_status, server_groups, etc.).
"""

from __future__ import annotations

# Phase → (icon, Rich style name)
PHASE_STYLE: dict[str, tuple[str, str]] = {
    "pending": ("◌", "dim"),
    "initializing": ("⟳", "yellow"),
    "ready": ("●", "green"),
    "degraded": ("◑", "dark_orange"),
    "failed": ("✕", "red"),
    "shutting_down": ("◑", "cyan"),
}

# Phase → compact summary icon (for group views, badges, etc.)
PHASE_ICON: dict[str, str] = {phase: icon for phase, (icon, _) in PHASE_STYLE.items()}

# Transport type → Rich-markup display badge
TRANSPORT_BADGE: dict[str, str] = {
    "stdio": "[cyan]stdio[/cyan]",
    "sse": "[yellow]SSE[/yellow]",
    "streamable-http": "[green]StreamableHTTP[/green]",
    "streamable_http": "[green]StreamableHTTP[/green]",
}


def phase_icon(phase: str) -> str:
    """Return the icon character for a lifecycle phase."""
    return PHASE_ICON.get(phase.lower(), "?")
