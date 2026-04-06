"""Tests for argus_cli.repl.dispatch — command routing and multiline collection."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from argus_cli.repl.state import (
    CompletionData,
    ConnectionState,
    ReplState,
    SessionState,
)


def _make_repl_state(**overrides) -> ReplState:
    """Build a ReplState with sensible test defaults."""
    cfg = MagicMock()
    cfg.server_url = "http://localhost:8080"
    cfg.token = ""
    cfg.output_format = "json"
    cfg.no_color = False
    return ReplState(
        config=cfg,
        connection=ConnectionState(),
        completions=CompletionData(**overrides.pop("completions", {})),
        session=SessionState(**overrides.pop("session", {})),
    )


# ── dispatch_command ──────────────────────────────────────────────────


def test_dispatch_empty_input():
    """Empty input should be a no-op."""
    from argus_cli.repl.dispatch import dispatch_command

    console = MagicMock()
    state = _make_repl_state()
    dispatch_command(console, state, "   ")
    # No error printed, no app call
    console.print.assert_not_called()


def test_dispatch_parse_error():
    """Unterminated quote should show parse error."""
    from argus_cli.repl.dispatch import dispatch_command

    console = MagicMock()
    state = _make_repl_state()
    dispatch_command(console, state, "tools list 'unterminated")
    console.print.assert_called_once()
    assert "Parse error" in str(console.print.call_args)


@patch("argus_cli.main.app")
@patch("argus_cli.config.set_repl_mode")
def test_dispatch_calls_app(mock_set_repl, mock_app):
    """Normal command should invoke the Typer app."""
    from argus_cli.repl.dispatch import dispatch_command

    console = MagicMock()
    state = _make_repl_state()
    dispatch_command(console, state, "server status")
    mock_app.assert_called_once()
    call_args = mock_app.call_args[0][0]
    assert "server" in call_args
    assert "status" in call_args


@patch("argus_cli.main.app")
@patch("argus_cli.config.set_repl_mode")
def test_dispatch_injects_scoped_backend(mock_set_repl, mock_app):
    """When a backend is scoped, it should be injected into tools/resources/prompts commands."""
    from argus_cli.repl.dispatch import dispatch_command

    console = MagicMock()
    state = _make_repl_state(session={"scoped_backend": "my-backend"})
    dispatch_command(console, state, "tools list")
    call_args = mock_app.call_args[0][0]
    assert "--backend" in call_args
    assert "my-backend" in call_args


@patch("argus_cli.main.app")
@patch("argus_cli.config.set_repl_mode")
def test_dispatch_no_inject_for_non_scoped_commands(mock_set_repl, mock_app):
    """Backend should NOT be injected for commands like 'server'."""
    from argus_cli.repl.dispatch import dispatch_command

    console = MagicMock()
    state = _make_repl_state(session={"scoped_backend": "my-backend"})
    dispatch_command(console, state, "server status")
    call_args = mock_app.call_args[0][0]
    assert "--backend" not in call_args


@patch("argus_cli.main.app", side_effect=SystemExit(0))
@patch("argus_cli.config.set_repl_mode")
def test_dispatch_handles_system_exit(mock_set_repl, mock_app):
    """SystemExit from app should be silently caught."""
    from argus_cli.repl.dispatch import dispatch_command

    console = MagicMock()
    state = _make_repl_state()
    # Should not raise
    dispatch_command(console, state, "server status")


@patch("argus_cli.main.app", side_effect=RuntimeError("boom"))
@patch("argus_cli.config.set_repl_mode")
def test_dispatch_handles_exception(mock_set_repl, mock_app):
    """Exceptions from app should be caught and printed."""
    from argus_cli.repl.dispatch import dispatch_command

    console = MagicMock()
    state = _make_repl_state()
    dispatch_command(console, state, "server status")
    console.print.assert_called()
    assert "Command failed" in str(console.print.call_args)


@patch("argus_cli.main.app")
@patch("argus_cli.config.set_repl_mode")
def test_dispatch_captures_json_result(mock_set_repl, mock_app):
    """JSON stdout output should be captured as last_result dict."""
    from argus_cli.repl.dispatch import dispatch_command

    import io
    import sys

    expected = {"status": "ok"}

    def fake_app(args, standalone_mode=False):
        sys.stdout.write(json.dumps(expected))

    mock_app.side_effect = fake_app
    console = MagicMock()
    state = _make_repl_state()
    dispatch_command(console, state, "health status")
    assert state.session.last_result == expected


@patch("argus_cli.main.app")
@patch("argus_cli.config.set_repl_mode")
def test_dispatch_captures_plain_text_result(mock_set_repl, mock_app):
    """Non-JSON stdout should be captured as a stripped string."""
    from argus_cli.repl.dispatch import dispatch_command

    import sys

    def fake_app(args, standalone_mode=False):
        sys.stdout.write("plain text output\n")

    mock_app.side_effect = fake_app
    console = MagicMock()
    state = _make_repl_state()
    dispatch_command(console, state, "server status")
    assert state.session.last_result == "plain text output"


@patch("argus_cli.main.app")
@patch("argus_cli.config.set_repl_mode")
def test_dispatch_restores_output_format(mock_set_repl, mock_app):
    """output_format should be restored even if the command changes it."""
    from argus_cli.repl.dispatch import dispatch_command

    console = MagicMock()
    state = _make_repl_state()
    state.config.output_format = "rich"

    def fake_app(args, standalone_mode=False):
        state.config.output_format = "json"

    mock_app.side_effect = fake_app
    dispatch_command(console, state, "tools list")
    assert state.config.output_format == "rich"


# ── collect_multiline ─────────────────────────────────────────────────


def test_collect_multiline_single_continuation():
    """Backslash continuation should merge lines."""
    from argus_cli.repl.dispatch import collect_multiline

    session = MagicMock()
    session.prompt.return_value = "second line"
    result = collect_multiline(session, "first line \\")
    assert result == "first line second line"


def test_collect_multiline_multiple_continuations():
    """Multiple backslash lines should all merge."""
    from argus_cli.repl.dispatch import collect_multiline

    session = MagicMock()
    session.prompt.side_effect = ["line2 \\", "line3"]
    result = collect_multiline(session, "line1 \\")
    assert result == "line1 line2 line3"


def test_collect_multiline_keyboard_interrupt():
    """KeyboardInterrupt should end collection."""
    from argus_cli.repl.dispatch import collect_multiline

    session = MagicMock()
    session.prompt.side_effect = KeyboardInterrupt
    result = collect_multiline(session, "start \\")
    assert result == "start"
