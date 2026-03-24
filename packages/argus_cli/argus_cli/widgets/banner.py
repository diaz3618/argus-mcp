"""ASCII art banner and welcome screen for the Argus CLI."""

from __future__ import annotations

__all__ = ["render_banner"]

from rich.text import Text

from argus_cli.output import get_console
from argus_cli.theme import COLORS

# Block-character art matching internal/art/banner.txt style
BANNER_ART = """\
 ▄▀█ █▀█ █▀▀ █ █ █▀   █▀▄▀█ █▀▀ █▀█
 █▀█ █▀▄ █▄█ █▄█ ▄█   █ ▀ █ █▄▄ █▀▀"""


def render_banner(*, version: str = "", server_url: str = "") -> None:
    """Print the Argus CLI banner to the console."""
    console = get_console()

    art = Text()
    for line in BANNER_ART.splitlines():
        art.append(line + "\n", style=f"bold {COLORS['highlight']}")

    console.print(art, end="")

    meta_parts: list[str] = []
    if version:
        meta_parts.append(f"[bold {COLORS['secondary']}]CLI v{version}[/]")
    if server_url:
        meta_parts.append(f"[dim]→ {server_url}[/]")
    if meta_parts:
        console.print("  " + "  ".join(meta_parts))

    console.print(f"[{COLORS['overlay']}]{'─' * 44}[/]")
