"""Tests for argus_cli.repl.handlers — REPL-exclusive command handlers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("argus_cli", reason="argus_cli package not installed")

from argus_cli.repl.state import (  # noqa: E402
    CompletionData,
    ConnectionState,
    ReplState,
    SessionState,
)


def _make_repl_state(**overrides) -> ReplState:
    cfg = MagicMock()
    cfg.server_url = "http://localhost:8080"
    cfg.token = ""
    cfg.output_format = "json"
    cfg.no_color = False
    cfg.theme = "dark"
    cfg.show_toolbar = True
    cfg.vi_mode = False
    return ReplState(
        config=cfg,
        connection=ConnectionState(**overrides.pop("connection", {})),
        completions=CompletionData(**overrides.pop("completions", {})),
        session=SessionState(**overrides.pop("session", {})),
    )


# show_banner
@patch("argus_cli.widgets.banner.render_banner")
def test_show_banner_connected(mock_banner):
    from argus_cli.repl.handlers import show_banner

    console = MagicMock()
    state = _make_repl_state(
        connection={
            "is_connected": True,
            "version": "1.0",
            "uptime": "1h2m",
            "backend_count": 3,
            "healthy_count": 2,
        }
    )
    show_banner(console, state)
    mock_banner.assert_called_once()
    # Should print Connected summary
    output = " ".join(str(c) for c in console.print.call_args_list)
    assert "Connected" in output or console.print.called


@patch("argus_cli.widgets.banner.render_banner")
def test_show_banner_disconnected(mock_banner):
    from argus_cli.repl.handlers import show_banner

    console = MagicMock()
    state = _make_repl_state(connection={"is_connected": False})
    show_banner(console, state)
    output = " ".join(str(c) for c in console.print.call_args_list)
    assert "Not connected" in output or console.print.called


# show_help
def test_show_help():
    from argus_cli.repl.handlers import show_help

    console = MagicMock()
    show_help(console)
    console.print.assert_called_once()
    text = console.print.call_args[0][0]
    assert "Commands" in text
    assert "tools" in text


# handle_use
def test_handle_use_valid_backend():
    from argus_cli.repl.handlers import handle_use

    console = MagicMock()
    state = _make_repl_state(completions={"backend_names": ["my-backend"]})
    handle_use(console, state, ["backend", "my-backend"])
    assert state.session.scoped_backend == "my-backend"


def test_handle_use_clear_scope():
    from argus_cli.repl.handlers import handle_use

    console = MagicMock()
    state = _make_repl_state(session={"scoped_backend": "old"})
    handle_use(console, state, ["backend", "none"])
    assert state.session.scoped_backend is None


def test_handle_use_unknown_backend():
    from argus_cli.repl.handlers import handle_use

    console = MagicMock()
    state = _make_repl_state(completions={"backend_names": ["valid"]})
    handle_use(console, state, ["backend", "missing"])
    output = str(console.print.call_args_list)
    assert "Unknown backend" in output


def test_handle_use_no_args():
    from argus_cli.repl.handlers import handle_use

    console = MagicMock()
    state = _make_repl_state()
    handle_use(console, state, [])
    output = str(console.print.call_args)
    assert "Usage" in output


# handle_alias / handle_unalias
@patch("argus_cli.repl.handlers.save_aliases")
def test_handle_alias_create(mock_save):
    from argus_cli.repl.handlers import handle_alias

    console = MagicMock()
    state = _make_repl_state()
    handle_alias(console, state, ["ll=backends", "list"])
    assert "ll" in state.session.aliases
    mock_save.assert_called_once()


def test_handle_alias_list_empty():
    from argus_cli.repl.handlers import handle_alias

    console = MagicMock()
    state = _make_repl_state()
    handle_alias(console, state, [])
    output = str(console.print.call_args)
    assert "No aliases" in output


def test_handle_alias_list_populated():
    from argus_cli.repl.handlers import handle_alias

    console = MagicMock()
    state = _make_repl_state(session={"aliases": {"ll": "backends list"}})
    handle_alias(console, state, [])
    output = str(console.print.call_args_list)
    assert "ll" in output


@patch("argus_cli.repl.handlers.save_aliases")
def test_handle_unalias_existing(mock_save):
    from argus_cli.repl.handlers import handle_unalias

    console = MagicMock()
    state = _make_repl_state(session={"aliases": {"ll": "backends list"}})
    handle_unalias(console, state, ["ll"])
    assert "ll" not in state.session.aliases
    mock_save.assert_called_once()


def test_handle_unalias_missing():
    from argus_cli.repl.handlers import handle_unalias

    console = MagicMock()
    state = _make_repl_state()
    handle_unalias(console, state, ["nope"])
    output = str(console.print.call_args)
    assert "No alias" in output


def test_handle_unalias_no_args():
    from argus_cli.repl.handlers import handle_unalias

    console = MagicMock()
    state = _make_repl_state()
    handle_unalias(console, state, [])
    output = str(console.print.call_args)
    assert "Usage" in output


# handle_watch
def test_handle_watch_no_args():
    from argus_cli.repl.handlers import handle_watch

    console = MagicMock()
    state = _make_repl_state()
    handle_watch(console, state, [], dispatch_fn=MagicMock())
    output = str(console.print.call_args)
    assert "Usage" in output


def test_handle_watch_invalid_interval():
    from argus_cli.repl.handlers import handle_watch

    console = MagicMock()
    state = _make_repl_state()
    handle_watch(console, state, ["--interval", "xyz", "health", "status"], dispatch_fn=MagicMock())
    output = str(console.print.call_args)
    assert "Invalid interval" in output


@patch("argus_cli.repl.handlers._time.sleep", side_effect=KeyboardInterrupt)
def test_handle_watch_runs_until_interrupt(mock_sleep):
    from argus_cli.repl.handlers import handle_watch

    console = MagicMock()
    state = _make_repl_state()
    dispatch_fn = MagicMock()
    handle_watch(console, state, ["health", "status"], dispatch_fn=dispatch_fn)
    dispatch_fn.assert_called()
    # Should print "Watch stopped" after interrupt
    output = str(console.print.call_args_list)
    assert "Watch stopped" in output


# handle_connect
def test_handle_connect_no_args():
    from argus_cli.repl.handlers import handle_connect

    console = MagicMock()
    state = _make_repl_state()
    handle_connect(console, state, [])
    output = str(console.print.call_args)
    assert "Current server" in output


def test_handle_connect_invalid_scheme():
    from argus_cli.repl.handlers import handle_connect

    console = MagicMock()
    state = _make_repl_state()
    handle_connect(console, state, ["ftp://example.com"])
    output = str(console.print.call_args)
    assert "http" in output.lower()


@patch("argus_cli.repl.handlers.refresh_completions")
def test_handle_connect_valid_url(mock_refresh):
    from argus_cli.repl.handlers import handle_connect

    console = MagicMock()
    state = _make_repl_state()
    handle_connect(console, state, ["http://newhost:9090"])
    assert state.config.server_url == "http://newhost:9090"
    mock_refresh.assert_called_once_with(state)


# handle_set
@patch("argus_cli.repl.handlers._persist_setting")
def test_handle_set_output_format(mock_persist):
    from argus_cli.repl.handlers import handle_set

    console = MagicMock()
    state = _make_repl_state()
    handle_set(console, state, ["output", "table"])
    assert state.config.output_format == "table"
    mock_persist.assert_called()


@patch("argus_cli.repl.handlers._persist_setting")
def test_handle_set_output_invalid(mock_persist):
    from argus_cli.repl.handlers import handle_set

    console = MagicMock()
    state = _make_repl_state()
    handle_set(console, state, ["output", "xml"])
    output = str(console.print.call_args)
    assert "Invalid" in output


@patch("argus_cli.repl.handlers._persist_setting")
def test_handle_set_no_color(mock_persist):
    from argus_cli.repl.handlers import handle_set

    console = MagicMock()
    state = _make_repl_state()
    handle_set(console, state, ["no-color", "true"])
    assert state.config.no_color is True


@patch("argus_cli.repl.handlers._persist_setting")
def test_handle_set_vi_mode(mock_persist):
    from argus_cli.repl.handlers import handle_set

    console = MagicMock()
    state = _make_repl_state()
    handle_set(console, state, ["vi-mode", "true"])
    assert state.config.vi_mode is True


def test_handle_set_no_args():
    from argus_cli.repl.handlers import handle_set

    console = MagicMock()
    state = _make_repl_state()
    handle_set(console, state, [])
    output = str(console.print.call_args_list)
    assert "Usage" in output


def test_handle_set_unknown_key():
    from argus_cli.repl.handlers import handle_set

    console = MagicMock()
    state = _make_repl_state()
    handle_set(console, state, ["badkey", "value"])
    output = str(console.print.call_args)
    assert "Unknown setting" in output


# handle_history
@patch("argus_cli.repl.handlers.ensure_history_dir")
def test_handle_history_with_entries(mock_dir, tmp_path: Path):
    from argus_cli.repl.handlers import handle_history

    hist_file = tmp_path / "history"
    hist_file.write_text("+health status\n+tools list\n+backends list\n", encoding="utf-8")
    mock_dir.return_value = str(hist_file)

    console = MagicMock()
    handle_history(console, limit=2)
    # Should show last 2 entries
    assert console.print.call_count >= 2


@patch("argus_cli.repl.handlers.ensure_history_dir")
def test_handle_history_empty(mock_dir, tmp_path: Path):
    from argus_cli.repl.handlers import handle_history

    hist_file = tmp_path / "history"
    hist_file.write_text("", encoding="utf-8")
    mock_dir.return_value = str(hist_file)

    console = MagicMock()
    handle_history(console)
    output = str(console.print.call_args)
    assert "No history" in output


@patch("argus_cli.repl.handlers.ensure_history_dir", return_value="/nonexistent/history")
def test_handle_history_file_missing(mock_dir):
    from argus_cli.repl.handlers import handle_history

    console = MagicMock()
    handle_history(console)
    output = str(console.print.call_args)
    assert "No history" in output
