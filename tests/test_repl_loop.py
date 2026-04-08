"""Tests for argus_cli.repl.loop — REPL main loop and key bindings."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("argus_cli", reason="argus_cli package not installed")

from argus_cli.repl.loop import _REPL_HANDLERS, _build_key_bindings, start_repl  # noqa: E402
from argus_cli.repl.state import ReplState  # noqa: E402


def _make_config():
    cfg = MagicMock()
    cfg.server_url = "http://localhost:8080"
    cfg.no_color = True
    cfg.show_toolbar = False
    cfg.vi_mode = False
    cfg.poll_interval = 2.0
    cfg.history_limit = 100
    return cfg


def _make_state():
    return ReplState(config=_make_config())


# _build_key_bindings
class TestBuildKeyBindings:
    def test_returns_key_bindings(self):
        """_build_key_bindings returns a KeyBindings object."""
        from prompt_toolkit.key_binding import KeyBindings

        state = _make_state()
        kb = _build_key_bindings(state)
        assert isinstance(kb, KeyBindings)
        # Should have at least 2 bindings (Ctrl-R and Ctrl-L)
        assert len(kb.bindings) >= 2

    @patch("argus_cli.repl.loop.refresh_completions")
    def test_ctrl_r_calls_refresh(self, mock_refresh):
        """Ctrl-R key binding invokes refresh_completions."""
        state = _make_state()
        kb = _build_key_bindings(state)
        # Find the ctrl-r binding and invoke its handler
        for binding in kb.bindings:
            if any(k.value == "c-r" for k in binding.keys):
                binding.handler(MagicMock())
                mock_refresh.assert_called_once_with(state)
                return
        pytest.fail("Ctrl-R binding not found")

    def test_ctrl_l_calls_clear(self):
        """Ctrl-L key binding invokes app.renderer.clear()."""
        state = _make_state()
        kb = _build_key_bindings(state)
        for binding in kb.bindings:
            if any(k.value == "c-l" for k in binding.keys):
                mock_event = MagicMock()
                binding.handler(mock_event)
                mock_event.app.renderer.clear.assert_called_once()
                return
        pytest.fail("Ctrl-L binding not found")


# _REPL_HANDLERS dispatch table
class TestReplHandlers:
    def test_clear_handler(self):
        console = MagicMock()
        _REPL_HANDLERS["clear"](console, MagicMock(), [])
        console.clear.assert_called_once()

    @patch("argus_cli.repl.loop.show_help")
    def test_help_handler(self, mock_help):
        console = MagicMock()
        _REPL_HANDLERS["help"](console, MagicMock(), [])
        mock_help.assert_called_once_with(console)

    @patch("argus_cli.repl.loop.handle_history")
    def test_history_handler(self, mock_history):
        console = MagicMock()
        state = _make_state()
        _REPL_HANDLERS["history"](console, state, [])
        mock_history.assert_called_once_with(console, limit=100)

    @patch("argus_cli.repl.loop.handle_use")
    def test_use_handler(self, mock_use):
        console = MagicMock()
        state = _make_state()
        args = ["some-backend"]
        _REPL_HANDLERS["use"](console, state, args)
        mock_use.assert_called_once_with(console, state, args)

    @patch("argus_cli.repl.loop.handle_alias")
    def test_alias_handler(self, mock_alias):
        console = MagicMock()
        state = _make_state()
        args = ["ll", "tools list"]
        _REPL_HANDLERS["alias"](console, state, args)
        mock_alias.assert_called_once_with(console, state, args)

    @patch("argus_cli.repl.loop.handle_unalias")
    def test_unalias_handler(self, mock_unalias):
        console = MagicMock()
        state = _make_state()
        args = ["ll"]
        _REPL_HANDLERS["unalias"](console, state, args)
        mock_unalias.assert_called_once_with(console, state, args)

    @patch("argus_cli.repl.loop.handle_watch")
    def test_watch_handler(self, mock_watch):
        console = MagicMock()
        state = _make_state()
        args = ["2", "health status"]
        _REPL_HANDLERS["watch"](console, state, args)
        mock_watch.assert_called_once()

    @patch("argus_cli.repl.loop.handle_connect")
    def test_connect_handler(self, mock_connect):
        console = MagicMock()
        state = _make_state()
        args = ["http://new:8080"]
        _REPL_HANDLERS["connect"](console, state, args)
        mock_connect.assert_called_once_with(console, state, args)

    @patch("argus_cli.repl.loop.handle_set")
    def test_set_handler(self, mock_set):
        console = MagicMock()
        state = _make_state()
        args = ["output_format", "json"]
        _REPL_HANDLERS["set"](console, state, args)
        mock_set.assert_called_once_with(console, state, args)


# start_repl
class TestStartRepl:
    @patch("argus_cli.repl.loop.PromptSession")
    @patch("argus_cli.repl.loop.refresh_completions")
    @patch("argus_cli.repl.loop.show_banner")
    @patch("argus_cli.repl.loop.load_aliases", return_value={})
    @patch("argus_cli.repl.loop.ensure_history_dir", return_value="/tmp/history")
    @patch("argus_cli.repl.loop.build_command_tree", return_value={})
    @patch("argus_cli.repl.loop.get_console")
    def test_eof_exits_repl(
        self,
        mock_gc,
        mock_tree,
        mock_hist,
        mock_aliases,
        mock_banner,
        mock_refresh,
        mock_session_cls,
    ):
        """EOFError (Ctrl-D) triggers graceful exit."""
        mock_console = MagicMock()
        mock_gc.return_value = mock_console
        mock_session = MagicMock()
        mock_session.prompt.side_effect = EOFError()
        mock_session_cls.return_value = mock_session

        cfg = _make_config()
        start_repl(cfg)

        mock_console.print.assert_called_with("[muted]Goodbye.[/]")

    @patch("argus_cli.repl.loop.PromptSession")
    @patch("argus_cli.repl.loop.refresh_completions")
    @patch("argus_cli.repl.loop.show_banner")
    @patch("argus_cli.repl.loop.load_aliases", return_value={})
    @patch("argus_cli.repl.loop.ensure_history_dir", return_value="/tmp/history")
    @patch("argus_cli.repl.loop.build_command_tree", return_value={})
    @patch("argus_cli.repl.loop.get_console")
    def test_exit_command(
        self,
        mock_gc,
        mock_tree,
        mock_hist,
        mock_aliases,
        mock_banner,
        mock_refresh,
        mock_session_cls,
    ):
        """Typing 'exit' breaks the loop."""
        mock_console = MagicMock()
        mock_gc.return_value = mock_console
        mock_session = MagicMock()
        mock_session.prompt.side_effect = ["exit"]
        mock_session_cls.return_value = mock_session

        start_repl(_make_config())
        mock_console.print.assert_called_with("[muted]Goodbye.[/]")

    @patch("argus_cli.repl.loop.PromptSession")
    @patch("argus_cli.repl.loop.refresh_completions")
    @patch("argus_cli.repl.loop.show_banner")
    @patch("argus_cli.repl.loop.load_aliases", return_value={})
    @patch("argus_cli.repl.loop.ensure_history_dir", return_value="/tmp/history")
    @patch("argus_cli.repl.loop.build_command_tree", return_value={})
    @patch("argus_cli.repl.loop.get_console")
    def test_quit_command(
        self,
        mock_gc,
        mock_tree,
        mock_hist,
        mock_aliases,
        mock_banner,
        mock_refresh,
        mock_session_cls,
    ):
        """Typing 'quit' breaks the loop."""
        mock_console = MagicMock()
        mock_gc.return_value = mock_console
        mock_session = MagicMock()
        mock_session.prompt.side_effect = ["quit"]
        mock_session_cls.return_value = mock_session

        start_repl(_make_config())
        mock_console.print.assert_called_with("[muted]Goodbye.[/]")

    @patch("argus_cli.repl.loop.PromptSession")
    @patch("argus_cli.repl.loop.refresh_completions")
    @patch("argus_cli.repl.loop.show_banner")
    @patch("argus_cli.repl.loop.load_aliases", return_value={})
    @patch("argus_cli.repl.loop.ensure_history_dir", return_value="/tmp/history")
    @patch("argus_cli.repl.loop.build_command_tree", return_value={})
    @patch("argus_cli.repl.loop.get_console")
    def test_empty_input_continues(
        self,
        mock_gc,
        mock_tree,
        mock_hist,
        mock_aliases,
        mock_banner,
        mock_refresh,
        mock_session_cls,
    ):
        """Empty input is skipped."""
        mock_console = MagicMock()
        mock_gc.return_value = mock_console
        mock_session = MagicMock()
        mock_session.prompt.side_effect = ["", "  ", "exit"]
        mock_session_cls.return_value = mock_session

        start_repl(_make_config())

    @patch("argus_cli.repl.loop.PromptSession")
    @patch("argus_cli.repl.loop.refresh_completions")
    @patch("argus_cli.repl.loop.show_banner")
    @patch("argus_cli.repl.loop.load_aliases", return_value={})
    @patch("argus_cli.repl.loop.ensure_history_dir", return_value="/tmp/history")
    @patch("argus_cli.repl.loop.build_command_tree", return_value={})
    @patch("argus_cli.repl.loop.get_console")
    def test_keyboard_interrupt_continues(
        self,
        mock_gc,
        mock_tree,
        mock_hist,
        mock_aliases,
        mock_banner,
        mock_refresh,
        mock_session_cls,
    ):
        """KeyboardInterrupt at prompt continues the loop."""
        mock_console = MagicMock()
        mock_gc.return_value = mock_console
        mock_session = MagicMock()
        mock_session.prompt.side_effect = [KeyboardInterrupt(), "exit"]
        mock_session_cls.return_value = mock_session

        start_repl(_make_config())

    @patch("argus_cli.repl.loop.dispatch_command")
    @patch("argus_cli.repl.loop.PromptSession")
    @patch("argus_cli.repl.loop.refresh_completions")
    @patch("argus_cli.repl.loop.show_banner")
    @patch("argus_cli.repl.loop.load_aliases", return_value={})
    @patch("argus_cli.repl.loop.ensure_history_dir", return_value="/tmp/history")
    @patch("argus_cli.repl.loop.build_command_tree", return_value={})
    @patch("argus_cli.repl.loop.get_console")
    def test_dispatch_to_typer(
        self,
        mock_gc,
        mock_tree,
        mock_hist,
        mock_aliases,
        mock_banner,
        mock_refresh,
        mock_session_cls,
        mock_dispatch,
    ):
        """Non-REPL commands dispatch to Typer."""
        mock_console = MagicMock()
        mock_gc.return_value = mock_console
        mock_session = MagicMock()
        mock_session.prompt.side_effect = ["tools list", "exit"]
        mock_session_cls.return_value = mock_session

        start_repl(_make_config())
        mock_dispatch.assert_called_once()

    @patch("argus_cli.repl.loop.dispatch_command")
    @patch("argus_cli.repl.loop.PromptSession")
    @patch("argus_cli.repl.loop.refresh_completions")
    @patch("argus_cli.repl.loop.show_banner")
    @patch("argus_cli.repl.loop.load_aliases", return_value={})
    @patch("argus_cli.repl.loop.ensure_history_dir", return_value="/tmp/history")
    @patch("argus_cli.repl.loop.build_command_tree", return_value={})
    @patch("argus_cli.repl.loop.get_console")
    def test_alias_expansion(
        self,
        mock_gc,
        mock_tree,
        mock_hist,
        mock_aliases,
        mock_banner,
        mock_refresh,
        mock_session_cls,
        mock_dispatch,
    ):
        """Aliases expand in the first word."""
        mock_console = MagicMock()
        mock_gc.return_value = mock_console
        mock_session = MagicMock()
        mock_session.prompt.side_effect = ["tl", "exit"]
        mock_session_cls.return_value = mock_session

        cfg = _make_config()
        with patch("argus_cli.repl.loop.load_aliases", return_value={"tl": "tools list"}):
            start_repl(cfg)

        # "tl" should be expanded to "tools list" and dispatched
        mock_dispatch.assert_called_once()
        dispatched_text = mock_dispatch.call_args[0][2]
        assert dispatched_text.startswith("tools list")

    @patch("argus_cli.repl.loop.dispatch_command")
    @patch("argus_cli.repl.loop.PromptSession")
    @patch("argus_cli.repl.loop.refresh_completions")
    @patch("argus_cli.repl.loop.show_banner")
    @patch("argus_cli.repl.loop.load_aliases", return_value={})
    @patch("argus_cli.repl.loop.ensure_history_dir", return_value="/tmp/history")
    @patch("argus_cli.repl.loop.build_command_tree", return_value={})
    @patch("argus_cli.repl.loop.get_console")
    def test_last_result_substitution_string(
        self,
        mock_gc,
        mock_tree,
        mock_hist,
        mock_aliases,
        mock_banner,
        mock_refresh,
        mock_session_cls,
        mock_dispatch,
    ):
        """$_ is replaced with last_result when it's a string."""
        mock_console = MagicMock()
        mock_gc.return_value = mock_console
        mock_session = MagicMock()
        mock_session.prompt.side_effect = ["echo $_", "exit"]
        mock_session_cls.return_value = mock_session

        cfg = _make_config()
        # We need to intercept state creation to set last_result
        original_repl_state = ReplState

        def patched_repl_state(config):
            s = original_repl_state(config=config)
            s.session.last_result = "previous-value"
            return s

        with patch("argus_cli.repl.loop.ReplState", side_effect=patched_repl_state):
            start_repl(cfg)

        # The dispatched command should have $_ replaced
        dispatched_text = mock_dispatch.call_args[0][2]
        assert "previous-value" in dispatched_text

    @patch("argus_cli.repl.loop.dispatch_command")
    @patch("argus_cli.repl.loop.PromptSession")
    @patch("argus_cli.repl.loop.refresh_completions")
    @patch("argus_cli.repl.loop.show_banner")
    @patch("argus_cli.repl.loop.load_aliases", return_value={})
    @patch("argus_cli.repl.loop.ensure_history_dir", return_value="/tmp/history")
    @patch("argus_cli.repl.loop.build_command_tree", return_value={})
    @patch("argus_cli.repl.loop.get_console")
    def test_last_result_substitution_dict(
        self,
        mock_gc,
        mock_tree,
        mock_hist,
        mock_aliases,
        mock_banner,
        mock_refresh,
        mock_session_cls,
        mock_dispatch,
    ):
        """$_ is replaced with JSON when last_result is a dict."""
        mock_console = MagicMock()
        mock_gc.return_value = mock_console
        mock_session = MagicMock()
        mock_session.prompt.side_effect = ["echo $_", "exit"]
        mock_session_cls.return_value = mock_session

        original_repl_state = ReplState

        def patched_repl_state(config):
            s = original_repl_state(config=config)
            s.session.last_result = {"key": "val"}
            return s

        with patch("argus_cli.repl.loop.ReplState", side_effect=patched_repl_state):
            start_repl(_make_config())

        dispatched_text = mock_dispatch.call_args[0][2]
        assert '"key"' in dispatched_text

    @patch("argus_cli.repl.loop.collect_multiline", return_value="tools list --all")
    @patch("argus_cli.repl.loop.dispatch_command")
    @patch("argus_cli.repl.loop.PromptSession")
    @patch("argus_cli.repl.loop.refresh_completions")
    @patch("argus_cli.repl.loop.show_banner")
    @patch("argus_cli.repl.loop.load_aliases", return_value={})
    @patch("argus_cli.repl.loop.ensure_history_dir", return_value="/tmp/history")
    @patch("argus_cli.repl.loop.build_command_tree", return_value={})
    @patch("argus_cli.repl.loop.get_console")
    def test_multiline_continuation(
        self,
        mock_gc,
        mock_tree,
        mock_hist,
        mock_aliases,
        mock_banner,
        mock_refresh,
        mock_session_cls,
        mock_dispatch,
        mock_collect,
    ):
        """Backslash continuation triggers collect_multiline."""
        mock_console = MagicMock()
        mock_gc.return_value = mock_console
        mock_session = MagicMock()
        mock_session.prompt.side_effect = ["tools \\", "exit"]
        mock_session_cls.return_value = mock_session

        start_repl(_make_config())
        mock_collect.assert_called_once()

    @patch("argus_cli.repl.loop.PromptSession")
    @patch("argus_cli.repl.loop.refresh_completions")
    @patch("argus_cli.repl.loop.show_banner")
    @patch("argus_cli.repl.loop.load_aliases", return_value={})
    @patch("argus_cli.repl.loop.ensure_history_dir", return_value="/tmp/history")
    @patch("argus_cli.repl.loop.build_command_tree", return_value={})
    @patch("argus_cli.repl.loop.get_console")
    def test_parse_error_continues(
        self,
        mock_gc,
        mock_tree,
        mock_hist,
        mock_aliases,
        mock_banner,
        mock_refresh,
        mock_session_cls,
    ):
        """shlex parse error prints error and continues."""
        mock_console = MagicMock()
        mock_gc.return_value = mock_console
        mock_session = MagicMock()
        mock_session.prompt.side_effect = ["'unterminated", "exit"]
        mock_session_cls.return_value = mock_session

        start_repl(_make_config())
        # Should have printed a parse error
        error_calls = [c for c in mock_console.print.call_args_list if "Parse error" in str(c)]
        assert len(error_calls) >= 1

    @patch("argus_cli.repl.loop.show_help")
    @patch("argus_cli.repl.loop.PromptSession")
    @patch("argus_cli.repl.loop.refresh_completions")
    @patch("argus_cli.repl.loop.show_banner")
    @patch("argus_cli.repl.loop.load_aliases", return_value={})
    @patch("argus_cli.repl.loop.ensure_history_dir", return_value="/tmp/history")
    @patch("argus_cli.repl.loop.build_command_tree", return_value={})
    @patch("argus_cli.repl.loop.get_console")
    def test_repl_handler_dispatched(
        self,
        mock_gc,
        mock_tree,
        mock_hist,
        mock_aliases,
        mock_banner,
        mock_refresh,
        mock_session_cls,
        mock_show_help,
    ):
        """Built-in REPL commands are dispatched via _REPL_HANDLERS."""
        mock_console = MagicMock()
        mock_gc.return_value = mock_console
        mock_session = MagicMock()
        mock_session.prompt.side_effect = ["help", "exit"]
        mock_session_cls.return_value = mock_session

        start_repl(_make_config())
        mock_show_help.assert_called_once()

    @patch("argus_cli.repl.loop.handle_connect")
    @patch("argus_cli.repl.loop.PromptSession")
    @patch("argus_cli.repl.loop.refresh_completions")
    @patch("argus_cli.repl.loop.show_banner")
    @patch("argus_cli.repl.loop.load_aliases", return_value={})
    @patch("argus_cli.repl.loop.ensure_history_dir", return_value="/tmp/history")
    @patch("argus_cli.repl.loop.build_command_tree", return_value={})
    @patch("argus_cli.repl.loop.get_console")
    def test_connect_refreshes_completer(
        self,
        mock_gc,
        mock_tree,
        mock_hist,
        mock_aliases,
        mock_banner,
        mock_refresh,
        mock_session_cls,
        mock_connect,
    ):
        """After 'connect', the completer is rebuilt."""
        mock_console = MagicMock()
        mock_gc.return_value = mock_console
        mock_session = MagicMock()
        mock_session.prompt.side_effect = ["connect http://new:8080", "exit"]
        mock_session_cls.return_value = mock_session

        start_repl(_make_config())
        # build_command_tree called at init + after connect
        assert mock_tree.call_count >= 2

    @patch("argus_cli.repl.loop.dispatch_command")
    @patch("argus_cli.repl.loop.PromptSession")
    @patch("argus_cli.repl.loop.refresh_completions")
    @patch("argus_cli.repl.loop.show_banner")
    @patch("argus_cli.repl.loop.load_aliases", return_value={})
    @patch("argus_cli.repl.loop.ensure_history_dir", return_value="/tmp/history")
    @patch("argus_cli.repl.loop.build_command_tree", return_value={})
    @patch("argus_cli.repl.loop.get_console")
    def test_state_mutating_cmd_refreshes(
        self,
        mock_gc,
        mock_tree,
        mock_hist,
        mock_aliases,
        mock_banner,
        mock_refresh,
        mock_session_cls,
        mock_dispatch,
    ):
        """State-mutating commands (config, backends, etc.) refresh completions."""
        mock_console = MagicMock()
        mock_gc.return_value = mock_console
        mock_session = MagicMock()
        mock_session.prompt.side_effect = ["config show", "exit"]
        mock_session_cls.return_value = mock_session

        start_repl(_make_config())
        # refresh_completions: once at init + once after 'config' command
        assert mock_refresh.call_count >= 2

    @patch("argus_cli.repl.loop.PromptSession")
    @patch("argus_cli.repl.loop.refresh_completions")
    @patch("argus_cli.repl.loop.show_banner")
    @patch("argus_cli.repl.loop.load_aliases", return_value={})
    @patch("argus_cli.repl.loop.ensure_history_dir", return_value="/tmp/history")
    @patch("argus_cli.repl.loop.build_command_tree", return_value={})
    @patch("argus_cli.repl.loop.make_toolbar")
    @patch("argus_cli.repl.loop.get_console")
    def test_toolbar_enabled(
        self,
        mock_gc,
        mock_toolbar,
        mock_tree,
        mock_hist,
        mock_aliases,
        mock_banner,
        mock_refresh,
        mock_session_cls,
    ):
        """When show_toolbar=True, make_toolbar is called."""
        mock_console = MagicMock()
        mock_gc.return_value = mock_console
        mock_session = MagicMock()
        mock_session.prompt.side_effect = ["exit"]
        mock_session_cls.return_value = mock_session
        mock_toolbar.return_value = MagicMock()

        cfg = _make_config()
        cfg.show_toolbar = True
        start_repl(cfg)
        mock_toolbar.assert_called()
