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

import sys
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TextIO

from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

# ── Phase enum (display-side, decoupled from runtime) ────────────────────


class DisplayPhase(str, Enum):
    PENDING = "pending"
    BUILDING = "building"
    INITIALIZING = "initializing"
    DOWNLOADING = "downloading"
    RETRYING = "retrying"
    READY = "ready"
    FAILED = "failed"
    SKIPPED = "skipped"


# ── Runtime detection ────────────────────────────────────────────────────


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


# ── Style configuration per runtime ─────────────────────────────────────


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


# ── Backend display entry ────────────────────────────────────────────────


class _BackendEntry:
    """Tracks state for one backend in the display."""

    __slots__ = ("name", "runtime", "style", "phase", "message", "start_time")

    def __init__(self, name: str, runtime: RuntimeKind) -> None:
        self.name = name
        self.runtime = runtime
        self.style = _STYLES.get(runtime, _STYLES[RuntimeKind.UNKNOWN])
        self.phase = DisplayPhase.PENDING
        self.message = "Pending..."
        self.start_time: float = 0.0  # set on first non-PENDING phase


# ── Main display class ──────────────────────────────────────────────────


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
    ) -> None:
        self._console = Console(stderr=True, file=stream)
        self._entries: Dict[str, _BackendEntry] = {}
        self._ordered: List[_BackendEntry] = []
        self._live: Optional[Live] = None
        self._finalized = False
        self._build_lines: Dict[str, List[str]] = {}
        self._max_build_lines = 15
        self._verbose = verbose

        # Sequential expand/collapse state
        self._active_name: Optional[str] = None
        self._active_spinner: Optional[Spinner] = None

        for name, conf in backends.items():
            runtime = detect_runtime(conf)
            entry = _BackendEntry(name, runtime)
            self._entries[name] = entry
            self._ordered.append(entry)

    # ── Rendering ────────────────────────────────────────────────────

    def _build_renderable(self) -> RenderableType:
        """Build the active spinner + build output (completed lines are printed directly)."""
        parts: List[RenderableType] = []

        if self._active_name is not None and self._active_spinner is not None:
            parts.append(self._active_spinner)

            lines = self._build_lines.get(self._active_name, [])
            if lines:
                visible = lines[-self._max_build_lines :]
                for ln in visible:
                    parts.append(Text(f"    {ln}", style="dim"))

        if not parts:
            parts.append(Text(""))

        return Group(*parts)

    def _refresh(self) -> None:
        """Push the current renderable to the Live display."""
        if self._live is not None:
            self._live.update(self._build_renderable())

    # ── Public API ───────────────────────────────────────────────────

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

        fps = 12 if self._verbose else 4
        self._live = Live(
            Text(""),
            console=self._console,
            refresh_per_second=fps,
        )
        self._live.start()

    def _collapse_to_completed(self, name: str, entry: _BackendEntry) -> None:
        """Collapse a finished backend: print its status line permanently above the Live area."""
        elapsed = time.monotonic() - entry.start_time if entry.start_time else 0.0
        mins, secs = divmod(int(elapsed), 60)
        style = entry.style

        label = f"Connecting {name} ({style.label}):"

        if entry.phase == DisplayPhase.READY:
            icon = "[bold bright_green]\u2713[/]"
            status = "Ready"
        elif entry.phase == DisplayPhase.FAILED:
            icon = "[bold red]\u2717[/]"
            status = entry.message or "Failed"
        else:
            icon = "[dim]-[/]"
            status = "Skipped"

        line = f"  {icon} [{style.name_style}]{label:<42}[/] {status} 0:{mins:02d}:{secs:02d}"

        # Print permanently above the Live display area (Rich handles cursor)
        if self._live is not None:
            self._live.console.print(Text.from_markup(line))
        else:
            self._console.print(Text.from_markup(line))

        # Clear active state if this was the active backend
        self._build_lines.pop(name, None)
        if self._active_name == name:
            self._active_name = None
            self._active_spinner = None

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

        # Parse the new phase
        if phase is not None:
            try:
                new_phase = DisplayPhase(phase)
                # Clear build output when leaving BUILDING phase
                if new_phase != DisplayPhase.BUILDING and name in self._build_lines:
                    del self._build_lines[name]
                # Record the start time on first non-PENDING phase
                if entry.phase == DisplayPhase.PENDING and new_phase != DisplayPhase.PENDING:
                    entry.start_time = time.monotonic()
                entry.phase = new_phase
            except ValueError:
                pass

        if message is not None:
            entry.message = message

        # ── Terminal phases: collapse to completed line ───────────
        if entry.phase in (DisplayPhase.READY, DisplayPhase.FAILED):
            self._collapse_to_completed(name, entry)
            self._refresh()
            return

        # ── BUILDING phase: accumulate build output ──────────────
        if entry.phase == DisplayPhase.BUILDING:
            if entry.message:
                lines = self._build_lines.setdefault(name, [])
                if not lines:
                    lines.append(f"$ docker build -t argus-mcp-{name} .")
                    lines.append("")
                lines.append(entry.message)
                if len(lines) > 200:
                    del lines[:100]

        # ── Set this backend as the active one ───────────────────
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

        # Collapse any remaining non-terminal backends as skipped
        for entry in self._ordered:
            if entry.phase not in (DisplayPhase.READY, DisplayPhase.FAILED):
                entry.phase = DisplayPhase.SKIPPED
                self._collapse_to_completed(entry.name, entry)

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
