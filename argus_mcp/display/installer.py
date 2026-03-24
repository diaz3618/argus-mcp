"""Backend startup progress display

Color scheme (non-monotone):
- **Python / uvx** — Blue family: bright_blue spinner, cyan name, blue status.
- **Node / npx**   — Warm family: red spinner, dark_orange name, orange status.
- **Docker**       — Purple family: bright_magenta spinner, magenta name.
- **Remote (SSE / streamable-http)** — Neutral: white spinner/name.
- **Success**      — bold bright_green checkmark + green status (all runtimes).
- **Failure**      — bold red X + red status (all runtimes).
"""

from __future__ import annotations

import re
import sys
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TextIO

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from argus_mcp.display.braille import (
    render_empty_bar,
    render_progress_bar,
    render_scattered_bar,
    render_solid_bar,
)


class DisplayPhase(str, Enum):
    PENDING = "pending"
    BUILDING = "building"
    INITIALIZING = "initializing"
    DOWNLOADING = "downloading"
    RETRYING = "retrying"
    READY = "ready"
    FAILED = "failed"
    SKIPPED = "skipped"


# progress for non-remote backends.
# each phase transition represents a discrete progress step.
_PARALLEL_PHASE_PROGRESS: Dict[DisplayPhase, float] = {
    DisplayPhase.INITIALIZING: 0.4,
    DisplayPhase.DOWNLOADING: 0.7,
    DisplayPhase.RETRYING: 0.3,
}

# BuildKit --progress=plain output: "#6 [2/8] RUN apt-get update"
_BUILDKIT_STEP_RE = re.compile(r"\[(\d+)/(\d+)\]")

# Shared column widths for consistent alignment between parallel and completed tables
_COL_ICON = 2
_COL_NAME = 50
_COL_BAR = 19
_COL_STATUS = 36
_COL_TIMER = 7


class RuntimeKind(str, Enum):
    UVX = "uvx"
    NPX = "npx"
    DOCKER = "docker"
    PYTHON = "python"
    NODE = "node"
    REMOTE = "remote"
    UNKNOWN = "unknown"


def detect_runtime(backend_conf: Dict[str, Any]) -> RuntimeKind:
    """Determine the runtime kind from backend config."""
    svr_type = backend_conf.get("type", "")
    command = ""

    params = backend_conf.get("params")
    if params is not None:
        command = getattr(params, "command", "") or ""
    if not command:
        command = backend_conf.get("command", "") or ""

    cmd_lower = command.lower().strip()

    if cmd_lower in ("uvx", "uv"):
        return RuntimeKind.UVX
    if cmd_lower in ("npx", "npm"):
        return RuntimeKind.NPX
    if cmd_lower in ("docker", "podman"):
        return RuntimeKind.DOCKER
    if cmd_lower in ("python", "python3") or "python" in cmd_lower:
        return RuntimeKind.PYTHON
    if cmd_lower in ("node", "tsx", "ts-node", "bun", "deno"):
        return RuntimeKind.NODE

    if svr_type in ("sse", "streamable-http") and not command:
        return RuntimeKind.REMOTE

    return RuntimeKind.UNKNOWN


class _RuntimeStyle:
    """Rich style palette for a specific runtime kind."""

    __slots__ = (
        "spinner_style",
        "name_style",
        "status_style",
        "tag_style",
        "label",
    )

    def __init__(
        self,
        spinner_style: str,
        name_style: str,
        status_style: str,
        tag_style: str,
        label: str,
    ) -> None:
        self.spinner_style = spinner_style
        self.name_style = name_style
        self.status_style = status_style
        self.tag_style = tag_style
        self.label = label


_STYLES: Dict[RuntimeKind, _RuntimeStyle] = {
    # Python / uvx — blue family
    RuntimeKind.UVX: _RuntimeStyle(
        spinner_style="bold bright_blue",
        name_style="cyan",
        status_style="blue",
        tag_style="bright_cyan",
        label="uvx",
    ),
    RuntimeKind.PYTHON: _RuntimeStyle(
        spinner_style="bold blue",
        name_style="bright_cyan",
        status_style="bright_blue",
        tag_style="cyan",
        label="python",
    ),
    # Node / npx — warm family (orange + red)
    RuntimeKind.NPX: _RuntimeStyle(
        spinner_style="bold bright_red",
        name_style="dark_orange",
        status_style="orange3",
        tag_style="bright_red",
        label="npx",
    ),
    RuntimeKind.NODE: _RuntimeStyle(
        spinner_style="bold red",
        name_style="orange3",
        status_style="bright_red",
        tag_style="dark_orange",
        label="node",
    ),
    # Docker — purple family
    RuntimeKind.DOCKER: _RuntimeStyle(
        spinner_style="bold bright_magenta",
        name_style="magenta",
        status_style="bright_magenta",
        tag_style="magenta",
        label="docker",
    ),
    # Remote (SSE / streamable-http) — neutral
    RuntimeKind.REMOTE: _RuntimeStyle(
        spinner_style="bold white",
        name_style="white",
        status_style="white",
        tag_style="dim",
        label="remote",
    ),
    # Fallback
    RuntimeKind.UNKNOWN: _RuntimeStyle(
        spinner_style="bold white",
        name_style="white",
        status_style="white",
        tag_style="dim",
        label="stdio",
    ),
}


class _BackendEntry:
    """Tracks state for one backend in the display."""

    __slots__ = (
        "name",
        "runtime",
        "style",
        "phase",
        "message",
        "start_time",
        "end_time",
        "build_progress",
    )

    def __init__(self, name: str, runtime: RuntimeKind) -> None:
        self.name = name
        self.runtime = runtime
        self.style = _STYLES.get(runtime, _STYLES[RuntimeKind.UNKNOWN])
        self.phase = DisplayPhase.PENDING
        self.message = "Pending..."
        self.start_time: float = 0.0  # set on first non-PENDING phase
        self.end_time: float = 0.0  # frozen on terminal phase
        self.build_progress: float = 0.0  # 0.0→1.0 for local builds


class InstallerDisplay:
    """Progress display for MCP backend connections.

    Uses Rich ``Live`` with ``Group`` rendering to show one active backend
    at a time (spinner + build output), collapsing finished backends to a
    single status line.  This matches the prototype visual model.

    Parameters
    ----------
    backends : dict
        ``{name: config_dict}`` — the same dict from ``load_and_validate_config``.
    stream : TextIO
        Output stream (default ``sys.stderr`` to keep stdout clean for MCP
        JSON-RPC transport).
    verbose : bool
        Higher refresh rate when ``True``.
    """

    def __init__(
        self,
        backends: Dict[str, Dict[str, Any]],
        stream: TextIO = sys.stderr,
        verbose: bool = False,
        parallel: bool = False,
        verbosity: int | None = None,
    ) -> None:
        self._console = Console(stderr=True, file=stream)
        self._entries: Dict[str, _BackendEntry] = {}
        self._ordered: List[_BackendEntry] = []
        self._live: Optional[Live] = None
        self._finalized = False
        self._build_lines: Dict[str, List[str]] = {}
        self._parallel = parallel
        self._all_terminal_at: Optional[float] = None

        # Resolve verbosity: explicit int wins, else derive from bool flag
        if verbosity is not None:
            self._verbosity = verbosity
        else:
            self._verbosity = 1 if verbose else 0

        # Build-line visibility per design doc Section 7
        if self._parallel:
            # Parallel: 0=no lines, 1=5 lines (focused), 2=10 lines (all)
            self._max_build_lines = {0: 0, 1: 5}.get(self._verbosity, 10)
        else:
            # Sequential: 0=no lines, 1=15 lines, 2=30 lines
            self._max_build_lines = {0: 0, 1: 15}.get(self._verbosity, 30)

        self._last_focused_builder: Optional[str] = None

        # Sequential expand/collapse state
        self._active_name: Optional[str] = None
        self._active_spinner: Optional[Spinner] = None

        for name, conf in backends.items():
            runtime = detect_runtime(conf)
            entry = _BackendEntry(name, runtime)
            self._entries[name] = entry
            self._ordered.append(entry)

        # Sort to match startup coordinator order: remote first, then stdio
        _type_prio = {"streamable-http": 0, "sse": 1}
        self._ordered.sort(key=lambda e: _type_prio.get(backends[e.name].get("type", "stdio"), 2))

    def _format_completed_line(self, entry: _BackendEntry) -> Table:
        """Return a Rich Table row for a terminal-state backend line."""
        elapsed = (
            (entry.end_time or time.monotonic()) - entry.start_time if entry.start_time else 0.0
        )
        mins, secs = divmod(int(elapsed), 60)
        style = entry.style

        if entry.phase == DisplayPhase.READY:
            icon = Text("\u2713", style="bold bright_green")
            verb = "Connected"
            status = Text("Ready", style="bold bright_green")
        elif entry.phase == DisplayPhase.FAILED:
            icon = Text("\u2717", style="bold red")
            verb = "Connecting"
            status = Text(entry.message or "Failed", style="bold red")
        else:
            icon = Text("-", style="dim")
            verb = "Connecting"
            status = Text("Skipped", style="dim")

        label = Text.from_markup(f"{verb} [{style.name_style}]{entry.name}[/] ({style.label}):")
        timer = f"{mins}:{secs:02d}"

        tbl = Table(show_header=False, box=None, pad_edge=False, expand=False)
        tbl.add_column(width=_COL_ICON, justify="center")  # Icon
        tbl.add_column(width=_COL_NAME, justify="left", no_wrap=True)  # Label
        tbl.add_column(width=_COL_STATUS, justify="left")  # Status
        tbl.add_column(width=_COL_TIMER, justify="right")  # Timer
        tbl.add_row(icon, label, status, timer)
        return tbl

    # Parallel rendering

    _TERMINAL_PHASES = frozenset({DisplayPhase.READY, DisplayPhase.FAILED, DisplayPhase.SKIPPED})
    _IN_PROGRESS_PHASES = frozenset(
        {
            DisplayPhase.INITIALIZING,
            DisplayPhase.DOWNLOADING,
            DisplayPhase.RETRYING,
        }
    )

    @staticmethod
    def _parallel_entry_cells(
        entry: "_BackendEntry",
        elapsed: float,
    ) -> tuple[Text, Text, RenderableType, Text, str]:
        """Return (icon, verb_name, bar, status, timer) for one entry row."""
        style = entry.style
        mins, secs = divmod(int(elapsed), 60)
        timer = f"{mins}:{secs:02d}"
        name_tag = f"[{style.name_style}]{entry.name}[/] ({style.label}):"

        phase = entry.phase
        if phase == DisplayPhase.READY:
            return (
                Text("\u2713", style="bold bright_green"),
                Text.from_markup(f"Connected {name_tag}"),
                render_solid_bar(style=style.spinner_style),
                Text("Ready", style="bold bright_green"),
                timer,
            )
        if phase == DisplayPhase.FAILED:
            return (
                Text("\u2717", style="bold red"),
                Text.from_markup(f"Connecting {name_tag}"),
                render_solid_bar(style="bold red"),
                Text(entry.message or "Failed", style="bold red"),
                timer,
            )
        if phase == DisplayPhase.SKIPPED:
            return (
                Text("-", style="dim"),
                Text.from_markup(f"Connecting {name_tag}"),
                render_empty_bar(),
                Text("Skipped", style="dim"),
                timer,
            )
        if phase == DisplayPhase.PENDING:
            return (
                Text("\u2026", style="dim"),
                Text.from_markup(f"Pending {name_tag}"),
                render_empty_bar(),
                Text("Pending...", style="dim"),
                "",
            )
        if phase == DisplayPhase.BUILDING:
            return (
                Text("\u2026", style=style.spinner_style),
                Text.from_markup(f"Deploying {name_tag}"),
                render_progress_bar(
                    entry.build_progress,
                    monotone_style=style.spinner_style,
                ),
                Text(entry.message or "Building...", style=style.status_style),
                timer,
            )
        # INITIALIZING, DOWNLOADING, RETRYING
        if entry.runtime == RuntimeKind.REMOTE:
            # Remote backends: scattered (no real progress to track)
            bar = render_scattered_bar(elapsed, monotone_style=style.spinner_style)
        else:
            # Non-remote backends: phase-based progress
            bar = render_progress_bar(
                _PARALLEL_PHASE_PROGRESS.get(phase, 0.3),
                monotone_style=style.spinner_style,
            )
        return (
            Text("\u2026", style=style.spinner_style),
            Text.from_markup(f"Connecting {name_tag}"),
            bar,
            Text(
                entry.message or f"{phase.value.title()}...",
                style=style.status_style,
            ),
            timer,
        )

    def _render_build_output(self) -> List[RenderableType]:
        """Return build-log lines for the current verbosity level."""
        parts: List[RenderableType] = []
        limit = self._max_build_lines

        if self._verbosity >= 2:
            for entry in self._ordered:
                if entry.phase == DisplayPhase.BUILDING:
                    lines = self._build_lines.get(entry.name, [])
                    if lines:
                        parts.append(Text(""))
                        parts.append(
                            Text.from_markup(f"  [{entry.style.name_style}]{entry.name}[/]:")
                        )
                        for ln in lines[-limit:]:
                            parts.append(Text(f"    {ln}", style="dim"))
        elif self._verbosity >= 1 and self._last_focused_builder:
            lines = self._build_lines.get(self._last_focused_builder, [])
            if lines:
                entry = self._entries[self._last_focused_builder]
                parts.append(Text(""))
                parts.append(
                    Text.from_markup(
                        f"  [{entry.style.name_style}]{self._last_focused_builder}[/]:"
                    )
                )
                for ln in lines[-limit:]:
                    parts.append(Text(f"    {ln}", style="dim"))
        return parts

    def _build_parallel_renderable(self) -> RenderableType:
        """Render all backends simultaneously with braille progress bars."""
        now = time.monotonic()

        # Detect all-terminal transition
        if self._all_terminal_at is None and all(
            e.phase in self._TERMINAL_PHASES for e in self._ordered
        ):
            self._all_terminal_at = now

        # After 0.5s hold in all-terminal, suppress bar column (State 3)
        show_bars = self._all_terminal_at is None or (now - self._all_terminal_at) <= 0.5

        table = Table(
            show_header=False,
            box=None,
            pad_edge=False,
            expand=False,
        )
        table.add_column(width=_COL_ICON, justify="center")
        table.add_column(width=_COL_NAME, justify="left", no_wrap=True)
        if show_bars:
            table.add_column(width=_COL_BAR, justify="left")
        table.add_column(width=_COL_STATUS, justify="left")
        table.add_column(width=_COL_TIMER, justify="right")

        for entry in self._ordered:
            elapsed = (entry.end_time or now) - entry.start_time if entry.start_time else 0.0
            icon, verb_name, bar, status, timer = self._parallel_entry_cells(entry, elapsed)
            if show_bars:
                table.add_row(icon, verb_name, bar, status, timer)
            else:
                table.add_row(icon, verb_name, status, timer)

        if self._max_build_lines == 0:
            return table

        build_parts = self._render_build_output()
        if build_parts:
            return Group(table, *build_parts)
        return table

    def _build_renderable(self) -> RenderableType:
        """Render all visible backends in config order inside the Live area."""
        if self._parallel:
            return self._build_parallel_renderable()

        parts: List[RenderableType] = []

        for entry in self._ordered:
            # Skip backends that haven't started yet
            if entry.phase == DisplayPhase.PENDING:
                continue

            # Terminal states: show completed line
            if entry.phase in (DisplayPhase.READY, DisplayPhase.FAILED, DisplayPhase.SKIPPED):
                parts.append(self._format_completed_line(entry))
                continue

            # Active backend with spinner
            if self._active_name == entry.name and self._active_spinner is not None:
                parts.append(self._active_spinner)
                # Build output lines (for docker builds)
                if self._max_build_lines > 0:
                    lines = self._build_lines.get(entry.name, [])
                    if lines:
                        visible = lines[-self._max_build_lines :]
                        for ln in visible:
                            parts.append(Text(f"    {ln}", style="dim"))
                continue

            # In-progress but not active: dim status line
            style = entry.style
            msg = entry.message or f"{entry.phase.value.title()}..."
            line = (
                f"  [dim]\u2026[/] [bold]Connecting[/] [{style.name_style}]{entry.name}[/] "
                f"({style.label}): {msg}"
            )
            parts.append(Text.from_markup(line))

        if not parts:
            parts.append(Text(""))

        return Group(*parts)

    def _refresh(self) -> None:
        """Push the current renderable to the Live display."""
        if self._live is not None:
            self._live.update(self._build_renderable())

    def _build_runtime_summary(self) -> str:
        """Return a Rich-formatted summary of runtime-type counts."""
        npx_count = sum(
            1 for e in self._ordered if e.runtime in (RuntimeKind.NPX, RuntimeKind.NODE)
        )
        uvx_count = sum(
            1 for e in self._ordered if e.runtime in (RuntimeKind.UVX, RuntimeKind.PYTHON)
        )
        docker_count = sum(1 for e in self._ordered if e.runtime == RuntimeKind.DOCKER)
        remote_count = sum(1 for e in self._ordered if e.runtime == RuntimeKind.REMOTE)
        total = len(self._ordered)
        other_count = total - npx_count - uvx_count - docker_count - remote_count

        parts: List[str] = []
        if uvx_count:
            parts.append(f"[bright_blue]{uvx_count} uvx[/bright_blue]")
        if npx_count:
            parts.append(f"[dark_orange]{npx_count} npx[/dark_orange]")
        if docker_count:
            parts.append(f"[bright_magenta]{docker_count} docker[/bright_magenta]")
        if remote_count:
            parts.append(f"[white]{remote_count} remote[/white]")
        if other_count:
            parts.append(f"{other_count} other")
        return ", ".join(parts)

    def render_initial(self) -> None:
        """Print the header and start the Rich Live display."""
        total = len(self._ordered)
        if total == 0:
            return

        summary = self._build_runtime_summary()
        self._console.print(f"\n[bold]Backend operations:[/bold] {total} connections ({summary})\n")

        fps = 12 if self._verbosity >= 1 else (8 if self._parallel else 4)
        self._live = Live(
            Text(""),
            console=self._console,
            refresh_per_second=fps,
        )
        self._live.start()

    def _collapse_to_completed(self, name: str, entry: _BackendEntry) -> None:
        """Mark a backend as finished: freeze elapsed time and clear active state."""
        entry.end_time = time.monotonic()
        self._build_lines.pop(name, None)
        if self._active_name == name:
            self._active_name = None
            self._active_spinner = None
            self._promote_next_active()

    def _promote_next_active(self) -> None:
        """Activate the next in-progress backend if nothing is currently shown."""
        if self._active_name is not None:
            return
        for entry in self._ordered:
            if entry.phase not in (
                DisplayPhase.READY,
                DisplayPhase.FAILED,
                DisplayPhase.SKIPPED,
                DisplayPhase.PENDING,
            ):
                self._set_active(entry.name, entry)
                return

    def _set_active(self, name: str, entry: _BackendEntry) -> None:
        """Make *name* the active backend with an appropriate spinner."""
        self._active_name = name
        style = entry.style

        if entry.phase == DisplayPhase.BUILDING:
            header = f" [bold]Deploying[/] [{style.name_style}]{name}[/] ({style.label})"
            self._active_spinner = Spinner(
                "dots",
                text=Text.from_markup(header),
                style="yellow",
            )
        else:
            msg = entry.message or f"{entry.phase.value.title()}..."
            header = f" [bold]Connecting[/] [{style.name_style}]{name}[/] ({style.label}): {msg}"
            self._active_spinner = Spinner(
                "dots",
                text=Text.from_markup(header),
                style=style.spinner_style,
            )

    def _apply_phase_update(
        self,
        entry: _BackendEntry,
        phase: str,
        name: str,
    ) -> None:
        """Parse *phase* string and update *entry* state, clearing stale build output."""
        try:
            new_phase = DisplayPhase(phase)
        except ValueError:
            return
        # Clear build output when leaving BUILDING phase
        if new_phase != DisplayPhase.BUILDING and name in self._build_lines:
            del self._build_lines[name]
        # Record the start time on first non-PENDING phase
        if entry.phase == DisplayPhase.PENDING and new_phase != DisplayPhase.PENDING:
            entry.start_time = time.monotonic()
        entry.phase = new_phase

    def _handle_build_output(self, entry: _BackendEntry, name: str) -> None:
        """Accumulate build log lines, parse progress, and manage focused-builder."""
        if entry.message:
            lines = self._build_lines.setdefault(name, [])
            if not lines:
                lines.append(f"$ docker build -t argus-mcp-{name} .")
                lines.append("")
            lines.append(entry.message)
            if len(lines) > 200:
                del lines[:100]

            # RC-1: Parse BuildKit step pattern to compute build_progress
            m = _BUILDKIT_STEP_RE.search(entry.message)
            if m:
                current, total = int(m.group(1)), int(m.group(2))
                if total > 0:
                    entry.build_progress = min(current / total, 1.0)

        if self._parallel:
            self._last_focused_builder = name

    def update(
        self,
        name: str,
        *,
        phase: Optional[str] = None,
        message: Optional[str] = None,
    ) -> None:
        """Update a backend's display state."""
        entry = self._entries.get(name)
        if entry is None or self._finalized or self._live is None:
            return

        if phase is not None:
            self._apply_phase_update(entry, phase, name)

        if message is not None:
            entry.message = message

        if entry.phase in (DisplayPhase.READY, DisplayPhase.FAILED):
            if self._parallel:
                entry.end_time = time.monotonic()
            else:
                self._collapse_to_completed(name, entry)
            self._refresh()
            return

        if entry.phase == DisplayPhase.BUILDING:
            self._handle_build_output(entry, name)

        if not self._parallel:
            if entry.phase == DisplayPhase.BUILDING:
                self._set_active(name, entry)
            elif self._active_name is None or self._active_name == name:
                self._set_active(name, entry)
        self._refresh()

    def finalize(self) -> None:
        """Stop the Rich Live display and print a summary line."""
        if self._finalized:
            return
        self._finalized = True

        self._build_lines.clear()
        self._active_name = None
        self._active_spinner = None

        # Mark any remaining non-terminal backends as skipped
        for entry in self._ordered:
            if entry.phase not in (DisplayPhase.READY, DisplayPhase.FAILED, DisplayPhase.SKIPPED):
                entry.phase = DisplayPhase.SKIPPED
                entry.end_time = time.monotonic()

        # Final refresh to render all terminal states before stopping
        self._refresh()

        try:
            if self._live is not None:
                self._live.stop()
        except (BrokenPipeError, SystemExit):
            pass

        ready = sum(1 for e in self._ordered if e.phase == DisplayPhase.READY)
        failed = sum(1 for e in self._ordered if e.phase == DisplayPhase.FAILED)
        total = len(self._ordered)

        try:
            if failed == 0:
                self._console.print(
                    f"\n[bold bright_green]Backends: {ready}/{total} connected"
                    f"[/bold bright_green]\n"
                )
            else:
                self._console.print(
                    f"\n[bold bright_red]Backends: {ready}/{total} connected"
                    f"[/bold bright_red]  [red]({failed} failed)[/red]\n"
                )
        except (BrokenPipeError, SystemExit):
            pass

    def make_callback(self) -> Callable[..., None]:
        """Return a callback suitable for ClientManager progress reporting.

        Signature: ``callback(name, phase, message=None)``
        """

        def _cb(name: str, phase: str, message: str | None = None) -> None:
            self.update(name, phase=phase, message=message)

        return _cb
