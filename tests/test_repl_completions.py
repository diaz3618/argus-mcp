"""Tests for argus_cli.repl.completions — command tree and API refresh."""

from __future__ import annotations

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
    return ReplState(
        config=cfg,
        connection=ConnectionState(),
        completions=CompletionData(**overrides.pop("completions", {})),
        session=SessionState(),
    )


# ── build_command_tree ────────────────────────────────────────────────


def test_build_command_tree_static_keys():
    from argus_cli.repl.completions import build_command_tree

    state = _make_repl_state()
    tree = build_command_tree(state)
    # Static keys
    assert "server" in tree
    assert "config" in tree
    assert "help" in tree
    assert "exit" in tree


def test_build_command_tree_dynamic_backends():
    from argus_cli.repl.completions import build_command_tree

    state = _make_repl_state(completions={"backend_names": ["alpha", "beta"]})
    tree = build_command_tree(state)
    assert "backends" in tree
    backend_inspect = tree["backends"]["inspect"]
    assert "alpha" in backend_inspect
    assert "beta" in backend_inspect


def test_build_command_tree_dynamic_tools():
    from argus_cli.repl.completions import build_command_tree

    state = _make_repl_state(completions={"tool_names": ["echo", "fetch"]})
    tree = build_command_tree(state)
    tool_inspect = tree["tools"]["inspect"]
    assert "echo" in tool_inspect
    assert "fetch" in tool_inspect


def test_build_command_tree_empty_dynamic():
    from argus_cli.repl.completions import build_command_tree

    state = _make_repl_state()
    tree = build_command_tree(state)
    # When no dynamic data, should be None (not empty dict)
    assert tree["backends"]["inspect"] is None


def test_build_command_tree_set_subcommands():
    from argus_cli.repl.completions import build_command_tree

    state = _make_repl_state()
    tree = build_command_tree(state)
    assert "set" in tree
    assert "output" in tree["set"]
    assert "rich" in tree["set"]["output"]


# ── refresh_completions ───────────────────────────────────────────────


@patch("argus_cli.client.ArgusClient")
def test_refresh_completions_success(MockClient):
    from argus_cli.repl.completions import refresh_completions

    client = MagicMock()
    MockClient.return_value.__enter__ = MagicMock(return_value=client)
    MockClient.return_value.__exit__ = MagicMock(return_value=False)

    client.health.return_value = {"status": "healthy"}
    client.status.return_value = {"service": {"version": "2.0.0", "uptime_seconds": 3661}}
    client.backends.return_value = {
        "backends": [
            {"name": "b1", "health": {"status": "healthy"}},
            {"name": "b2", "health": {"status": "unhealthy"}},
        ]
    }
    client.capabilities.return_value = {
        "tools": [{"name": "echo"}],
        "resources": [{"uri": "file://a"}],
        "prompts": [{"name": "p1"}],
    }
    client.events.return_value = {"events": [{"id": 1}]}

    state = _make_repl_state()
    refresh_completions(state)

    assert state.connection.is_connected is True
    assert state.connection.version == "2.0.0"
    assert state.connection.uptime == "1h1m1s"
    assert state.connection.backend_count == 2
    assert state.connection.healthy_count == 1
    assert state.completions.backend_names == ["b1", "b2"]
    assert state.completions.tool_names == ["echo"]
    assert state.completions.resource_uris == ["file://a"]
    assert state.completions.prompt_names == ["p1"]
    assert state.connection.last_event_age == "recent"


@patch("argus_cli.client.ArgusClient")
def test_refresh_completions_health_failure(MockClient):
    from argus_cli.client import ArgusClientError
    from argus_cli.repl.completions import refresh_completions

    client = MagicMock()
    MockClient.return_value.__enter__ = MagicMock(return_value=client)
    MockClient.return_value.__exit__ = MagicMock(return_value=False)

    client.health.side_effect = ArgusClientError(500, "error", "fail")

    state = _make_repl_state()
    refresh_completions(state)

    assert state.connection.is_connected is False
    assert state.connection.server_status == "disconnected"


@patch("argus_cli.client.ArgusClient")
def test_refresh_completions_client_error(MockClient):
    from argus_cli.client import ArgusClientError
    from argus_cli.repl.completions import refresh_completions

    MockClient.return_value.__enter__ = MagicMock(
        side_effect=ArgusClientError(500, "error", "connection refused")
    )
    MockClient.return_value.__exit__ = MagicMock(return_value=False)

    state = _make_repl_state()
    refresh_completions(state)

    assert state.connection.is_connected is False


@patch("argus_cli.client.ArgusClient")
def test_refresh_completions_no_events(MockClient):
    from argus_cli.repl.completions import refresh_completions

    client = MagicMock()
    MockClient.return_value.__enter__ = MagicMock(return_value=client)
    MockClient.return_value.__exit__ = MagicMock(return_value=False)

    client.health.return_value = {"status": "healthy"}
    client.status.return_value = {"service": {}}
    client.backends.return_value = {"backends": []}
    client.capabilities.return_value = {"tools": [], "resources": [], "prompts": []}
    client.events.return_value = {"events": []}

    state = _make_repl_state()
    refresh_completions(state)

    assert state.connection.last_event_age == "none"
