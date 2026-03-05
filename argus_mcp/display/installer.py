"""Backend startup progress display.

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

from rich.console import Console
from rich.progress import (
    Progress,
    ProgressColumn,
    SpinnerColumn,
    Task,
    TimeElapsedColumn,
)
from rich.text import Text

# ── Phase enum (display-side, decoupled from runtime) ────────────────────


class DisplayPhase(str, Enum):
    PENDING = "pending"
    INITIALIZING = "initializing"
    DOWNLOADING = "downloading"  # docker pull / npm install
    RETRYING = "retrying"  # automatic retry after failure
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


# ── Custom Rich column: status-aware spinner ────────────────────────────


class _StatusSpinnerColumn(ProgressColumn):
    """Spinner that shows animated dots while running, then a result icon.

    While a task is active it renders Rich "dots" spinner coloured via
    ``task.fields["spinner_style"]``.  Once the task is finished, it renders
    ``task.fields["result_icon"]`` (checkmark or X) with the matching style.
    """

    def __init__(self) -> None:
        super().__init__()
        self._spinner = SpinnerColumn("dots")

    def render(self, task: Task) -> Text:
        fields = task.fields

        if task.finished:
            icon: str = fields.get("result_icon", "\u2713")
            icon_style: str = fields.get("result_style", "bold bright_green")
            return Text(f"  {icon}", style=icon_style)

        # Delegate to the inner SpinnerColumn for the animated dots frame
        spinner_text = self._spinner.render(task)
        style_str: str = fields.get("spinner_style", "bold white")
        result = Text("  ", style=style_str)
        result.append(str(spinner_text))
        return result


# ── Custom Rich column: coloured backend name + tag ─────────────────────


class _ColouredDescColumn(ProgressColumn):
    """Renders ``Connecting <name> (<tag>): `` with per-task Rich styles."""

    def render(self, task: Task) -> Text:
        fields = task.fields
        name: str = fields.get("backend_name", task.description)
        name_style: str = fields.get("name_style", "white")
        tag_label: str = fields.get("tag_label", "")
        tag_style: str = fields.get("tag_style", "dim")

        line = Text("Connecting ")
        line.append(name, style=name_style)
        line.append(" (")
        line.append(tag_label, style=tag_style)
        line.append("): ")
        return line


# ── Custom Rich column: phase status text ───────────────────────────────


class _StatusTextColumn(ProgressColumn):
    """Renders the current phase message (Pending / Initializing / Ready)."""

    def render(self, task: Task) -> Text:
        fields = task.fields
        status_msg: str = fields.get("status_msg", "Pending...")
        status_style: str = fields.get("current_status_style", "blue")
        return Text(status_msg, style=status_style)


# ── Backend display entry ────────────────────────────────────────────────


class _BackendEntry:
    """Tracks state for one backend in the Rich progress table."""

    __slots__ = ("name", "runtime", "style", "phase", "message", "start_time", "task_id")

    def __init__(self, name: str, runtime: RuntimeKind) -> None:
        self.name = name
        self.runtime = runtime
        self.style = _STYLES.get(runtime, _STYLES[RuntimeKind.UNKNOWN])
        self.phase = DisplayPhase.PENDING
        self.message = "Pending..."
        self.start_time = time.monotonic()
        self.task_id: Any = None  # Rich TaskID, set during render_initial


# ── Main display class ──────────────────────────────────────────────────


class InstallerDisplay:
    """Progress display for MCP backend connections.

    Parameters
    ----------
    backends : dict
        ``{name: config_dict}`` — the same dict from ``load_and_validate_config``.
    stream : TextIO
        Output stream (default ``sys.stderr`` to keep stdout clean for MCP
        JSON-RPC transport).
    """

    def __init__(
        self,
        backends: Dict[str, Dict[str, Any]],
        stream: TextIO = sys.stderr,
    ) -> None:
        self._console = Console(stderr=True, file=stream)
        self._entries: Dict[str, _BackendEntry] = {}
        self._ordered: List[_BackendEntry] = []
        self._progress: Optional[Progress] = None
        self._finalized = False

        for name, conf in backends.items():
            runtime = detect_runtime(conf)
            entry = _BackendEntry(name, runtime)
            self._entries[name] = entry
            self._ordered.append(entry)

    # ── Public API ───────────────────────────────────────────────────

    def render_initial(self) -> None:
        """Print the header and start the Rich Progress live display."""
        total = len(self._ordered)
        if total == 0:
            return

        # Count runtime types for the header summary
        npx_count = sum(
            1 for e in self._ordered if e.runtime in (RuntimeKind.NPX, RuntimeKind.NODE)
        )
        uvx_count = sum(
            1 for e in self._ordered if e.runtime in (RuntimeKind.UVX, RuntimeKind.PYTHON)
        )
        docker_count = sum(1 for e in self._ordered if e.runtime == RuntimeKind.DOCKER)
        remote_count = sum(1 for e in self._ordered if e.runtime == RuntimeKind.REMOTE)
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

        summary = ", ".join(parts)
        self._console.print(f"\n[bold]Backend operations:[/bold] {total} connections ({summary})\n")

        # Build the Rich Progress display with custom columns
        self._progress = Progress(
            _StatusSpinnerColumn(),
            _ColouredDescColumn(),
            _StatusTextColumn(),
            TimeElapsedColumn(),
            console=self._console,
            transient=False,
            redirect_stdout=False,
            redirect_stderr=False,
            refresh_per_second=12,
        )
        self._progress.start()

        # Add a task per backend
        for entry in self._ordered:
            style = entry.style
            task_id = self._progress.add_task(
                entry.name,
                total=1,
                completed=0,
                # Custom fields consumed by our ProgressColumn subclasses
                backend_name=entry.name,
                spinner_style=style.spinner_style,
                name_style=style.name_style,
                tag_label=style.label,
                tag_style=style.tag_style,
                status_msg="Pending...",
                current_status_style=style.status_style,
                result_icon="\u2713",  # ✓
                result_style="bold bright_green",
            )
            entry.task_id = task_id

    def update(
        self,
        name: str,
        *,
        phase: Optional[str] = None,
        message: Optional[str] = None,
    ) -> None:
        """Update a backend's display state."""
        entry = self._entries.get(name)
        if entry is None or self._finalized or self._progress is None:
            return

        if phase is not None:
            try:
                entry.phase = DisplayPhase(phase)
            except ValueError:
                pass

        if message is not None:
            entry.message = message

        style = entry.style

        if entry.phase == DisplayPhase.READY:
            self._progress.update(
                entry.task_id,
                completed=1,  # marks task finished → spinner stops
                status_msg="Ready",
                current_status_style="green",
                result_icon="\u2713",  # ✓
                result_style="bold bright_green",
            )
        elif entry.phase == DisplayPhase.FAILED:
            msg = entry.message or "Failed"
            self._progress.update(
                entry.task_id,
                completed=1,
                status_msg=msg,
                current_status_style="red",
                result_icon="\u2717",  # ✗
                result_style="bold red",
            )
        elif entry.phase == DisplayPhase.DOWNLOADING:
            msg = entry.message or "Downloading..."
            self._progress.update(
                entry.task_id,
                status_msg=msg,
                current_status_style=style.status_style,
            )
        elif entry.phase == DisplayPhase.RETRYING:
            msg = entry.message or "Retrying..."
            # Reset completed so the spinner reappears
            self._progress.update(
                entry.task_id,
                completed=0,
                status_msg=msg,
                current_status_style="yellow",
                spinner_style="bold yellow",
            )
        elif entry.phase == DisplayPhase.INITIALIZING:
            msg = entry.message or "Initializing..."
            self._progress.update(
                entry.task_id,
                status_msg=msg,
                current_status_style=style.status_style,
            )
        else:
            self._progress.update(
                entry.task_id,
                status_msg=entry.message or "Pending...",
                current_status_style=style.status_style,
            )

    def finalize(self) -> None:
        """Stop the Rich live display and print a summary line."""
        if self._finalized:
            return
        self._finalized = True

        # Force-finish any still-pending tasks so spinners stop.
        # Wrap in BrokenPipeError guard — stdout may already be closed
        # if the server was started via `timeout` or piped to a pager.
        try:
            if self._progress is not None:
                for entry in self._ordered:
                    if entry.task_id is not None:
                        task_obj = self._progress.tasks[entry.task_id]
                        if not task_obj.finished:
                            self._progress.update(
                                entry.task_id,
                                completed=1,
                                status_msg="Skipped",
                                current_status_style="dim",
                                result_icon="-",
                                result_style="dim",
                            )
                self._progress.stop()
        except (BrokenPipeError, SystemExit):
            pass  # stdout closed — nothing to display

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
            pass  # stdout closed — nothing to display

    def make_callback(self) -> Callable[..., None]:
        """Return a callback suitable for ClientManager progress reporting.

        Signature: ``callback(name, phase, message=None)``
        """

        def _cb(name: str, phase: str, message: str | None = None) -> None:
            self.update(name, phase=phase, message=message)

        return _cb
