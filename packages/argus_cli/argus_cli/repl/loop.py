"""Main REPL loop — entry point and input handling."""

from __future__ import annotations

__all__ = ["start_repl"]

import json
import shlex
from typing import TYPE_CHECKING, Any

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import NestedCompleter
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings

from argus_cli._console import get_console
from argus_cli.repl.completions import build_command_tree, refresh_completions
from argus_cli.repl.dispatch import collect_multiline, dispatch_command
from argus_cli.repl.handlers import (
    handle_alias,
    handle_connect,
    handle_history,
    handle_set,
    handle_unalias,
    handle_use,
    handle_watch,
    show_banner,
    show_help,
)
from argus_cli.repl.state import ReplState, ensure_history_dir
from argus_cli.repl.toolbar import make_prompt, make_toolbar

if TYPE_CHECKING:
    from argus_cli.config import CliConfig

# Dispatch table for REPL-exclusive commands.
# All handlers accept (console, state, args) for uniform dispatch.
_REPL_HANDLERS: dict[str, Any] = {
    "clear": lambda console, _state, _args: console.clear(),
    "help": lambda console, _state, _args: show_help(console),
    "history": lambda console, state, _args: handle_history(
        console,
        limit=state.config.history_limit,
    ),
    "use": lambda console, state, args: handle_use(console, state, args),
    "alias": lambda console, state, args: handle_alias(console, state, args),
    "unalias": lambda console, state, args: handle_unalias(console, state, args),
    "watch": lambda console, state, args: handle_watch(
        console,
        state,
        args,
        dispatch_fn=dispatch_command,
    ),
    "connect": lambda console, state, args: handle_connect(console, state, args),
    "set": lambda console, state, args: handle_set(console, state, args),
}


def _build_key_bindings(state: ReplState) -> KeyBindings:
    """Create custom key bindings for the REPL session."""
    kb = KeyBindings()

    @kb.add("c-r")
    def _refresh(_event: Any) -> None:
        """Ctrl-R: Refresh completions from server."""
        refresh_completions(state)

    @kb.add("c-l")
    def _clear(event: Any) -> None:
        """Ctrl-L: Clear the screen."""
        event.app.renderer.clear()

    return kb


def start_repl(config: CliConfig) -> None:
    """Start the interactive REPL session."""
    console = get_console(no_color=config.no_color)
    state = ReplState(config=config)

    # Initial connection & data fetch
    refresh_completions(state)

    # Banner + connection summary
    show_banner(console, state)

    # Set up prompt-toolkit session
    history_path = ensure_history_dir()
    completer = NestedCompleter.from_nested_dict(build_command_tree(state))

    session: PromptSession[str] = PromptSession(
        history=FileHistory(history_path),
        auto_suggest=AutoSuggestFromHistory(),
        completer=completer,
        complete_while_typing=True,
        vi_mode=config.vi_mode,
        key_bindings=_build_key_bindings(state),
    )

    while True:
        try:
            toolbar = make_toolbar(state) if config.show_toolbar else None
            # sync prompt — async migration deferred (FW-M5); see frameworks report
            text = session.prompt(
                make_prompt(state),
                bottom_toolbar=toolbar,
            )
        except KeyboardInterrupt:
            continue
        except EOFError:
            console.print("[muted]Goodbye.[/]")
            break

        text = text.strip()
        if not text:
            continue

        # Multi-line continuation
        if text.endswith("\\"):
            text = collect_multiline(session, text)

        # Exit
        if text in ("exit", "quit"):
            console.print("[muted]Goodbye.[/]")
            break

        # $_ variable substitution
        if "$_" in text and state.session.last_result is not None:
            if isinstance(state.session.last_result, str):
                text = text.replace("$_", state.session.last_result)
            else:
                text = text.replace("$_", json.dumps(state.session.last_result))

        # Alias expansion (first word only)
        first_word = text.split()[0] if text.split() else ""
        if first_word in state.session.aliases:
            text = state.session.aliases[first_word] + text[len(first_word) :]

        # Parse into parts
        try:
            parts = shlex.split(text)
        except ValueError as e:
            console.print(f"  [error]Parse error:[/] {e}")
            continue

        if not parts:
            continue

        cmd = parts[0]
        args = parts[1:]

        # ── REPL-exclusive commands ────────────────────────────────
        handler = _REPL_HANDLERS.get(cmd)
        if handler is not None:
            handler(console, state, args)
            if cmd == "connect":
                completer = NestedCompleter.from_nested_dict(build_command_tree(state))
                session.completer = completer
            continue

        # ── Dispatch to Typer ──────────────────────────────────────
        dispatch_command(console, state, text)

        # Refresh completions after state-mutating commands
        if cmd in ("config", "backends", "registry", "skills"):
            refresh_completions(state)
            completer = NestedCompleter.from_nested_dict(build_command_tree(state))
            session.completer = completer
