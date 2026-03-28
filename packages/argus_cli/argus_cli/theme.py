"""Theme and color system — loads palettes from YAML files in themes/.

Each .yaml file in argus_cli/themes/ defines a palette with a ``colors`` mapping.
Users can also drop custom theme files into ~/.config/argus-mcp/themes/.
"""

from __future__ import annotations

__all__ = [
    "ARGUS_THEME",
    "COLORS",
    "STATUS_STYLES",
    "THEME_NAMES",
    "get_active_theme",
    "refresh_themes",
    "set_active_theme",
    "status_markup",
    "status_style",
]

from pathlib import Path

from rich.style import Style
from rich.theme import Theme

# ── Required color keys every theme file must provide ───────────────────

_REQUIRED_KEYS = frozenset(
    {
        "success",
        "error",
        "warning",
        "highlight",
        "info",
        "accent",
        "secondary",
        "surface",
        "text",
        "subtext",
        "overlay",
    }
)

# ── Theme loading ───────────────────────────────────────────────────────

_BUILTIN_DIR = Path(__file__).parent / "themes"
_USER_DIR = Path.home() / ".config" / "argus-mcp" / "themes"


def _load_theme_file(path: Path) -> dict[str, str] | None:
    """Parse a single theme YAML file. Returns the colors dict or None."""
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        colors = data.get("colors")
        if not isinstance(colors, dict):
            return None
        if not _REQUIRED_KEYS.issubset(colors.keys()):
            return None
        return {k: str(v) for k, v in colors.items()}
    except (OSError, ValueError):
        return None


def _discover_themes() -> dict[str, dict[str, str]]:
    """Scan built-in and user theme directories. User themes override built-in."""
    palettes: dict[str, dict[str, str]] = {}
    for directory in (_BUILTIN_DIR, _USER_DIR):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.yaml")):
            colors = _load_theme_file(path)
            if colors is not None:
                palettes[path.stem] = colors
    return palettes


# Lazy initialization — populated on first access via _ensure_loaded()
PALETTES: dict[str, dict[str, str]] = {}
THEME_NAMES: list[str] = []
_loaded: bool = False


def _ensure_loaded() -> None:
    """Load theme palettes on first access (lazy)."""
    global _loaded, ARGUS_THEME
    if _loaded:
        return
    _loaded = True
    PALETTES.update(_discover_themes())
    THEME_NAMES[:] = sorted(PALETTES.keys())
    COLORS.update(PALETTES.get(_DEFAULT_THEME, {}))
    STATUS_STYLES.update(_build_status_styles(COLORS))
    ARGUS_THEME = _build_rich_theme(COLORS)


def refresh_themes() -> None:
    """Re-scan theme directories (e.g. after adding a file at runtime)."""
    PALETTES.clear()
    PALETTES.update(_discover_themes())
    THEME_NAMES[:] = sorted(PALETTES.keys())


# ── Active theme state ──────────────────────────────────────────────────

_DEFAULT_THEME = "catppuccin-mocha"
_active_theme: str = _DEFAULT_THEME
COLORS: dict[str, str] = {}


def set_active_theme(name: str) -> bool:
    """Switch the active theme. Returns True on success.

    Side effects:
        - Updates module-level ``COLORS`` and ``STATUS_STYLES``.
        - Replaces ``ARGUS_THEME`` with a new ``Theme`` instance.
        - Calls ``reset_console()`` so the Rich console picks up the new theme.
    """
    global _active_theme, STATUS_STYLES, ARGUS_THEME
    _ensure_loaded()
    if name not in PALETTES:
        return False
    _active_theme = name
    COLORS.clear()
    COLORS.update(PALETTES[name])
    STATUS_STYLES = _build_status_styles(COLORS)
    ARGUS_THEME = _build_rich_theme(COLORS)
    # Reset the console singleton so it picks up the new theme
    from argus_cli._console import reset_console

    reset_console()
    return True


def get_active_theme() -> str:
    """Return the current theme name."""
    return _active_theme


# ── Status colors (semantic) ───────────────────────────────────────────

# Canonical mapping: status keyword → Rich theme tag (e.g. "success", "warning")
# Used by both _build_status_styles() and status_markup() to avoid duplication.
_STATUS_TAG_MAP: dict[str, str] = {
    "healthy": "success",
    "connected": "success",
    "running": "success",
    "degraded": "warning",
    "warning": "warning",
    "pending": "warning",
    "unhealthy": "error",
    "disconnected": "error",
    "error": "error",
    "stopped": "error",
    "enabled": "success",
    "disabled": "error",
    "true": "success",
    "false": "error",
    "unknown": "overlay",
    "info": "info",
}

# Bold statuses for _build_status_styles
_BOLD_STATUSES = frozenset({"healthy", "degraded", "unhealthy", "error"})
_ITALIC_STATUSES = frozenset({"unknown"})


def _build_status_styles(colors: dict[str, str]) -> dict[str, Style]:
    styles: dict[str, Style] = {}
    for status, tag in _STATUS_TAG_MAP.items():
        color = colors.get(tag)
        if color is None:
            continue
        styles[status] = Style(
            color=color,
            bold=status in _BOLD_STATUSES,
            italic=status in _ITALIC_STATUSES,
        )
    return styles


STATUS_STYLES: dict[str, Style] = {}


# ── Rich Theme ─────────────────────────────────────────────────────────


def _build_rich_theme(colors: dict[str, str]) -> Theme:
    if not colors:
        return Theme({})
    return Theme(
        {
            "info": colors["info"],
            "warning": colors["warning"],
            "error": colors["error"],
            "success": colors["success"],
            "highlight": colors["highlight"],
            "muted": colors["subtext"],
            "argus.header": f"bold {colors['info']}",
            "argus.key": colors["highlight"],
            "argus.value": colors["text"],
            "argus.url": f"underline {colors['info']}",
        }
    )


ARGUS_THEME: Theme = Theme({})


def status_style(status: str) -> Style:
    """Get the Rich style for a status string."""
    _ensure_loaded()
    return STATUS_STYLES.get(status.lower(), STATUS_STYLES.get("unknown", Style()))


def status_markup(status: str) -> str:
    """Wrap a status string in Rich markup with appropriate color."""
    tag = _STATUS_TAG_MAP.get(str(status).lower(), "dim")
    return f"[{tag}]{status}[/{tag}]"


# ── Textual ↔ YAML theme bridging ──────────────────────────────────────

# Maps Textual built-in theme names to the closest YAML palette.
# Themes not listed here fall back to catppuccin-mocha.
TEXTUAL_TO_YAML: dict[str, str] = {
    "textual-dark": "catppuccin-mocha",
    "textual-light": "catppuccin-latte",
    "catppuccin-mocha": "catppuccin-mocha",
    "catppuccin-latte": "catppuccin-latte",
    "catppuccin-frappe": "catppuccin-frappe",
    "catppuccin-macchiato": "catppuccin-macchiato",
    "dracula": "dracula",
    "gruvbox": "gruvbox",
    "monokai": "monokai",
    "nord": "nord",
    "solarized-light": "solarized-light",
    "solarized-dark": "solarized-dark",
    "tokyo-night": "tokyo-night",
}


def sync_with_textual_theme(textual_theme: str) -> str:
    """Activate the YAML palette closest to *textual_theme*.

    Returns the YAML palette name that was applied.
    """
    _ensure_loaded()
    yaml_name = TEXTUAL_TO_YAML.get(textual_theme, _DEFAULT_THEME)
    if yaml_name not in PALETTES:
        yaml_name = _DEFAULT_THEME
    set_active_theme(yaml_name)
    return yaml_name
