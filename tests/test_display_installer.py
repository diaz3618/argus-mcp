"""Tests for argus_mcp.display.installer — runtime detection and display enums.

Covers:
- DisplayPhase enum values
- RuntimeKind enum values
- detect_runtime() for each backend type
- _RuntimeStyle existence
- InstallerDisplay build line accumulation and Live+Group rendering
"""

from __future__ import annotations

import io

from rich.console import Group

from argus_mcp.display.installer import (
    _STYLES,
    DisplayPhase,
    InstallerDisplay,
    RuntimeKind,
    detect_runtime,
)


class TestDisplayPhase:
    def test_all_values(self):
        expected = {
            "pending",
            "building",
            "initializing",
            "downloading",
            "retrying",
            "ready",
            "failed",
            "skipped",
        }
        assert {p.value for p in DisplayPhase} == expected

    def test_string_identity(self):
        assert DisplayPhase.PENDING.value == "pending"
        assert DisplayPhase.READY.value == "ready"
        assert DisplayPhase.FAILED.value == "failed"


class TestRuntimeKind:
    def test_all_values(self):
        expected = {"uvx", "npx", "docker", "python", "node", "remote", "unknown"}
        assert {k.value for k in RuntimeKind} == expected

    def test_string_identity(self):
        assert RuntimeKind.UVX.value == "uvx"
        assert RuntimeKind.DOCKER.value == "docker"
        assert RuntimeKind.REMOTE.value == "remote"


class TestDetectRuntime:
    def test_stdio_uvx(self):
        conf = {"type": "stdio", "command": "uvx", "params": {"args": ["some-pkg"]}}
        assert detect_runtime(conf) == RuntimeKind.UVX

    def test_stdio_npx(self):
        conf = {"type": "stdio", "command": "npx", "params": {"args": ["-y", "some-pkg"]}}
        assert detect_runtime(conf) == RuntimeKind.NPX

    def test_stdio_docker(self):
        conf = {"type": "stdio", "command": "docker", "params": {"args": ["run", "img"]}}
        assert detect_runtime(conf) == RuntimeKind.DOCKER

    def test_stdio_python(self):
        conf = {"type": "stdio", "command": "python", "params": {"args": ["-m", "mod"]}}
        assert detect_runtime(conf) == RuntimeKind.PYTHON

    def test_stdio_python3(self):
        conf = {"type": "stdio", "command": "python3", "params": {"args": ["-m", "mod"]}}
        assert detect_runtime(conf) == RuntimeKind.PYTHON

    def test_stdio_node(self):
        conf = {"type": "stdio", "command": "node", "params": {"args": ["script.js"]}}
        assert detect_runtime(conf) == RuntimeKind.NODE

    def test_stdio_unknown_command(self):
        conf = {"type": "stdio", "command": "custom-binary"}
        assert detect_runtime(conf) == RuntimeKind.UNKNOWN

    def test_sse_remote(self):
        conf = {"type": "sse", "url": "http://example.com/sse"}
        assert detect_runtime(conf) == RuntimeKind.REMOTE

    def test_streamable_http_remote(self):
        conf = {"type": "streamable-http", "url": "http://example.com/mcp"}
        assert detect_runtime(conf) == RuntimeKind.REMOTE

    def test_unknown_type(self):
        conf = {"type": "grpc"}
        assert detect_runtime(conf) == RuntimeKind.UNKNOWN

    def test_missing_params(self):
        conf = {"type": "stdio"}
        assert detect_runtime(conf) == RuntimeKind.UNKNOWN


class TestStyles:
    def test_every_runtime_kind_has_style(self):
        """Every RuntimeKind should have an entry in _STYLES."""
        for kind in RuntimeKind:
            assert kind in _STYLES, f"Missing style for {kind}"

    def test_style_has_expected_attrs(self):
        """Each style should have label and spinner_style attributes."""
        for kind, style in _STYLES.items():
            assert hasattr(style, "label"), f"{kind} style missing 'label'"
            assert hasattr(style, "spinner_style"), f"{kind} style missing 'spinner_style'"


def _make_display(*backends):
    """Create an InstallerDisplay with given backend configs for testing."""
    configs = {}
    for name, cmd in backends:
        configs[name] = {"type": "stdio", "command": cmd}
    stream = io.StringIO()
    return InstallerDisplay(configs, stream=stream)


class TestBuildLineAccumulation:
    """Tests for streaming build output accumulation and display."""

    def test_build_lines_accumulated(self):
        disp = _make_display(("rg", "npx"))
        disp.render_initial()
        try:
            disp.update("rg", phase="building", message="Step 1/5: FROM node:20-slim")
            disp.update("rg", phase="building", message="Step 2/5: RUN npm install")
            assert "rg" in disp._build_lines
            # First two lines are the auto-generated header:
            #   "$ docker build -t argus-mcp-rg ." and ""
            # followed by the two actual build messages.
            assert len(disp._build_lines["rg"]) == 4
            assert disp._build_lines["rg"][0] == "$ docker build -t argus-mcp-rg ."
            assert disp._build_lines["rg"][2] == "Step 1/5: FROM node:20-slim"
            assert disp._build_lines["rg"][3] == "Step 2/5: RUN npm install"
        finally:
            disp.finalize()

    def test_build_lines_cleared_on_phase_change(self):
        disp = _make_display(("rg", "npx"))
        disp.render_initial()
        try:
            disp.update("rg", phase="building", message="Step 1/5")
            assert "rg" in disp._build_lines
            disp.update("rg", phase="initializing", message="Connecting...")
            assert "rg" not in disp._build_lines
        finally:
            disp.finalize()

    def test_build_lines_cleared_on_ready(self):
        disp = _make_display(("rg", "npx"))
        disp.render_initial()
        try:
            disp.update("rg", phase="building", message="Step 1/5")
            disp.update("rg", phase="ready")
            assert "rg" not in disp._build_lines
        finally:
            disp.finalize()

    def test_build_lines_cleared_on_failed(self):
        disp = _make_display(("rg", "npx"))
        disp.render_initial()
        try:
            disp.update("rg", phase="building", message="Step 1/5")
            disp.update("rg", phase="failed", message="Build error")
            assert "rg" not in disp._build_lines
        finally:
            disp.finalize()

    def test_live_renderable_is_group_during_build(self):
        disp = _make_display(("rg", "npx"))
        disp.render_initial()
        try:
            disp.update("rg", phase="building", message="Step 1/5")
            renderable = disp._build_renderable()
            assert isinstance(renderable, Group)
        finally:
            disp.finalize()

    def test_active_cleared_after_build(self):
        disp = _make_display(("rg", "npx"))
        disp.render_initial()
        try:
            disp.update("rg", phase="building", message="Step 1/5")
            disp.update("rg", phase="initializing")
            # Build lines should be cleared when leaving BUILDING
            assert "rg" not in disp._build_lines
            # Active name should still be "rg" (now in initializing)
            assert disp._active_name == "rg"
        finally:
            disp.finalize()

    def test_build_lines_capped_at_200(self):
        disp = _make_display(("rg", "npx"))
        disp.render_initial()
        try:
            for i in range(250):
                disp.update("rg", phase="building", message=f"Line {i}")
            assert len(disp._build_lines["rg"]) <= 200
        finally:
            disp.finalize()

    def test_finalize_clears_build_lines(self):
        disp = _make_display(("rg", "npx"))
        disp.render_initial()
        disp.update("rg", phase="building", message="Step 1/5")
        disp.finalize()
        assert len(disp._build_lines) == 0
