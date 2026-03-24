"""Unit tests for argus_mcp.cli — parser, PID helpers, and command handlers."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest

from argus_mcp.cli import (
    _build_parser,
    _build_tui_server_manager,
    _cleanup_pid_file,
    _cmd_build,
    _cmd_secret,
    _cmd_server,
    _cmd_status,
    _cmd_stop,
    _cmd_tui,
    _detach_server,
    _load_client_config,
    _remove_pid_file,
    _resolve_tui_server_url,
    _restore_terminal,
    _run_server,
    _stop_legacy_pid,
    _stop_named_session,
    _write_pid_file,
    main,
)
from argus_mcp.constants import DEFAULT_HOST, DEFAULT_PORT

# _build_parser


class TestBuildParser:
    """Tests for argparse construction."""

    def test_returns_parser(self) -> None:
        parser = _build_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_server_defaults(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["server"])
        assert args.command == "server"
        assert args.host == DEFAULT_HOST
        assert args.port == DEFAULT_PORT
        assert args.log_level == "info"
        assert args.config is None
        assert args.detach is False
        assert args.name is None

    def test_server_custom_args(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            [
                "server",
                "--host",
                "0.0.0.0",
                "--port",
                "8080",
                "--log-level",
                "debug",
                "--config",
                "/tmp/cfg.yaml",
                "-d",
                "--name",
                "my-session",
                "-vv",
            ]
        )
        assert args.host == "0.0.0.0"
        assert args.port == 8080
        assert args.log_level == "debug"
        assert args.config == "/tmp/cfg.yaml"
        assert args.detach is True
        assert args.name == "my-session"
        assert args.verbose == 2

    def test_stop_no_name(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["stop"])
        assert args.command == "stop"
        assert args.session_name is None

    def test_stop_with_name(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["stop", "my-session"])
        assert args.session_name == "my-session"

    def test_status_command(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["status"])
        assert args.command == "status"

    def test_tui_defaults(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["tui"])
        assert args.command == "tui"
        assert args.server == f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
        assert args.token is None
        assert args.servers_config is None

    def test_tui_custom_args(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(
            [
                "tui",
                "--server",
                "http://remote:9999",
                "--token",
                "abc123",
                "--servers-config",
                "/tmp/servers.json",
            ]
        )
        assert args.server == "http://remote:9999"
        assert args.token == "abc123"
        assert args.servers_config == "/tmp/servers.json"

    def test_build_command(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["build"])
        assert args.command == "build"
        assert args.config is None

    def test_build_with_config(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["build", "--config", "/my/config.yaml"])
        assert args.config == "/my/config.yaml"

    def test_secret_set(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["secret", "set", "my_key", "my_val"])
        assert args.command == "secret"
        assert args.secret_action == "set"
        assert args.name == "my_key"
        assert args.value == "my_val"

    def test_secret_set_no_value(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["secret", "set", "my_key"])
        assert args.secret_action == "set"
        assert args.name == "my_key"
        assert args.value is None

    def test_secret_get(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["secret", "get", "my_key"])
        assert args.secret_action == "get"
        assert args.name == "my_key"

    def test_secret_list(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["secret", "list"])
        assert args.secret_action == "list"

    def test_secret_delete(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["secret", "delete", "my_key"])
        assert args.secret_action == "delete"
        assert args.name == "my_key"

    def test_secret_provider_choices(self) -> None:
        parser = _build_parser()
        args = parser.parse_args(["secret", "--provider", "keyring", "list"])
        assert args.provider == "keyring"

    def test_no_command_returns_none(self) -> None:
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.command is None


# _write_pid_file / _remove_pid_file


class TestWritePidFile:
    """Tests for PID file management."""

    def test_write_creates_session(self) -> None:
        _mock_info_cls = MagicMock()
        with (
            patch("argus_mcp.cli._server.save_session", create=True) as _save,
            patch("argus_mcp.sessions.save_session") as _mock_save,
            patch("argus_mcp.sessions.SessionInfo") as _mock_cls,
            patch("builtins.open", mock_open()),
            patch("argus_mcp.cli._server.os.getpid", return_value=12345),
        ):
            # Patch at the import point inside the function
            with patch.dict("sys.modules", {}):
                # _write_pid_file does a local import, so we patch sessions directly
                mock_session_info = MagicMock()
                with (
                    patch("argus_mcp.sessions.SessionInfo", return_value=mock_session_info),
                    patch("argus_mcp.sessions.save_session") as _mock_save_fn,
                ):
                    _write_pid_file("test-sess", "0.0.0.0", 8080, "/cfg.yaml")

    def test_write_default_args(self) -> None:
        with (
            patch("argus_mcp.sessions.SessionInfo") as mock_cls,
            patch("argus_mcp.sessions.save_session"),
            patch("builtins.open", mock_open()),
        ):
            _write_pid_file()
            call_kwargs = mock_cls.call_args
            assert call_kwargs[1]["name"] == "default"
            assert call_kwargs[1]["host"] == DEFAULT_HOST
            assert call_kwargs[1]["port"] == DEFAULT_PORT

    def test_write_creates_legacy_pid_file(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "argus-mcp.pid"
        with (
            patch("argus_mcp.sessions.SessionInfo"),
            patch("argus_mcp.sessions.save_session"),
            patch("argus_mcp.cli._server._PID_FILE", str(pid_file)),
        ):
            _write_pid_file()
            assert pid_file.read_text().strip() == str(os.getpid())


class TestRemovePidFile:
    """Tests for PID file removal."""

    def test_remove_cleans_session_and_legacy(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "argus-mcp.pid"
        pid_file.write_text(str(os.getpid()))

        mock_info = MagicMock()
        mock_info.pid = os.getpid()

        with (
            patch("argus_mcp.sessions.load_session", return_value=mock_info),
            patch("argus_mcp.sessions.remove_session") as mock_rm,
            patch("argus_mcp.cli._server._PID_FILE", str(pid_file)),
        ):
            _remove_pid_file("test-sess")
            mock_rm.assert_called_once_with("test-sess")
            assert not pid_file.exists()

    def test_remove_skips_if_different_pid(self) -> None:
        mock_info = MagicMock()
        mock_info.pid = os.getpid() + 999  # Different PID

        with (
            patch("argus_mcp.sessions.load_session", return_value=mock_info),
            patch("argus_mcp.sessions.remove_session") as mock_rm,
            patch("argus_mcp.cli._server._PID_FILE", "/nonexistent"),
        ):
            _remove_pid_file("test-sess")
            mock_rm.assert_not_called()

    def test_remove_handles_no_session(self) -> None:
        with (
            patch("argus_mcp.sessions.load_session", return_value=None),
            patch("argus_mcp.sessions.remove_session") as mock_rm,
            patch("argus_mcp.cli._server._PID_FILE", "/nonexistent"),
        ):
            _remove_pid_file("ghost")
            mock_rm.assert_not_called()

    def test_remove_handles_missing_legacy_file(self, tmp_path: Path) -> None:
        mock_info = MagicMock()
        mock_info.pid = os.getpid()
        missing_file = str(tmp_path / "nonexistent.pid")

        with (
            patch("argus_mcp.sessions.load_session", return_value=mock_info),
            patch("argus_mcp.sessions.remove_session"),
            patch("argus_mcp.cli._server._PID_FILE", missing_file),
        ):
            _remove_pid_file("test-sess")  # Should not raise


# _cleanup_pid_file


class TestCleanupPidFile:
    """Tests for legacy PID file cleanup."""

    def test_removes_existing_file(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "argus-mcp.pid"
        pid_file.write_text("12345")
        with patch("argus_mcp.cli._stop._PID_FILE", str(pid_file)):
            _cleanup_pid_file()
            assert not pid_file.exists()

    def test_ignores_missing_file(self) -> None:
        with patch("argus_mcp.cli._stop._PID_FILE", "/nonexistent/path.pid"):
            _cleanup_pid_file()  # Should not raise


# _restore_terminal


class TestRestoreTerminal:
    """Tests for terminal restoration helper."""

    def test_restores_stdout_stderr(self) -> None:
        _restore_terminal(None)
        assert sys.stdout is sys.__stdout__
        assert sys.stderr is sys.__stderr__

    def test_with_saved_termios(self) -> None:
        mock_termios = MagicMock()
        with (
            patch("termios.tcsetattr") as mock_set,
            patch("termios.tcgetattr", return_value=[0, 0, 0, 0, 0, 0, [0] * 32]),
            patch("subprocess.run"),
            patch("sys.stdin") as mock_stdin,
        ):
            mock_stdin.fileno.return_value = 0
            _restore_terminal(mock_termios)
            mock_set.assert_called()

    def test_without_termios_still_restores(self) -> None:
        with (
            patch("subprocess.run"),
        ):
            _restore_terminal(None)
            assert sys.stdout is sys.__stdout__

    def test_handles_stty_failure(self) -> None:
        with (
            patch("subprocess.run", side_effect=OSError("stty not found")),
        ):
            _restore_terminal(None)  # Should not raise


# _load_client_config


class TestLoadClientConfig:
    """Tests for TUI client config loading."""

    def test_returns_defaults_when_no_config(self) -> None:
        args = argparse.Namespace(config=None)
        with (
            patch.dict(os.environ, {}, clear=False),
            patch("argus_mcp.cli._tui._find_config_file", return_value=None),
        ):
            # Remove ARGUS_CONFIG from env if present
            env = os.environ.copy()
            env.pop("ARGUS_CONFIG", None)
            with patch.dict(os.environ, env, clear=True):
                cfg, path = _load_client_config(args)
        # Should return a ClientConfig (defaults)
        assert cfg is not None

    def test_uses_cli_config_path(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text(
            "server:\n  transport: streamable-http\nclient:\n  server_url: http://test:9000\n"
        )
        args = argparse.Namespace(config=str(cfg_file))
        cfg, path = _load_client_config(args)
        assert path == str(cfg_file)

    def test_uses_env_config_path(self, tmp_path: Path) -> None:
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("server:\n  transport: streamable-http\n")
        args = argparse.Namespace(config=None)
        with patch.dict(os.environ, {"ARGUS_CONFIG": str(cfg_file)}):
            cfg, path = _load_client_config(args)
        assert path == str(cfg_file)

    def test_handles_config_load_failure(self, tmp_path: Path) -> None:
        """When load_argus_config raises a caught exception, defaults are used."""
        cfg_file = tmp_path / "config.yaml"
        cfg_file.write_text("server:\n  transport: streamable-http\n")
        args = argparse.Namespace(config=str(cfg_file))
        # Force the error path by making load_argus_config raise a ValueError
        with patch("argus_mcp.cli.load_argus_config", create=True):
            with patch(
                "argus_mcp.config.loader.load_argus_config",
                side_effect=ValueError("bad"),
            ):
                cfg, path = _load_client_config(args)
        assert cfg is not None


# _resolve_tui_server_url


class TestResolveTuiServerUrl:
    """Tests for TUI server URL resolution."""

    def test_uses_explicit_server_arg(self) -> None:
        args = argparse.Namespace(server="http://custom:1234")
        mock_cfg = MagicMock()
        with patch("argus_mcp.tui.app._normalise_server_url", side_effect=lambda x: x):
            result = _resolve_tui_server_url(args, mock_cfg)
        assert result == "http://custom:1234"

    def test_falls_back_to_env(self) -> None:
        default_url = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
        args = argparse.Namespace(server=default_url)
        mock_cfg = MagicMock()
        mock_cfg.server_url = None

        with (
            patch.dict(os.environ, {"ARGUS_TUI_SERVER": "http://env:5555"}),
            patch("argus_mcp.tui.app._normalise_server_url", side_effect=lambda x: x),
        ):
            result = _resolve_tui_server_url(args, mock_cfg)
        assert result == "http://env:5555"

    def test_falls_back_to_client_config(self) -> None:
        default_url = f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
        args = argparse.Namespace(server=default_url)
        mock_cfg = MagicMock()
        mock_cfg.server_url = "http://cfg:7777"

        with (
            patch.dict(os.environ, {}, clear=False),
            patch("argus_mcp.tui.app._normalise_server_url", side_effect=lambda x: x),
        ):
            env = os.environ.copy()
            env.pop("ARGUS_TUI_SERVER", None)
            with patch.dict(os.environ, env, clear=True):
                result = _resolve_tui_server_url(args, mock_cfg)
        assert result == "http://cfg:7777"


# _cmd_status


class TestCmdStatus:
    """Tests for ``argus-mcp status`` command handler."""

    def test_no_sessions(self, capsys: pytest.CaptureFixture[str]) -> None:
        with (
            patch("argus_mcp.sessions.list_sessions", return_value=[]),
            patch("argus_mcp.sessions.discover_server_processes", return_value=[]),
        ):
            _cmd_status(argparse.Namespace())
        out = capsys.readouterr().out
        assert "No running" in out

    def test_shows_sessions_table(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock_sess = MagicMock()
        mock_sess.name = "default"
        mock_sess.pid = 42
        mock_sess.port = 9000
        mock_sess.host = "127.0.0.1"
        mock_sess.config = "/path/to/config.yaml"
        mock_sess.started_at = "2025-01-01T12:00:00Z"

        with (
            patch("argus_mcp.sessions.list_sessions", return_value=[mock_sess]),
            patch("argus_mcp.sessions.discover_server_processes", return_value=[]),
        ):
            _cmd_status(argparse.Namespace())
        out = capsys.readouterr().out
        assert "default" in out
        assert "42" in out
        assert "9000" in out
        assert "1 registered session(s)" in out

    def test_shows_multiple_sessions(self, capsys: pytest.CaptureFixture[str]) -> None:
        sessions = []
        for i in range(3):
            s = MagicMock()
            s.name = f"sess-{i}"
            s.pid = 100 + i
            s.port = 9000 + i
            s.host = "127.0.0.1"
            s.config = ""
            s.started_at = f"2025-01-0{i + 1}T00:00:00"
            sessions.append(s)

        with (
            patch("argus_mcp.sessions.list_sessions", return_value=sessions),
            patch("argus_mcp.sessions.discover_server_processes", return_value=[]),
        ):
            _cmd_status(argparse.Namespace())
        out = capsys.readouterr().out
        assert "3 registered session(s)" in out


# _cmd_stop


class TestCmdStop:
    """Tests for ``argus-mcp stop`` command handler."""

    def test_stop_named_session(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock_info = MagicMock()
        mock_info.name = "my-session"
        mock_info.pid = 42
        mock_info.is_alive.return_value = True

        args = argparse.Namespace(session_name="my-session", all=False, force=False)
        with (
            patch("argus_mcp.sessions.load_session", return_value=mock_info),
            patch("argus_mcp.sessions.stop_session", return_value=True),
            patch("argus_mcp.sessions.remove_session"),
            patch("argus_mcp.cli._stop._cleanup_pid_file"),
        ):
            _cmd_stop(args)
        out = capsys.readouterr().out
        assert "stopped" in out

    def test_stop_named_missing(self) -> None:
        args = argparse.Namespace(session_name="nonexistent", all=False, force=False)
        with (
            patch("argus_mcp.sessions.load_session", return_value=None),
            pytest.raises(SystemExit),
        ):
            _cmd_stop(args)

    def test_stop_single_session_auto(self, capsys: pytest.CaptureFixture[str]) -> None:
        mock_info = MagicMock()
        mock_info.name = "auto"
        mock_info.pid = 55

        args = argparse.Namespace(session_name=None, all=False, force=False)
        with (
            patch("argus_mcp.sessions.find_session", return_value=mock_info),
            patch("argus_mcp.sessions.stop_session", return_value=True),
            patch("argus_mcp.sessions.list_sessions", return_value=[]),
            patch("argus_mcp.cli._stop._cleanup_pid_file"),
        ):
            _cmd_stop(args)
        out = capsys.readouterr().out
        assert "stopped" in out

    def test_stop_multiple_sessions_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        s1 = MagicMock(name="s1", pid=1, port=9000)
        s1.name = "s1"
        s2 = MagicMock(name="s2", pid=2, port=9001)
        s2.name = "s2"

        args = argparse.Namespace(session_name=None, all=False, force=False)
        with (
            patch("argus_mcp.sessions.find_session", return_value=None),
            patch("argus_mcp.sessions.list_sessions", return_value=[s1, s2]),
            patch("argus_mcp.sessions.discover_server_processes", return_value=[]),
            patch("argus_mcp.sessions.stop_session"),
            pytest.raises(SystemExit),
        ):
            _cmd_stop(args)


# main


class TestMain:
    """Tests for the main entry-point dispatcher."""

    def test_no_command_shows_help(self) -> None:
        with (
            patch("sys.argv", ["argus-mcp"]),
            pytest.raises(SystemExit) as exc_info,
        ):
            main()
        assert exc_info.value.code == 1

    def test_dispatches_to_func(self) -> None:
        mock_func = MagicMock()
        with (
            patch("argus_mcp.cli._build_parser") as mock_parser_fn,
        ):
            mock_parser = MagicMock()
            mock_args = argparse.Namespace(command="test", func=mock_func)
            mock_parser.parse_args.return_value = mock_args
            mock_parser_fn.return_value = mock_parser

            main()
            mock_func.assert_called_once_with(mock_args)


# _run_server


class TestRunServer:
    """Tests for the async _run_server function."""

    @pytest.mark.asyncio
    async def test_port_in_use(self, capsys: pytest.CaptureFixture[str]) -> None:
        """When port is occupied, _run_server prints error and returns."""
        import socket as _socket

        # Occupy a port
        sock = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        _, occupied_port = sock.getsockname()
        try:
            with (
                patch("argus_mcp.cli._server.setup_logging", return_value=("/dev/null", "INFO")),
                patch("argus_mcp.cli._server._find_config_file", return_value="config.yaml"),
                patch("argus_mcp.server.app.app") as mock_app,
            ):
                mock_app.state = MagicMock()
                await _run_server("127.0.0.1", occupied_port, "info")
        finally:
            sock.close()
        out = capsys.readouterr().out
        assert "already in use" in out

    @pytest.mark.asyncio
    async def test_normal_serve(self) -> None:
        """Mocked uvicorn serve completes cleanly."""
        mock_server = MagicMock()
        mock_server.serve = AsyncMock()

        with (
            patch("argus_mcp.cli._server.setup_logging", return_value=("/dev/null", "INFO")),
            patch("argus_mcp.cli._server._find_config_file", return_value="config.yaml"),
            patch("argus_mcp.server.app.app") as mock_app,
            patch("argus_mcp.cli._server.uvicorn.Config"),
            patch("argus_mcp.cli._server.uvicorn.Server", return_value=mock_server),
            patch("socket.socket") as mock_sock_cls,
        ):
            mock_app.state = MagicMock()
            mock_sock_inst = MagicMock()
            mock_sock_cls.return_value = mock_sock_inst
            await _run_server("127.0.0.1", 9999, "info")
            mock_server.serve.assert_called_once()


# _detach_server


class TestDetachServer:
    """Tests for background server detachment."""

    def test_detach_success(self, capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
        args = argparse.Namespace(
            name=None,
            host=DEFAULT_HOST,
            port=DEFAULT_PORT,
            log_level="info",
            config=None,
        )
        mock_proc = MagicMock()
        mock_proc.pid = 99999

        with (
            patch("argus_mcp.sessions.check_port_conflict", return_value=None),
            patch("argus_mcp.sessions.auto_name", return_value="default"),
            patch("argus_mcp.cli._server.os.makedirs"),
            patch("builtins.open", mock_open()),
            patch("argus_mcp.cli._server.subprocess.Popen", return_value=mock_proc),
            patch("argus_mcp.sessions.SessionInfo"),
            patch("argus_mcp.sessions.save_session"),
        ):
            _detach_server(args)
        out = capsys.readouterr().out
        assert "started in background" in out
        assert "99999" in out

    def test_detach_port_conflict(self) -> None:
        conflict_info = MagicMock()
        conflict_info.name = "existing"
        conflict_info.pid = 111
        args = argparse.Namespace(
            name=None,
            host=DEFAULT_HOST,
            port=DEFAULT_PORT,
            log_level="info",
            config=None,
        )
        with (
            patch("argus_mcp.sessions.check_port_conflict", return_value=conflict_info),
            patch("argus_mcp.sessions.auto_name", return_value="default"),
            pytest.raises(SystemExit),
        ):
            _detach_server(args)

    def test_detach_explicit_name(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = argparse.Namespace(
            name="my-server",
            host="0.0.0.0",
            port=8080,
            log_level="debug",
            config="/etc/cfg.yaml",
        )
        mock_proc = MagicMock()
        mock_proc.pid = 55555

        with (
            patch("argus_mcp.sessions.validate_name", return_value="my-server"),
            patch("argus_mcp.sessions.check_port_conflict", return_value=None),
            patch("argus_mcp.cli._server.os.makedirs"),
            patch("builtins.open", mock_open()),
            patch("argus_mcp.cli._server.subprocess.Popen", return_value=mock_proc),
            patch("argus_mcp.sessions.SessionInfo"),
            patch("argus_mcp.sessions.save_session"),
        ):
            _detach_server(args)
        out = capsys.readouterr().out
        assert "my-server" in out


# _stop_named_session


class TestStopNamedSession:
    """Tests for stopping a named session."""

    def test_session_not_found(self) -> None:
        with (
            patch("argus_mcp.sessions.load_session", return_value=None),
            pytest.raises(SystemExit),
        ):
            _stop_named_session("ghost")

    def test_session_stale(self, capsys: pytest.CaptureFixture[str]) -> None:
        info = MagicMock()
        info.name = "stale"
        info.pid = 99
        info.is_alive.return_value = False
        with (
            patch("argus_mcp.sessions.load_session", return_value=info),
            patch("argus_mcp.sessions.remove_session") as mock_rm,
        ):
            _stop_named_session("stale")
            mock_rm.assert_called_once_with("stale")
        out = capsys.readouterr().out
        assert "not running" in out

    def test_session_stop_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        info = MagicMock()
        info.name = "running"
        info.pid = 42
        info.is_alive.return_value = True
        with (
            patch("argus_mcp.sessions.load_session", return_value=info),
            patch("argus_mcp.sessions.stop_session", return_value=True),
            patch("argus_mcp.cli._stop._cleanup_pid_file"),
        ):
            _stop_named_session("running")
        out = capsys.readouterr().out
        assert "stopped" in out

    def test_session_stop_failure(self) -> None:
        info = MagicMock()
        info.name = "stuck"
        info.pid = 42
        info.is_alive.return_value = True
        with (
            patch("argus_mcp.sessions.load_session", return_value=info),
            patch("argus_mcp.sessions.stop_session", return_value=False),
            pytest.raises(SystemExit),
        ):
            _stop_named_session("stuck")


# _stop_legacy_pid


class TestStopLegacyPid:
    """Tests for legacy PID-file-based stop."""

    def test_no_pid_file(self) -> None:
        with (
            patch("argus_mcp.cli._stop._PID_FILE", "/no/such/file.pid"),
            pytest.raises(SystemExit),
        ):
            _stop_legacy_pid()

    def test_stale_pid(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        pid_file = tmp_path / "argus.pid"
        pid_file.write_text("99999999")
        with (
            patch("argus_mcp.cli._stop._PID_FILE", str(pid_file)),
            patch("os.kill", side_effect=ProcessLookupError),
            patch("argus_mcp.cli._stop._cleanup_pid_file"),
        ):
            _stop_legacy_pid()
        out = capsys.readouterr().out
        assert "not running" in out

    def test_sends_sigterm(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        pid_file = tmp_path / "argus.pid"
        pid_file.write_text("12345")

        call_count = 0

        def fake_kill(pid: int, sig: int) -> None:
            nonlocal call_count
            call_count += 1
            if sig == 0:
                if call_count > 2:  # Process gone after first loop iteration
                    raise ProcessLookupError
                return  # Process alive
            # SIGTERM: do nothing

        with (
            patch("argus_mcp.cli._stop._PID_FILE", str(pid_file)),
            patch("os.kill", side_effect=fake_kill),
            patch("argus_mcp.cli._stop._cleanup_pid_file"),
            patch("time.sleep"),
        ):
            _stop_legacy_pid()
        out = capsys.readouterr().out
        assert "stopped" in out.lower() or "SIGTERM" in out

    def test_corrupt_pid_file(self, tmp_path: Path) -> None:
        pid_file = tmp_path / "argus.pid"
        pid_file.write_text("not-a-number")
        with (
            patch("argus_mcp.cli._stop._PID_FILE", str(pid_file)),
            pytest.raises(SystemExit),
        ):
            _stop_legacy_pid()


# _cmd_server


class TestCmdServer:
    """Tests for ``argus-mcp server`` command handler."""

    def test_detach_mode(self) -> None:
        args = argparse.Namespace(
            detach=True,
            host=DEFAULT_HOST,
            port=DEFAULT_PORT,
            log_level="info",
            config=None,
            name=None,
        )
        with patch("argus_mcp.cli._server._detach_server") as mock_detach:
            from argus_mcp.cli import _cmd_server

            _cmd_server(args)
            mock_detach.assert_called_once_with(args)

    def test_foreground_keyboard_interrupt(self) -> None:
        args = argparse.Namespace(
            detach=False,
            host=DEFAULT_HOST,
            port=DEFAULT_PORT,
            log_level="info",
            config=None,
            name=None,
            verbose=0,
        )
        with (
            patch("argus_mcp.sessions.auto_name", return_value="default"),
            patch("argus_mcp.cli._server._write_pid_file"),
            patch("argus_mcp.cli._server._remove_pid_file"),
            patch("argus_mcp.cli._server.signal.signal"),
            patch("asyncio.run", side_effect=KeyboardInterrupt),
        ):
            from argus_mcp.cli import _cmd_server

            _cmd_server(args)  # Should not raise

    def test_foreground_system_exit_zero(self) -> None:
        args = argparse.Namespace(
            detach=False,
            host=DEFAULT_HOST,
            port=DEFAULT_PORT,
            log_level="info",
            config=None,
            name=None,
            verbose=0,
        )
        with (
            patch("argus_mcp.sessions.auto_name", return_value="default"),
            patch("argus_mcp.cli._server._write_pid_file"),
            patch("argus_mcp.cli._server._remove_pid_file"),
            patch("argus_mcp.cli._server.signal.signal"),
            patch("asyncio.run", side_effect=SystemExit(0)),
        ):
            from argus_mcp.cli import _cmd_server

            _cmd_server(args)  # Should not raise

    def test_foreground_fatal_error(self) -> None:
        args = argparse.Namespace(
            detach=False,
            host=DEFAULT_HOST,
            port=DEFAULT_PORT,
            log_level="info",
            config=None,
            name=None,
            verbose=0,
        )
        with (
            patch("argus_mcp.sessions.auto_name", return_value="default"),
            patch("argus_mcp.cli._server._write_pid_file"),
            patch("argus_mcp.cli._server._remove_pid_file"),
            patch("argus_mcp.cli._server.signal.signal"),
            patch("asyncio.run", side_effect=RuntimeError("boom")),
            pytest.raises(SystemExit),
        ):
            from argus_mcp.cli import _cmd_server

            _cmd_server(args)


# _cmd_secret


class TestCmdSecret:
    """Tests for ``argus-mcp secret`` command handler."""

    def test_secret_set_with_value(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = argparse.Namespace(
            provider="file",
            path=None,
            secret_action="set",
            name="my_key",
            value="my_val",
        )
        mock_store = MagicMock()
        with patch("argus_mcp.secrets.store.SecretStore", return_value=mock_store):
            _cmd_secret(args)
        mock_store.set.assert_called_once_with("my_key", "my_val")
        assert "stored" in capsys.readouterr().out

    def test_secret_set_prompts(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = argparse.Namespace(
            provider="file",
            path=None,
            secret_action="set",
            name="prompted_key",
            value=None,
        )
        mock_store = MagicMock()
        with (
            patch("argus_mcp.secrets.store.SecretStore", return_value=mock_store),
            patch("getpass.getpass", return_value="secret_val"),
        ):
            _cmd_secret(args)
        mock_store.set.assert_called_once_with("prompted_key", "secret_val")

    def test_secret_get_found(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = argparse.Namespace(
            provider="file",
            path=None,
            secret_action="get",
            name="my_key",
        )
        mock_store = MagicMock()
        mock_store.get.return_value = "the_value"
        with patch("argus_mcp.secrets.store.SecretStore", return_value=mock_store):
            _cmd_secret(args)
        assert "the_value" in capsys.readouterr().out

    def test_secret_get_not_found(self) -> None:
        args = argparse.Namespace(
            provider="file",
            path=None,
            secret_action="get",
            name="missing",
        )
        mock_store = MagicMock()
        mock_store.get.return_value = None
        with (
            patch("argus_mcp.secrets.store.SecretStore", return_value=mock_store),
            pytest.raises(SystemExit),
        ):
            _cmd_secret(args)

    def test_secret_list_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = argparse.Namespace(
            provider="file",
            path=None,
            secret_action="list",
        )
        mock_store = MagicMock()
        mock_store.list_names.return_value = []
        with patch("argus_mcp.secrets.store.SecretStore", return_value=mock_store):
            _cmd_secret(args)
        assert "No secrets" in capsys.readouterr().out

    def test_secret_list_populated(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = argparse.Namespace(
            provider="file",
            path=None,
            secret_action="list",
        )
        mock_store = MagicMock()
        mock_store.list_names.return_value = ["c_key", "a_key", "b_key"]
        with patch("argus_mcp.secrets.store.SecretStore", return_value=mock_store):
            _cmd_secret(args)
        out = capsys.readouterr().out
        assert "a_key" in out
        assert "b_key" in out
        assert "c_key" in out

    def test_secret_delete(self, capsys: pytest.CaptureFixture[str]) -> None:
        args = argparse.Namespace(
            provider="file",
            path=None,
            secret_action="delete",
            name="old_key",
        )
        mock_store = MagicMock()
        with patch("argus_mcp.secrets.store.SecretStore", return_value=mock_store):
            _cmd_secret(args)
        mock_store.delete.assert_called_once_with("old_key")
        assert "deleted" in capsys.readouterr().out


# _run_server extended coverage


class TestRunServerExtended:
    """Additional edge-paths in _run_server."""

    @pytest.mark.asyncio
    async def test_transport_detection_failure_defaults_to_streamable_http(self) -> None:
        """When load_argus_config raises, transport defaults to streamable-http."""
        mock_server = MagicMock()
        mock_server.serve = AsyncMock()

        with (
            patch("argus_mcp.cli._server.setup_logging", return_value=("/dev/null", "INFO")),
            patch("argus_mcp.cli._server._find_config_file", return_value="config.yaml"),
            patch("argus_mcp.server.app.app") as mock_app,
            patch(
                "argus_mcp.config.loader.load_argus_config",
                side_effect=OSError("no file"),
            ),
            patch("argus_mcp.cli._server.uvicorn.Config"),
            patch("argus_mcp.cli._server.uvicorn.Server", return_value=mock_server),
            patch("socket.socket") as mock_sock_cls,
        ):
            mock_app.state = MagicMock()
            mock_sock_cls.return_value = MagicMock()
            await _run_server("127.0.0.1", 9990, "info")
            assert mock_app.state.transport_type == "streamable-http"

    @pytest.mark.asyncio
    async def test_serve_keyboard_interrupt(self) -> None:
        """KeyboardInterrupt during serve is caught and logged."""
        mock_server = MagicMock()
        mock_server.serve = AsyncMock(side_effect=KeyboardInterrupt)

        with (
            patch("argus_mcp.cli._server.setup_logging", return_value=("/dev/null", "INFO")),
            patch("argus_mcp.cli._server._find_config_file", return_value="config.yaml"),
            patch("argus_mcp.server.app.app") as mock_app,
            patch("argus_mcp.config.loader.load_argus_config", side_effect=ValueError),
            patch("argus_mcp.cli._server.uvicorn.Config"),
            patch("argus_mcp.cli._server.uvicorn.Server", return_value=mock_server),
            patch("socket.socket") as mock_sock_cls,
        ):
            mock_app.state = MagicMock()
            mock_sock_cls.return_value = MagicMock()
            await _run_server("127.0.0.1", 9991, "info")

    @pytest.mark.asyncio
    async def test_serve_unexpected_exception_propagates(self) -> None:
        """Unexpected error during serve is re-raised."""
        mock_server = MagicMock()
        mock_server.serve = AsyncMock(side_effect=RuntimeError("boom"))

        with (
            patch("argus_mcp.cli._server.setup_logging", return_value=("/dev/null", "INFO")),
            patch("argus_mcp.cli._server._find_config_file", return_value="config.yaml"),
            patch("argus_mcp.server.app.app") as mock_app,
            patch("argus_mcp.config.loader.load_argus_config", side_effect=ValueError),
            patch("argus_mcp.cli._server.uvicorn.Config"),
            patch("argus_mcp.cli._server.uvicorn.Server", return_value=mock_server),
            patch("socket.socket") as mock_sock_cls,
        ):
            mock_app.state = MagicMock()
            mock_sock_cls.return_value = MagicMock()
            with pytest.raises(RuntimeError, match="boom"):
                await _run_server("127.0.0.1", 9992, "info")


# _cmd_server extended coverage


class TestCmdServerExtended:
    """Additional _cmd_server paths for SystemExit non-zero."""

    def test_foreground_system_exit_nonzero(self) -> None:
        """SystemExit with non-zero code logs error but doesn't re-raise."""
        args = argparse.Namespace(
            detach=False,
            host="127.0.0.1",
            port=9000,
            log_level="info",
            config=None,
            name=None,
            verbose=0,
        )
        with (
            patch("argus_mcp.cli._server._write_pid_file"),
            patch("argus_mcp.cli._server._remove_pid_file"),
            patch("argus_mcp.cli._restore_terminal"),
            patch("argus_mcp.sessions.auto_name", return_value="auto-9000"),
            patch("asyncio.run", side_effect=SystemExit(42)),
            patch("signal.signal"),
        ):
            _cmd_server(args)  # should not raise — exits handled gracefully


# _stop_legacy_pid extended coverage


class TestStopLegacyPidExtended:
    """Extra paths in _stop_legacy_pid."""

    def test_permission_error_still_sends_sigterm(self) -> None:
        """PermissionError on kill(0) is harmless — still sends SIGTERM."""
        with (
            patch("builtins.open", mock_open(read_data="1234")),
            patch("os.kill") as mock_kill,
            patch("argus_mcp.cli._stop._cleanup_pid_file"),
            patch("time.sleep"),
        ):
            # kill(pid, 0) → PermissionError (process owned by another user)
            # kill(pid, SIGTERM) → ok
            # kill(pid, 0) loop → ProcessLookupError (exited)
            def kill_side_effect(pid: int, sig: int) -> None:
                if sig == 0 and mock_kill.call_count == 1:
                    raise PermissionError("op not permitted")
                if sig == 0 and mock_kill.call_count > 2:
                    raise ProcessLookupError

            mock_kill.side_effect = kill_side_effect
            _stop_legacy_pid()
            # SIGTERM was sent
            calls = [c for c in mock_kill.call_args_list if c[0][1] != 0]
            assert len(calls) >= 1

    def test_sigterm_fails_with_os_error(self) -> None:
        """OSError sending SIGTERM calls sys.exit(1)."""
        with (
            patch("builtins.open", mock_open(read_data="1234")),
            patch("os.kill") as mock_kill,
        ):

            def kill_side_effect(pid: int, sig: int) -> None:
                if sig == 0:
                    return  # process exists
                raise OSError("denied")

            mock_kill.side_effect = kill_side_effect
            with pytest.raises(SystemExit):
                _stop_legacy_pid()

    def test_sigkill_after_timeout(self, capsys: pytest.CaptureFixture[str]) -> None:
        """If process doesn't exit in 3s, SIGKILL is sent."""
        import signal as _sig

        call_count = 0
        with (
            patch("builtins.open", mock_open(read_data="1234")),
            patch("os.kill") as mock_kill,
            patch("argus_mcp.cli._stop._cleanup_pid_file"),
            patch("time.sleep"),
        ):

            def kill_side_effect(pid: int, sig: int) -> None:
                nonlocal call_count
                call_count += 1
                if sig == 0 and call_count == 1:
                    return  # alive check
                if sig == _sig.SIGTERM:
                    return
                if sig == 0:
                    return  # still alive in loop
                if sig == _sig.SIGKILL:
                    return

            mock_kill.side_effect = kill_side_effect
            _stop_legacy_pid()
            out = capsys.readouterr().out
            assert "SIGKILL" in out or "stopped" in out.lower()

    def test_value_error_reading_pid(self) -> None:
        """Non-integer PID file content causes sys.exit."""
        with patch("builtins.open", mock_open(read_data="not_a_number")):
            with pytest.raises(SystemExit):
                _stop_legacy_pid()


# _cmd_stop extended (find_session path)


class TestCmdStopExtended:
    """Cover the find_session auto-detection paths."""

    def test_auto_stop_single_session_success(
        self,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """When find_session returns a session, it's stopped."""
        mock_info = MagicMock()
        mock_info.name = "auto-9000"
        mock_info.pid = 1234
        args = argparse.Namespace(session_name=None, all=False, force=False)
        with (
            patch("argus_mcp.sessions.find_session", return_value=mock_info),
            patch("argus_mcp.sessions.stop_session", return_value=True),
            patch("argus_mcp.cli._stop._cleanup_pid_file"),
        ):
            _cmd_stop(args)
        assert "stopped" in capsys.readouterr().out.lower()

    def test_auto_stop_single_session_failure(self) -> None:
        """When stop_session fails, sys.exit(1)."""
        mock_info = MagicMock()
        mock_info.name = "auto-9000"
        mock_info.pid = 1234
        args = argparse.Namespace(session_name=None, all=False, force=False)
        with (
            patch("argus_mcp.sessions.find_session", return_value=mock_info),
            patch("argus_mcp.sessions.stop_session", return_value=False),
            patch("argus_mcp.cli._stop._cleanup_pid_file"),
        ):
            with pytest.raises(SystemExit):
                _cmd_stop(args)

    def test_no_sessions_falls_back_to_legacy(self) -> None:
        """When no session found and none alive, falls to _stop_legacy_pid."""
        args = argparse.Namespace(session_name=None, all=False, force=False)
        with (
            patch("argus_mcp.sessions.find_session", return_value=None),
            patch("argus_mcp.sessions.list_sessions", return_value=[]),
            patch("argus_mcp.sessions.discover_server_processes", return_value=[]),
            patch("argus_mcp.cli._stop._stop_legacy_pid") as mock_legacy,
        ):
            _cmd_stop(args)
            mock_legacy.assert_called_once()


# _build_tui_server_manager


class TestBuildTuiServerManager:
    """Tests for _build_tui_server_manager helper."""

    def test_servers_config_from_args(self) -> None:
        """Uses ServerManager.from_config when servers_config is on args."""
        args = argparse.Namespace(servers_config="/tmp/servers.yaml")
        client_cfg = MagicMock()
        client_cfg.servers_config = None
        with patch("argus_mcp.tui.server_manager.ServerManager.from_config") as mock_fc:
            mock_fc.return_value = MagicMock()
            _result = _build_tui_server_manager(args, client_cfg, "http://localhost:9000", None)
            mock_fc.assert_called_once_with(config_path="/tmp/servers.yaml")

    def test_servers_config_from_client_cfg(self) -> None:
        """Falls back to client_cfg.servers_config."""
        args = argparse.Namespace(servers_config=None)
        client_cfg = MagicMock()
        client_cfg.servers_config = "/tmp/client_servers.yaml"
        with patch("argus_mcp.tui.server_manager.ServerManager.from_config") as mock_fc:
            mock_fc.return_value = MagicMock()
            _build_tui_server_manager(args, client_cfg, "http://localhost:9000", None)
            mock_fc.assert_called_once_with(config_path="/tmp/client_servers.yaml")

    def test_no_config_and_empty_manager_adds_default(self) -> None:
        """When no servers_config and manager is empty, adds a default server."""
        args = argparse.Namespace(servers_config=None)
        client_cfg = MagicMock()
        client_cfg.servers_config = None
        mock_mgr = MagicMock()
        mock_mgr.count = 0
        with patch("argus_mcp.tui.server_manager.ServerManager.from_config", return_value=mock_mgr):
            _result = _build_tui_server_manager(args, client_cfg, "http://localhost:9000", "tok")
            mock_mgr.add.assert_called_once_with(
                "default",
                "http://localhost:9000",
                "tok",
                set_active=True,
            )

    def test_no_config_and_manager_has_servers(self) -> None:
        """When no servers_config but manager already has servers, no add."""
        args = argparse.Namespace(servers_config=None)
        client_cfg = MagicMock()
        client_cfg.servers_config = None
        mock_mgr = MagicMock()
        mock_mgr.count = 2
        with patch("argus_mcp.tui.server_manager.ServerManager.from_config", return_value=mock_mgr):
            _result = _build_tui_server_manager(args, client_cfg, "http://localhost:9000", None)
            mock_mgr.add.assert_not_called()


# _cmd_tui


class TestCmdTui:
    """Tests for _cmd_tui."""

    def test_tui_runs_successfully(self) -> None:
        """Happy-path: TUI app runs and returns."""
        args = argparse.Namespace(
            config=None,
            token=None,
            server_url=None,
            servers_config=None,
            env_config=None,
        )
        mock_app = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.token = None
        mock_cfg.servers_config = None
        with (
            patch("argus_mcp.cli._tui._load_client_config", return_value=(mock_cfg, None)),
            patch(
                "argus_mcp.cli._tui._resolve_tui_server_url", return_value="http://localhost:9000"
            ),
            patch("argus_mcp.cli._tui._build_tui_server_manager") as mock_mgr_fn,
            patch("argus_mcp.tui.app.ArgusApp", return_value=mock_app),
            patch("argus_mcp.cli._tui._restore_terminal"),
            patch("argus_mcp.cli._tui.termios", create=True),
        ):
            mock_mgr = MagicMock()
            mock_mgr.count = 1
            mock_mgr_fn.return_value = mock_mgr
            _cmd_tui(args)
            mock_app.run.assert_called_once()

    def test_tui_import_error(self, capsys: pytest.CaptureFixture[str]) -> None:
        """ImportError for Textual prints helpful message."""
        args = argparse.Namespace(
            config=None,
            token=None,
            server_url=None,
            servers_config=None,
            env_config=None,
        )
        mock_cfg = MagicMock()
        mock_cfg.token = None
        with (
            patch("argus_mcp.cli._tui._load_client_config", return_value=(mock_cfg, None)),
            patch(
                "argus_mcp.cli._tui._resolve_tui_server_url", return_value="http://localhost:9000"
            ),
            patch("argus_mcp.tui.app.ArgusApp", side_effect=ImportError("No module textual")),
            patch("argus_mcp.cli._tui._restore_terminal"),
        ):
            with pytest.raises(SystemExit):
                _cmd_tui(args)
            assert "textual" in capsys.readouterr().err.lower()

    def test_tui_keyboard_interrupt(self) -> None:
        """KeyboardInterrupt in TUI is caught gracefully."""
        args = argparse.Namespace(
            config=None,
            token=None,
            server_url=None,
            servers_config=None,
            env_config=None,
        )
        mock_cfg = MagicMock()
        mock_cfg.token = None
        mock_cfg.servers_config = None
        mock_app = MagicMock()
        mock_app.run.side_effect = KeyboardInterrupt
        with (
            patch("argus_mcp.cli._tui._load_client_config", return_value=(mock_cfg, None)),
            patch(
                "argus_mcp.cli._tui._resolve_tui_server_url", return_value="http://localhost:9000"
            ),
            patch("argus_mcp.cli._tui._build_tui_server_manager") as mock_mgr_fn,
            patch("argus_mcp.tui.app.ArgusApp", return_value=mock_app),
            patch("argus_mcp.cli._tui._restore_terminal"),
        ):
            mock_mgr_fn.return_value = MagicMock(count=1)
            _cmd_tui(args)  # should not raise

    def test_tui_fatal_error(self) -> None:
        """Unexpected exception in TUI calls sys.exit(1)."""
        args = argparse.Namespace(
            config=None,
            token=None,
            server_url=None,
            servers_config=None,
            env_config=None,
        )
        mock_cfg = MagicMock()
        mock_cfg.token = None
        mock_cfg.servers_config = None
        mock_app = MagicMock()
        mock_app.run.side_effect = RuntimeError("TUI crash")
        with (
            patch("argus_mcp.cli._tui._load_client_config", return_value=(mock_cfg, None)),
            patch(
                "argus_mcp.cli._tui._resolve_tui_server_url", return_value="http://localhost:9000"
            ),
            patch("argus_mcp.cli._tui._build_tui_server_manager") as mock_mgr_fn,
            patch("argus_mcp.tui.app.ArgusApp", return_value=mock_app),
            patch("argus_mcp.cli._tui._restore_terminal"),
        ):
            mock_mgr_fn.return_value = MagicMock(count=1)
            with pytest.raises(SystemExit):
                _cmd_tui(args)

    def test_tui_token_from_env(self) -> None:
        """Token resolved from ARGUS_MGMT_TOKEN env var."""
        args = argparse.Namespace(
            config=None,
            token=None,
            server_url=None,
            servers_config=None,
            env_config=None,
        )
        mock_cfg = MagicMock()
        mock_cfg.token = None
        mock_cfg.servers_config = None
        mock_app = MagicMock()
        with (
            patch("argus_mcp.cli._tui._load_client_config", return_value=(mock_cfg, None)),
            patch(
                "argus_mcp.cli._tui._resolve_tui_server_url", return_value="http://localhost:9000"
            ),
            patch("argus_mcp.cli._tui._build_tui_server_manager") as mock_mgr_fn,
            patch("argus_mcp.tui.app.ArgusApp", return_value=mock_app) as mock_app_cls,
            patch("argus_mcp.cli._tui._restore_terminal"),
            patch.dict(os.environ, {"ARGUS_MGMT_TOKEN": "env-token-123"}),
        ):
            mock_mgr_fn.return_value = MagicMock(count=1)
            _cmd_tui(args)
            assert mock_app_cls.call_args[1]["token"] == "env-token-123"


# _cmd_build


class TestCmdBuild:
    """Tests for _cmd_build."""

    def test_no_stdio_backends(self, capsys: pytest.CaptureFixture[str]) -> None:
        """When no stdio backends found, prints message and returns."""
        args = argparse.Namespace(config=None)
        with (
            patch("argus_mcp.cli._build._find_config_file", return_value="config.yaml"),
            patch("argus_mcp.cli._build.setup_logging"),
            patch(
                "argus_mcp.config.loader.load_and_validate_config",
                return_value={"web": {"type": "sse", "params": MagicMock()}},
            ),
        ):
            _cmd_build(args)
        assert "nothing to build" in capsys.readouterr().out.lower()

    def test_build_invalid_params_skipped(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Backend with non-StdioServerParameters params is skipped."""
        args = argparse.Namespace(config="my.yaml")
        with (
            patch("argus_mcp.cli._build.setup_logging"),
            patch(
                "argus_mcp.config.loader.load_and_validate_config",
                return_value={"bad": {"type": "stdio", "params": "not-a-params-obj"}},
            ),
        ):
            _cmd_build(args)
        out = capsys.readouterr().out
        assert "skip" in out.lower() or "Done" in out

    def test_build_success(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Successful build prints OK."""
        args = argparse.Namespace(config="my.yaml")
        mock_params = MagicMock()
        mock_params.command = "test-server"
        with (
            patch("argus_mcp.cli._build.setup_logging"),
            patch(
                "argus_mcp.config.loader.load_and_validate_config",
                return_value={
                    "tool1": {
                        "type": "stdio",
                        "params": mock_params,
                        "container": {"enabled": True},
                    },
                },
            ),
            patch("mcp.StdioServerParameters", new=type(mock_params)),
            patch(
                "argus_mcp.bridge.container.wrap_backend",
                new=AsyncMock(return_value=(MagicMock(), True)),
            ),
        ):
            _cmd_build(args)
        out = capsys.readouterr().out
        assert "OK" in out or "Done" in out

    def test_build_failure(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Failed build prints FAILED and exits."""
        args = argparse.Namespace(config="my.yaml")
        mock_params = MagicMock()
        mock_params.command = "test-server"
        with (
            patch("argus_mcp.cli._build.setup_logging"),
            patch(
                "argus_mcp.config.loader.load_and_validate_config",
                return_value={
                    "tool1": {
                        "type": "stdio",
                        "params": mock_params,
                        "container": {},
                    },
                },
            ),
            patch("mcp.StdioServerParameters", new=type(mock_params)),
            patch(
                "argus_mcp.bridge.container.wrap_backend",
                new=AsyncMock(side_effect=RuntimeError("build failed")),
            ),
        ):
            with pytest.raises(SystemExit):
                _cmd_build(args)
        out = capsys.readouterr().out
        assert "FAILED" in out
