"""Tests for argus_cli.repl.state — dataclasses and persistence helpers."""

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
    ensure_history_dir,
    load_aliases,
    save_aliases,
)

# ── ConnectionState defaults ──────────────────────────────────────────


def test_connection_state_defaults():
    conn = ConnectionState()
    assert conn.is_connected is False
    assert conn.server_status == "unknown"
    assert conn.version == ""
    assert conn.uptime == ""
    assert conn.backend_count == 0
    assert conn.healthy_count == 0


def test_connection_state_custom():
    conn = ConnectionState(is_connected=True, version="1.2.3", backend_count=5, healthy_count=3)
    assert conn.is_connected is True
    assert conn.version == "1.2.3"
    assert conn.backend_count == 5
    assert conn.healthy_count == 3


# ── CompletionData defaults ───────────────────────────────────────────


def test_completion_data_defaults():
    comp = CompletionData()
    assert comp.backend_names == []
    assert comp.tool_names == []
    assert comp.resource_uris == []
    assert comp.prompt_names == []
    assert comp.skill_names == []
    assert comp.workflow_names == []
    assert comp.secret_names == []


def test_completion_data_populated():
    comp = CompletionData(
        backend_names=["a", "b"],
        tool_names=["t1"],
    )
    assert comp.backend_names == ["a", "b"]
    assert comp.tool_names == ["t1"]


# ── SessionState ──────────────────────────────────────────────────────


def test_session_state_defaults():
    sess = SessionState()
    assert sess.aliases == {}
    assert sess.scoped_backend is None
    assert sess.last_result is None


def test_session_state_aliases():
    sess = SessionState(aliases={"ll": "backends list"}, scoped_backend="my-backend")
    assert sess.aliases["ll"] == "backends list"
    assert sess.scoped_backend == "my-backend"


# ── ReplState composite ──────────────────────────────────────────────


def test_repl_state_composite():
    cfg = MagicMock()
    state = ReplState(config=cfg)
    assert state.config is cfg
    assert isinstance(state.connection, ConnectionState)
    assert isinstance(state.completions, CompletionData)
    assert isinstance(state.session, SessionState)


# ── ensure_history_dir ────────────────────────────────────────────────


def test_ensure_history_dir(tmp_path: Path):
    fake_dir = tmp_path / ".config" / "argus-mcp"
    with patch("argus_cli.repl.state._HISTORY_DIR", str(fake_dir)):
        result = ensure_history_dir()
    assert result.endswith("history")
    assert fake_dir.is_dir()


# ── load_aliases / save_aliases ───────────────────────────────────────


def test_load_aliases_missing_file(tmp_path: Path):
    fake_file = tmp_path / "aliases.yaml"
    with patch("argus_cli.repl.state._ALIASES_FILE", fake_file):
        aliases = load_aliases()
    assert aliases == {}


def test_save_and_load_aliases(tmp_path: Path):
    fake_file = tmp_path / "aliases.yaml"
    test_aliases = {"ll": "backends list", "st": "server status"}
    with patch("argus_cli.repl.state._ALIASES_FILE", fake_file):
        save_aliases(test_aliases)
        loaded = load_aliases()
    assert loaded == test_aliases


def test_load_aliases_corrupt_yaml(tmp_path: Path):
    fake_file = tmp_path / "aliases.yaml"
    # Valid YAML that parses to a list (not a dict) — isinstance(data, dict) returns False
    fake_file.write_text("- item1\n- item2\n", encoding="utf-8")
    with patch("argus_cli.repl.state._ALIASES_FILE", fake_file):
        aliases = load_aliases()
    # Non-dict YAML is gracefully handled as empty aliases
    assert aliases == {}
