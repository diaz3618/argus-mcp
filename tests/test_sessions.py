"""Tests for the named session management module."""

import os
from unittest import mock

import pytest

from argus_mcp.sessions import (
    SessionInfo,
    auto_name,
    check_port_conflict,
    find_session,
    list_sessions,
    load_session,
    remove_session,
    save_session,
    session_path,
    validate_name,
)

# validate_name ────────────────────────────────────────────────────


class TestValidateName:
    def test_valid_names(self):
        assert validate_name("default") == "default"
        assert validate_name("dev") == "dev"
        assert validate_name("argus-9000") == "argus-9000"
        assert validate_name("my-server-1") == "my-server-1"

    def test_uppercased_input_normalised(self):
        assert validate_name("DEV") == "dev"
        assert validate_name("My-Server") == "my-server"

    def test_invalid_names(self):
        with pytest.raises(ValueError):
            validate_name("")
        with pytest.raises(ValueError):
            validate_name("-bad")  # starts with hyphen
        with pytest.raises(ValueError):
            validate_name("has spaces")
        with pytest.raises(ValueError):
            validate_name("a" * 33)  # too long

    def test_name_with_whitespace_stripped(self):
        assert validate_name("  dev  ") == "dev"


# auto_name ────────────────────────────────────────────────────────


class TestAutoName:
    def test_default_port(self):
        assert auto_name(9000, 9000) == "default"

    def test_custom_port(self):
        assert auto_name(8080, 9000) == "argus-8080"
        assert auto_name(3000, 9000) == "argus-3000"


# SessionInfo.is_alive ────────────────────────────────────────────


class TestSessionInfoIsAlive:
    def test_current_process_is_alive(self):
        info = SessionInfo(name="test", pid=os.getpid(), host="127.0.0.1", port=9000, config="")
        assert info.is_alive() is True

    def test_dead_pid(self):
        # Use a very high PID that is almost certainly not running
        info = SessionInfo(name="test", pid=999999999, host="127.0.0.1", port=9000, config="")
        assert info.is_alive() is False


# save/load/remove session ────────────────────────────────────────


class TestSessionPersistence:
    def test_save_load_roundtrip(self, tmp_path):
        """Save and load a session via a temporary directory."""
        with mock.patch("argus_mcp.sessions._SESSION_DIR", str(tmp_path)):
            info = SessionInfo(
                name="test",
                pid=12345,
                host="0.0.0.0",
                port=8080,
                config="config.yaml",
                log_file="/tmp/test.log",
                started_at="2026-01-01T00:00:00+00:00",
            )
            save_session(info)

            loaded = load_session("test")
            assert loaded is not None
            assert loaded.name == "test"
            assert loaded.pid == 12345
            assert loaded.host == "0.0.0.0"
            assert loaded.port == 8080
            assert loaded.config == "config.yaml"
            assert loaded.log_file == "/tmp/test.log"

    def test_load_missing_returns_none(self, tmp_path):
        with mock.patch("argus_mcp.sessions._SESSION_DIR", str(tmp_path)):
            assert load_session("nonexistent") is None

    def test_remove_session(self, tmp_path):
        with mock.patch("argus_mcp.sessions._SESSION_DIR", str(tmp_path)):
            info = SessionInfo(name="removeme", pid=1, host="127.0.0.1", port=9000, config="")
            save_session(info)
            assert load_session("removeme") is not None

            remove_session("removeme")
            assert load_session("removeme") is None

    def test_remove_nonexistent_does_not_raise(self, tmp_path):
        with mock.patch("argus_mcp.sessions._SESSION_DIR", str(tmp_path)):
            remove_session("nope")  # should not raise

    def test_load_corrupt_file_returns_none(self, tmp_path):
        with mock.patch("argus_mcp.sessions._SESSION_DIR", str(tmp_path)):
            path = os.path.join(str(tmp_path), "corrupt.json")
            with open(path, "w") as f:
                f.write("not json at all {{{")
            assert load_session("corrupt") is None


# list_sessions ───────────────────────────────────────────────────


class TestListSessions:
    def test_empty_dir(self, tmp_path):
        with mock.patch("argus_mcp.sessions._SESSION_DIR", str(tmp_path)):
            assert list_sessions() == []

    def test_lists_only_alive_sessions(self, tmp_path):
        with mock.patch("argus_mcp.sessions._SESSION_DIR", str(tmp_path)):
            # Save current process (alive)
            alive = SessionInfo(
                name="alive", pid=os.getpid(), host="127.0.0.1", port=9000, config=""
            )
            save_session(alive)

            # Save dead process
            dead = SessionInfo(name="dead", pid=999999999, host="127.0.0.1", port=8080, config="")
            save_session(dead)

            sessions = list_sessions()
            assert len(sessions) == 1
            assert sessions[0].name == "alive"

            # Dead session file should be cleaned up
            assert not os.path.exists(session_path("dead"))

    def test_include_dead(self, tmp_path):
        with mock.patch("argus_mcp.sessions._SESSION_DIR", str(tmp_path)):
            dead = SessionInfo(name="dead", pid=999999999, host="127.0.0.1", port=8080, config="")
            save_session(dead)

            sessions = list_sessions(include_dead=True)
            assert len(sessions) == 1
            assert sessions[0].name == "dead"

    def test_nonexistent_dir(self, tmp_path):
        nonexistent = str(tmp_path / "does_not_exist")
        with mock.patch("argus_mcp.sessions._SESSION_DIR", nonexistent):
            assert list_sessions() == []


# find_session ────────────────────────────────────────────────────


class TestFindSession:
    def test_find_by_name(self, tmp_path):
        with mock.patch("argus_mcp.sessions._SESSION_DIR", str(tmp_path)):
            info = SessionInfo(
                name="findme", pid=os.getpid(), host="127.0.0.1", port=9000, config=""
            )
            save_session(info)

            found = find_session("findme")
            assert found is not None
            assert found.name == "findme"

    def test_find_by_name_dead_returns_none(self, tmp_path):
        with mock.patch("argus_mcp.sessions._SESSION_DIR", str(tmp_path)):
            info = SessionInfo(name="dead", pid=999999999, host="127.0.0.1", port=9000, config="")
            save_session(info)
            assert find_session("dead") is None

    def test_find_only_session(self, tmp_path):
        with mock.patch("argus_mcp.sessions._SESSION_DIR", str(tmp_path)):
            info = SessionInfo(name="only", pid=os.getpid(), host="127.0.0.1", port=9000, config="")
            save_session(info)

            found = find_session()
            assert found is not None
            assert found.name == "only"

    def test_find_none_when_multiple(self, tmp_path):
        with mock.patch("argus_mcp.sessions._SESSION_DIR", str(tmp_path)):
            # Both use current PID so they appear alive
            info1 = SessionInfo(name="one", pid=os.getpid(), host="127.0.0.1", port=9000, config="")
            info2 = SessionInfo(name="two", pid=os.getpid(), host="127.0.0.1", port=8080, config="")
            save_session(info1)
            save_session(info2)

            assert find_session() is None

    def test_find_none_when_empty(self, tmp_path):
        with mock.patch("argus_mcp.sessions._SESSION_DIR", str(tmp_path)):
            assert find_session() is None


# check_port_conflict ─────────────────────────────────────────────


class TestCheckPortConflict:
    def test_no_conflict(self, tmp_path):
        with mock.patch("argus_mcp.sessions._SESSION_DIR", str(tmp_path)):
            assert check_port_conflict("127.0.0.1", 9000) is None

    def test_conflict_found(self, tmp_path):
        with mock.patch("argus_mcp.sessions._SESSION_DIR", str(tmp_path)):
            info = SessionInfo(
                name="blocker", pid=os.getpid(), host="127.0.0.1", port=9000, config=""
            )
            save_session(info)

            conflict = check_port_conflict("127.0.0.1", 9000)
            assert conflict is not None
            assert conflict.name == "blocker"

    def test_wildcard_host_conflicts(self, tmp_path):
        with mock.patch("argus_mcp.sessions._SESSION_DIR", str(tmp_path)):
            info = SessionInfo(
                name="wildcard", pid=os.getpid(), host="0.0.0.0", port=8080, config=""
            )
            save_session(info)

            conflict = check_port_conflict("127.0.0.1", 8080)
            assert conflict is not None
            assert conflict.name == "wildcard"

    def test_different_port_no_conflict(self, tmp_path):
        with mock.patch("argus_mcp.sessions._SESSION_DIR", str(tmp_path)):
            info = SessionInfo(
                name="other", pid=os.getpid(), host="127.0.0.1", port=9000, config=""
            )
            save_session(info)

            assert check_port_conflict("127.0.0.1", 8080) is None


# session_path ────────────────────────────────────────────────────


class TestSessionPath:
    def test_session_path_format(self, tmp_path):
        with mock.patch("argus_mcp.sessions._SESSION_DIR", str(tmp_path)):
            path = session_path("myserver")
            assert path.endswith("myserver.json")
