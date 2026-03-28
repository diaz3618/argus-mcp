"""Composable Rich widgets for the Argus REPL.

This package provides reusable UI building blocks for the interactive REPL
session (banner, panels, tables, spinners).  It is intentionally separate from
``argus_cli.output``, which handles *command* output formatting (json / table /
text / rich modes).  The two layers serve different concerns:

- **widgets** — Rich renderables composed inside the REPL (banners, detail
  panels, live spinners).  Imported by ``repl/handlers.py`` and future REPL
  extensions.
- **output** — Uniform four-mode formatter consumed by every Typer command
  callback.  Not used inside the REPL UI itself.
"""

from argus_cli.widgets.banner import render_banner
from argus_cli.widgets.spinners import live_status, progress_bar, step_progress

__all__ = [
    "live_status",
    "progress_bar",
    "render_banner",
    "step_progress",
]
