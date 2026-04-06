"""Persistent TUI settings (theme preference, enabled themes, etc.)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

ALL_THEMES: List[str] = [
    "textual-dark",
    "textual-light",
    "nord",
    "gruvbox",
    "catppuccin-mocha",
    "textual-ansi",
    "dracula",
    "tokyo-night",
    "monokai",
    "flexoki",
    "catppuccin-latte",
    "catppuccin-frappe",
    "catppuccin-macchiato",
    "solarized-light",
    "solarized-dark",
    "rose-pine",
    "rose-pine-moon",
    "rose-pine-dawn",
    "atom-one-dark",
    "atom-one-light",
]

# Curated default subset — sensible for typical terminal use
DEFAULT_ENABLED: List[str] = [
    "textual-dark",
    "textual-light",
    "nord",
    "gruvbox",
    "dracula",
    "tokyo-night",
    "monokai",
    "catppuccin-mocha",
    "solarized-dark",
    "solarized-light",
    "rose-pine",
    "atom-one-dark",
]

_SETTINGS_DIR = os.path.realpath(
    os.path.join(
        os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
        "argus-mcp",
    )
)
_SETTINGS_FILE = os.path.realpath(os.path.join(_SETTINGS_DIR, "settings.json"))


def _default_settings() -> Dict[str, Any]:
    return {
        "theme": "textual-dark",
        "enabled_themes": DEFAULT_ENABLED[:],
    }


def load_settings() -> Dict[str, Any]:
    """Load settings from disk, returning defaults if missing/corrupt."""
    defaults = _default_settings()
    try:
        with open(_SETTINGS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        # Merge with defaults so new keys are always present
        for key, val in defaults.items():
            data.setdefault(key, val)
        return data
    except FileNotFoundError:
        return defaults
    except (json.JSONDecodeError, OSError):
        logger.debug("Could not load settings, using defaults", exc_info=True)
        return defaults


def save_settings(settings: Dict[str, Any]) -> None:
    """Persist settings to disk."""
    try:
        os.makedirs(_SETTINGS_DIR, exist_ok=True)
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as fh:
            json.dump(settings, fh, indent=2)
    except OSError:
        logger.debug("Could not save settings", exc_info=True)
