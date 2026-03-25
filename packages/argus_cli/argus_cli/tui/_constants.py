"""Shared UI constants for the TUI layer.

Centralises phase→icon/style mappings and transport badges that are
used across multiple widgets (backend_status, server_groups, etc.).

Re-exports canonical definitions from :mod:`argus_cli.design` so
existing imports continue to work.
"""

from __future__ import annotations

from argus_cli.design import PHASE_DISPLAY

# Backward-compatible aliases
PHASE_STYLE = PHASE_DISPLAY

# Phase → compact summary icon (for group views, badges, etc.)
PHASE_ICON: dict[str, str] = {phase: icon for phase, (icon, _) in PHASE_STYLE.items()}


def phase_icon(phase: str) -> str:
    """Return the icon character for a lifecycle phase."""
    return PHASE_ICON.get(phase.lower(), "?")
