"""Version badge widget — drift indicator for TUI.

Shows a colored badge per tool indicating version drift severity:
- Green: current
- Yellow: minor drift
- Red: major drift
"""

from __future__ import annotations

from argus_mcp.bridge.version_checker import DriftResult, DriftSeverity
from textual.widgets import Static

# Rich markup colors per severity
_SEVERITY_STYLES = {
    DriftSeverity.CURRENT: ("green", "✓"),
    DriftSeverity.PATCH: ("yellow", "↑"),
    DriftSeverity.MINOR: ("dark_orange", "⬆"),
    DriftSeverity.MAJOR: ("red", "⚠"),
    DriftSeverity.UNKNOWN: ("dim", "?"),
}


class VersionBadge(Static):
    """Displays a version drift indicator.

    Usage::

        badge = VersionBadge(drift_result)
        # Renders: [green]✓ 1.2.3[/] or [red]⚠ 1.2.3 → 2.0.0[/]
    """

    def __init__(self, drift: DriftResult, **kwargs) -> None:
        super().__init__(**kwargs)
        self._drift = drift

    def render(self) -> str:
        d = self._drift
        color, icon = _SEVERITY_STYLES.get(d.severity, ("dim", "?"))

        if d.severity == DriftSeverity.CURRENT:
            return f"[{color}]{icon} {d.current_version}[/]"

        if d.severity == DriftSeverity.UNKNOWN:
            return f"[{color}]{icon} {d.current_version}[/]"

        return f"[{color}]{icon} {d.current_version} → {d.latest_version}[/]"
