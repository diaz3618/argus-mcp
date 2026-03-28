"""REPL package — interactive shell for Argus CLI."""

from argus_cli.repl.completions import build_command_tree, refresh_completions
from argus_cli.repl.dispatch import dispatch_command
from argus_cli.repl.handlers import (
    handle_alias,
    handle_connect,
    handle_set,
    handle_unalias,
    handle_use,
)
from argus_cli.repl.loop import start_repl
from argus_cli.repl.state import ReplState
from argus_cli.repl.toolbar import make_prompt, make_toolbar

__all__ = [
    "ReplState",
    "build_command_tree",
    "dispatch_command",
    "handle_alias",
    "handle_connect",
    "handle_set",
    "handle_unalias",
    "handle_use",
    "make_prompt",
    "make_toolbar",
    "refresh_completions",
    "start_repl",
]
