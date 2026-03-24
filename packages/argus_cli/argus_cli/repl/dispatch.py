"""Command dispatch — routes REPL input to the Typer app."""

from __future__ import annotations

__all__ = ["collect_multiline", "dispatch_command"]

import io
import json
import shlex
import sys

from prompt_toolkit import PromptSession
from rich.console import Console

from argus_cli.config import DEFAULT_SERVER_URL
from argus_cli.repl.state import ReplState


def dispatch_command(console: Console, state: ReplState, text: str) -> None:
    """Dispatch a REPL input line to the Typer app via direct invocation."""
    from argus_cli.config import set_repl_mode
    from argus_cli.main import app

    try:
        args = shlex.split(text)
    except ValueError as e:
        console.print(f"  [error]Parse error:[/] {e}")
        return

    if not args:
        return

    # Inject scoped backend for relevant commands
    if (
        state.session.scoped_backend
        and args[0] in ("tools", "resources", "prompts")
        and "--backend" not in args
    ):
        args.extend(["--backend", state.session.scoped_backend])

    # Build global flags from current REPL config
    global_args: list[str] = []
    if state.config.server_url != DEFAULT_SERVER_URL:
        global_args.extend(["--server", state.config.server_url])
    if state.config.token:
        global_args.extend(["--token", state.config.token])
    global_args.extend(["--output", state.config.output_format])
    if state.config.no_color:
        global_args.append("--no-color")

    # Tee stdout to capture output for $_ while still printing live
    old_stdout = sys.stdout
    capture = io.StringIO()

    class TeeWriter:
        """Write to both the real stdout and a capture buffer."""

        def write(self, s: str) -> int:
            old_stdout.write(s)
            capture.write(s)
            return len(s)

        def flush(self) -> None:
            old_stdout.flush()

    set_repl_mode(True)
    sys.stdout = TeeWriter()
    try:
        app(global_args + args, standalone_mode=False)
    except SystemExit:
        pass
    except Exception as exc:
        console.print(f"  [error]Command failed:[/] {exc}")
    finally:
        sys.stdout = old_stdout
        set_repl_mode(False)

    # Capture last result for $_ substitution
    captured = capture.getvalue()
    if captured:
        try:
            state.session.last_result = json.loads(captured)
        except (json.JSONDecodeError, ValueError):
            state.session.last_result = captured.strip()


def collect_multiline(session: PromptSession[str], first_line: str) -> str:
    """Collect continuation lines for ``\\`` multi-line input."""
    lines = [first_line.rstrip("\\").rstrip()]

    while True:
        try:
            cont = session.prompt("... ")
        except (KeyboardInterrupt, EOFError):
            break

        if cont.rstrip().endswith("\\"):
            lines.append(cont.rstrip("\\").rstrip())
        else:
            lines.append(cont)
            break

    return " ".join(lines)
