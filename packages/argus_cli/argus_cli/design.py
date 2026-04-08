"""Shared iconography and status conventions for TUI and REPL.

Provides canonical status dots, phase displays, and transport badges
that both interfaces re-use so the visual language stays consistent.
"""

from __future__ import annotations

__all__ = [
    "PHASE_DISPLAY",
    "STATUS_DOT",
    "TRANSPORT_BADGE",
    "phase_markup",
    "status_dot",
    "transport_badge",
]

# Status dots
# Canonical mapping: status keyword → (icon, Rich color name).
STATUS_DOT: dict[str, tuple[str, str]] = {
    "healthy": ("●", "green"),
    "connected": ("●", "cyan"),
    "degraded": ("◑", "dark_orange"),
    "warning": ("◑", "yellow"),
    "disconnected": ("○", "red"),
    "error": ("✕", "red"),
    "idle": ("●", "dim"),
    "active": ("●", "green"),
    "live": ("●", "green"),
}

# Phase displays
# Lifecycle phase → (icon, Rich style name).
PHASE_DISPLAY: dict[str, tuple[str, str]] = {
    "pending": ("◌", "dim"),
    "initializing": ("⟳", "yellow"),
    "ready": ("●", "green"),
    "degraded": ("◑", "dark_orange"),
    "failed": ("✕", "red"),
    "shutting_down": ("◑", "cyan"),
}

# Transport badges
TRANSPORT_BADGE: dict[str, str] = {
    "stdio": "[cyan]stdio[/cyan]",
    "sse": "[yellow]SSE[/yellow]",
    "streamable-http": "[green]StreamableHTTP[/green]",
    "streamable_http": "[green]StreamableHTTP[/green]",
}


# Helpers


def status_dot(status: str, *, plain: bool = False) -> str:
    """Return a status-dot string.

    When *plain* is ``True`` the icon is returned without Rich markup;
    otherwise it is wrapped in ``[color]...[/color]`` tags.
    """
    icon, color = STATUS_DOT.get(status.lower(), ("?", "dim"))
    if plain:
        return icon
    return f"[{color}]{icon}[/{color}]"


def phase_markup(phase: str, *, plain: bool = False) -> str:
    """Return a Rich-markup string for a lifecycle *phase*."""
    icon, color = PHASE_DISPLAY.get(phase.lower(), ("?", "dim"))
    if plain:
        return icon
    return f"[{color}]{icon}[/{color}]"


def transport_badge(transport: str) -> str:
    """Return a Rich-markup badge for a *transport* type."""
    return TRANSPORT_BADGE.get(transport.lower(), transport)
