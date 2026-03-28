"""Console singleton — shared by theme.py and output.py to avoid circular imports.

The module-global singleton pattern is intentional: Rich Console configuration
(theme, no_color) must be consistent across all output paths.  ``reset_console()``
exists to support tests that need to reconfigure the console between runs.
"""

from __future__ import annotations

__all__ = ["get_console", "reset_console"]

from rich.console import Console

_console: Console | None = None


def get_console(no_color: bool | None = None) -> Console:
    """Get or create the Rich console singleton.

    Args:
        no_color: Override color setting. When ``None``, reads from
                  the active CLI config.
    """
    global _console
    if _console is None:
        from argus_cli.theme import ARGUS_THEME, _ensure_loaded

        _ensure_loaded()
        if no_color is None:
            from argus_cli.config import get_config

            try:
                no_color = get_config().no_color
            except RuntimeError:
                no_color = False
        _console = Console(
            theme=ARGUS_THEME,
            no_color=no_color,
            stderr=False,
        )
    return _console


def reset_console() -> None:
    """Reset console singleton so the next call picks up a new theme."""
    global _console
    _console = None
