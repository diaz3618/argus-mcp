"""Tests for argus_cli.repl.toolbar — prompt and toolbar rendering."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("argus_cli", reason="argus_cli package not installed")

from argus_cli.repl.state import ReplState  # noqa: E402
from argus_cli.repl.toolbar import _ansi, make_prompt, make_toolbar  # noqa: E402

_MOCK_COLORS = {
    "success": "#00ff00",
    "warning": "#ffff00",
    "info": "#00ffff",
    "error": "#ff0000",
}


def _make_state(**overrides) -> ReplState:
    """Create a ReplState with sensible defaults for testing."""
    cfg = MagicMock()
    cfg.server_url = "http://localhost:8080"
    cfg.show_toolbar = True
    cfg.vi_mode = False
    state = ReplState(config=cfg)
    for k, v in overrides.items():
        if hasattr(state.connection, k):
            setattr(state.connection, k, v)
        elif hasattr(state.session, k):
            setattr(state.session, k, v)
    return state


# ── _ansi helper ──────────────────────────────────────────────────────


class TestAnsi:
    @patch("argus_cli.repl.toolbar._ensure_loaded")
    @patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS, clear=True)
    def test_hex_color_returned(self, _mock_el):
        """When COLORS has a hex value, it should be returned as-is."""
        result = _ansi("success")
        assert result == "#00ff00"

    @patch("argus_cli.repl.toolbar._ensure_loaded")
    @patch.dict("argus_cli.theme.COLORS", {}, clear=True)
    def test_fallback_for_known_role(self, _mock_el):
        """When COLORS has no entry, falls back to ANSI keyword."""
        result = _ansi("success")
        assert result == "ansigreen"

    @patch("argus_cli.repl.toolbar._ensure_loaded")
    @patch.dict("argus_cli.theme.COLORS", {}, clear=True)
    def test_fallback_for_unknown_role(self, _mock_el):
        """Unknown role with no ANSI fallback returns ansiwhite."""
        result = _ansi("unknown_role")
        assert result == "ansiwhite"

    @patch("argus_cli.repl.toolbar._ensure_loaded")
    @patch.dict("argus_cli.theme.COLORS", {"warning": "not-hex"}, clear=True)
    def test_non_hex_color_uses_fallback(self, _mock_el):
        """Non-hex color string falls back to ANSI keyword."""
        result = _ansi("warning")
        assert result == "ansiyellow"

    @patch("argus_cli.repl.toolbar._ensure_loaded")
    @patch.dict("argus_cli.theme.COLORS", {"error": "#ff0000"}, clear=True)
    def test_error_hex(self, _mock_el):
        result = _ansi("error")
        assert result == "#ff0000"


# ── make_prompt ───────────────────────────────────────────────────────


class TestMakePrompt:
    @patch("argus_cli.repl.toolbar._ensure_loaded")
    @patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS, clear=True)
    def test_connected_healthy(self, _mock_el):
        state = _make_state(is_connected=True, server_status="healthy")
        prompt = make_prompt(state)
        assert "argus" in str(prompt)

    @patch("argus_cli.repl.toolbar._ensure_loaded")
    @patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS, clear=True)
    def test_connected_degraded(self, _mock_el):
        state = _make_state(is_connected=True, server_status="degraded")
        prompt = make_prompt(state)
        assert "argus" in str(prompt)

    @patch("argus_cli.repl.toolbar._ensure_loaded")
    @patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS, clear=True)
    def test_connected_warning(self, _mock_el):
        state = _make_state(is_connected=True, server_status="warning")
        prompt = make_prompt(state)
        assert "argus" in str(prompt)

    @patch("argus_cli.repl.toolbar._ensure_loaded")
    @patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS, clear=True)
    def test_connected_other_status(self, _mock_el):
        state = _make_state(is_connected=True, server_status="other")
        prompt = make_prompt(state)
        assert "argus" in str(prompt)

    @patch("argus_cli.repl.toolbar._ensure_loaded")
    @patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS, clear=True)
    def test_disconnected(self, _mock_el):
        state = _make_state(is_connected=False)
        prompt = make_prompt(state)
        assert "argus" in str(prompt)

    @patch("argus_cli.repl.toolbar._ensure_loaded")
    @patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS, clear=True)
    def test_scoped_backend(self, _mock_el):
        state = _make_state(is_connected=True, server_status="healthy")
        state.session.scoped_backend = "my-backend"
        prompt = make_prompt(state)
        assert "my-backend" in str(prompt)


# ── make_toolbar ──────────────────────────────────────────────────────


class TestMakeToolbar:
    @patch("argus_cli.repl.toolbar._ensure_loaded")
    @patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS, clear=True)
    def test_connected_healthy_toolbar(self, _mock_el):
        state = _make_state(
            is_connected=True, server_status="healthy", backend_count=3, healthy_count=2
        )
        toolbar_fn = make_toolbar(state)
        result = toolbar_fn()
        text = str(result)
        assert "localhost:8080" in text
        assert "2/3" in text

    @patch("argus_cli.repl.toolbar._ensure_loaded")
    @patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS, clear=True)
    def test_connected_degraded_toolbar(self, _mock_el):
        state = _make_state(
            is_connected=True, server_status="degraded", backend_count=1, healthy_count=0
        )
        toolbar_fn = make_toolbar(state)
        result = toolbar_fn()
        text = str(result)
        assert "localhost:8080" in text

    @patch("argus_cli.repl.toolbar._ensure_loaded")
    @patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS, clear=True)
    def test_disconnected_toolbar(self, _mock_el):
        state = _make_state(is_connected=False)
        toolbar_fn = make_toolbar(state)
        result = toolbar_fn()
        text = str(result)
        assert "disconnected" in text

    @patch("argus_cli.repl.toolbar._ensure_loaded")
    @patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS, clear=True)
    def test_toolbar_with_events(self, _mock_el):
        state = _make_state(is_connected=True, server_status="healthy", backend_count=0)
        state.connection.last_event_age = "5m ago"
        toolbar_fn = make_toolbar(state)
        result = toolbar_fn()
        text = str(result)
        assert "5m ago" in text

    @patch("argus_cli.repl.toolbar._ensure_loaded")
    @patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS, clear=True)
    def test_toolbar_with_scoped_backend(self, _mock_el):
        state = _make_state(is_connected=True, server_status="healthy", backend_count=0)
        state.session.scoped_backend = "test-scope"
        toolbar_fn = make_toolbar(state)
        result = toolbar_fn()
        text = str(result)
        assert "test-scope" in text
