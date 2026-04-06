"""Prompt and toolbar rendering for the REPL."""

from __future__ import annotations

__all__ = ["make_prompt", "make_toolbar"]

from collections.abc import Callable

from prompt_toolkit.formatted_text import HTML

from argus_cli.repl.state import ReplState
from argus_cli.theme import COLORS, _ensure_loaded

# ── ANSI color helpers ──────────────────────────────────────────────────
# prompt_toolkit HTML uses ANSI color names or hex.  We map from the
# active YAML palette's semantic colors to the closest ANSI keyword so
# that the prompt and toolbar respect the current theme.

_ANSI_FALLBACKS = {
    "success": "ansigreen",
    "warning": "ansiyellow",
    "info": "ansicyan",
    "error": "ansired",
}


def _ansi(role: str) -> str:
    """Return an ANSI color for *role* from the active palette, with fallback."""
    _ensure_loaded()
    color = COLORS.get(role)
    if color and color.startswith("#"):
        return color  # prompt_toolkit accepts hex
    return _ANSI_FALLBACKS.get(role, "ansiwhite")


def make_prompt(state: ReplState) -> HTML:
    """Build the prompt string with connection-status color."""
    if state.connection.is_connected:
        if state.connection.server_status == "healthy":
            color = _ansi("success")
        elif state.connection.server_status in ("degraded", "warning"):
            color = _ansi("warning")
        else:
            color = _ansi("info")
    else:
        color = _ansi("error")

    prefix = "argus"
    if state.session.scoped_backend:
        prefix = f"argus:{state.session.scoped_backend}"

    return HTML(f"<style color='{color}'>{prefix} \u25b8</style> ")


def make_toolbar(state: ReplState) -> Callable[[], HTML]:
    """Return a bottom toolkit toolbar callback with live status."""

    def toolbar() -> HTML:
        conn = state.connection
        if conn.is_connected:
            status_color = _ansi("success") if conn.server_status == "healthy" else _ansi("warning")
            conn_text = f"<b style='color: {status_color}'>\u25cf</b> {state.config.server_url}"
        else:
            conn_text = f"<b style='color: {_ansi('error')}'>\u25cf</b> disconnected"

        parts = [conn_text]

        if conn.backend_count > 0:
            parts.append(f"Backends: {conn.healthy_count}/{conn.backend_count} healthy")

        if conn.last_event_age:
            parts.append(f"Events: {conn.last_event_age}")

        if state.session.scoped_backend:
            parts.append(f"Scope: <b>{state.session.scoped_backend}</b>")

        return HTML(" | ".join(parts))

    return toolbar
