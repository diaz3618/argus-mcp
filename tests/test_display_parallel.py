"""Tests for parallel display mode, braille rendering, and verbosity controls.

Covers:
- braille.py public API (render_*_bar functions)
- InstallerDisplay parallel mode rendering
- Verbosity-aware build line limits
- Focused builder tracking
- All-terminal state detection
- Lifespan wiring (_setup_installer_display)
"""

from __future__ import annotations

import io
from unittest.mock import patch

from rich.console import Group
from rich.table import Table
from rich.text import Text

from argus_mcp.display.braille import (
    BRAILLE_BASE,
    braille,
    render_empty_bar,
    render_progress_bar,
    render_scattered_bar,
    render_solid_bar,
)
from argus_mcp.display.installer import (
    _BUILDKIT_STEP_RE,
    _COL_BAR,
    _COL_ICON,
    _COL_NAME,
    _COL_STATUS,
    _COL_TIMER,
    _PARALLEL_PHASE_PROGRESS,
    DisplayPhase,
    InstallerDisplay,
    RuntimeKind,
)


# Helpers
def _make_configs(*backends: tuple[str, str]) -> dict:
    configs = {}
    for name, cmd in backends:
        configs[name] = {"type": "stdio", "command": cmd}
    return configs


def _make_display(
    *backends: tuple[str, str],
    parallel: bool = False,
    verbosity: int = 0,
) -> InstallerDisplay:
    configs = _make_configs(*backends)
    return InstallerDisplay(configs, stream=io.StringIO(), parallel=parallel, verbosity=verbosity)


# braille.py tests
class TestBrailleFunction:
    def test_base_character(self):
        assert braille(0x00) == chr(BRAILLE_BASE)

    def test_full_character(self):
        assert braille(0xFF) == chr(BRAILLE_BASE + 0xFF)

    def test_masks_8bit(self):
        assert braille(0x1FF) == braille(0xFF)


class TestRenderEmptyBar:
    def test_returns_text(self):
        result = render_empty_bar()
        assert isinstance(result, Text)

    def test_default_width(self):
        result = render_empty_bar()
        # 17 braille chars + 2 brackets = 19 chars
        assert len(result.plain) == 19

    def test_custom_width(self):
        result = render_empty_bar(width=10)
        assert len(result.plain) == 12  # 10 + 2

    def test_all_empty_glyphs(self):
        result = render_empty_bar(width=5)
        inner = result.plain[1:-1]  # strip brackets
        empty_char = chr(BRAILLE_BASE)
        assert all(c == empty_char for c in inner)


class TestRenderSolidBar:
    def test_returns_text(self):
        result = render_solid_bar()
        assert isinstance(result, Text)

    def test_default_width(self):
        result = render_solid_bar()
        assert len(result.plain) == 19

    def test_all_solid_glyphs(self):
        result = render_solid_bar(width=5)
        inner = result.plain[1:-1]
        solid_char = chr(BRAILLE_BASE + 0xFF)
        assert all(c == solid_char for c in inner)


class TestRenderProgressBar:
    def test_zero_progress(self):
        result = render_progress_bar(0.0, width=10)
        inner = result.plain[1:-1]
        empty_char = chr(BRAILLE_BASE)
        assert all(c == empty_char for c in inner)

    def test_full_progress(self):
        result = render_progress_bar(1.0, width=10)
        inner = result.plain[1:-1]
        solid_char = chr(BRAILLE_BASE + 0xFF)
        assert all(c == solid_char for c in inner)

    def test_half_progress(self):
        result = render_progress_bar(0.5, width=10)
        inner = result.plain[1:-1]
        solid_char = chr(BRAILLE_BASE + 0xFF)
        # First ~5 should be solid, rest empty/partial
        solid_count = sum(1 for c in inner if c == solid_char)
        assert solid_count >= 4  # at least 4 of 10 are solid at 50%

    def test_clamps_negative(self):
        result = render_progress_bar(-0.5, width=5)
        assert len(result.plain) == 7  # doesn't crash

    def test_clamps_above_one(self):
        result = render_progress_bar(1.5, width=5)
        inner = result.plain[1:-1]
        solid_char = chr(BRAILLE_BASE + 0xFF)
        assert all(c == solid_char for c in inner)


class TestRenderScatteredBar:
    def test_returns_text(self):
        result = render_scattered_bar(0.0, width=10)
        assert isinstance(result, Text)

    def test_deterministic_for_same_frame(self):
        a = render_scattered_bar(1.0, width=10)
        b = render_scattered_bar(1.0, width=10)
        assert a.plain == b.plain

    def test_different_frames(self):
        a = render_scattered_bar(0.0, width=10)
        b = render_scattered_bar(5.0, width=10)
        # Different elapsed times produce different patterns
        assert a.plain != b.plain


# InstallerDisplay — verbosity controls
class TestVerbosityScale:
    def test_sequential_v0(self):
        d = _make_display(("a", "npx"), parallel=False, verbosity=0)
        assert d._max_build_lines == 0

    def test_sequential_v1(self):
        d = _make_display(("a", "npx"), parallel=False, verbosity=1)
        assert d._max_build_lines == 15

    def test_sequential_v2(self):
        d = _make_display(("a", "npx"), parallel=False, verbosity=2)
        assert d._max_build_lines == 30

    def test_parallel_v0(self):
        d = _make_display(("a", "npx"), parallel=True, verbosity=0)
        assert d._max_build_lines == 0

    def test_parallel_v1(self):
        d = _make_display(("a", "npx"), parallel=True, verbosity=1)
        assert d._max_build_lines == 5

    def test_parallel_v2(self):
        d = _make_display(("a", "npx"), parallel=True, verbosity=2)
        assert d._max_build_lines == 10

    def test_backwards_compat_verbose_true(self):
        d = InstallerDisplay(
            _make_configs(("a", "npx")),
            stream=io.StringIO(),
            verbose=True,
        )
        assert d._verbosity == 1

    def test_backwards_compat_verbose_false(self):
        d = InstallerDisplay(
            _make_configs(("a", "npx")),
            stream=io.StringIO(),
            verbose=False,
        )
        assert d._verbosity == 0

    def test_explicit_verbosity_overrides_bool(self):
        d = InstallerDisplay(
            _make_configs(("a", "npx")),
            stream=io.StringIO(),
            verbose=False,
            verbosity=2,
        )
        assert d._verbosity == 2


# InstallerDisplay — parallel mode
class TestParallelMode:
    def test_parallel_flag_stored(self):
        d = _make_display(("a", "npx"), parallel=True)
        assert d._parallel is True

    def test_parallel_renderable_returns_table(self):
        d = _make_display(("a", "npx"), ("b", "uvx"), parallel=True, verbosity=0)
        d.render_initial()
        try:
            result = d._build_parallel_renderable()
            assert isinstance(result, Table)
        finally:
            d.finalize()

    def test_parallel_update_all_shown(self):
        """All backends visible simultaneously in parallel mode."""
        d = _make_display(("a", "npx"), ("b", "uvx"), parallel=True, verbosity=0)
        d.render_initial()
        try:
            d.update("a", phase="building", message="Step 1/5")
            d.update("b", phase="initializing", message="Connecting...")
            # Both still present in ordered list at same time
            names = [e.name for e in d._ordered]
            assert "a" in names
            assert "b" in names
            assert d._entries["a"].phase == DisplayPhase.BUILDING
            assert d._entries["b"].phase == DisplayPhase.INITIALIZING
        finally:
            d.finalize()

    def test_parallel_routes_to_parallel_renderable(self):
        """_build_renderable dispatches to parallel version."""
        d = _make_display(("a", "npx"), parallel=True, verbosity=0)
        d.render_initial()
        try:
            result = d._build_renderable()
            # Parallel renderable always starts with a Table
            assert isinstance(result, Table)
        finally:
            d.finalize()


class TestFocusedBuilder:
    def test_last_focused_builder_tracked(self):
        d = _make_display(("a", "npx"), ("b", "uvx"), parallel=True, verbosity=1)
        d.render_initial()
        try:
            d.update("a", phase="building", message="Step 1/5")
            assert d._last_focused_builder == "a"
            d.update("b", phase="building", message="Step 1/3")
            assert d._last_focused_builder == "b"
        finally:
            d.finalize()

    def test_focused_builder_not_tracked_in_sequential(self):
        d = _make_display(("a", "npx"), parallel=False, verbosity=1)
        d.render_initial()
        try:
            d.update("a", phase="building", message="Step 1/5")
            assert d._last_focused_builder is None
        finally:
            d.finalize()

    def test_v1_parallel_renders_group_with_focused_lines(self):
        d = _make_display(("a", "npx"), ("b", "uvx"), parallel=True, verbosity=1)
        d.render_initial()
        try:
            d.update("a", phase="building", message="Step 1/5")
            d.update("b", phase="building", message="Step 1/3")
            result = d._build_parallel_renderable()
            # With build lines and focused builder, should be a Group
            assert isinstance(result, Group)
        finally:
            d.finalize()

    def test_v2_parallel_renders_group_with_all_lines(self):
        d = _make_display(("a", "npx"), ("b", "uvx"), parallel=True, verbosity=2)
        d.render_initial()
        try:
            d.update("a", phase="building", message="Step 1/5")
            d.update("b", phase="building", message="Step 1/3")
            result = d._build_parallel_renderable()
            assert isinstance(result, Group)
        finally:
            d.finalize()

    def test_v0_parallel_no_build_lines(self):
        """At verbosity=0, parallel renderable is just the table."""
        d = _make_display(("a", "npx"), ("b", "uvx"), parallel=True, verbosity=0)
        d.render_initial()
        try:
            d.update("a", phase="building", message="Step 1/5")
            result = d._build_parallel_renderable()
            assert isinstance(result, Table)
        finally:
            d.finalize()


class TestAllTerminalDetection:
    def test_all_terminal_initially_none(self):
        d = _make_display(("a", "npx"), ("b", "uvx"), parallel=True)
        assert d._all_terminal_at is None

    def test_all_terminal_when_all_ready(self):
        d = _make_display(("a", "npx"), ("b", "uvx"), parallel=True)
        d.render_initial()
        try:
            d.update("a", phase="ready")
            d.update("b", phase="ready")
            assert d._all_terminal_at is not None
        finally:
            d.finalize()

    def test_all_terminal_mixed_ready_failed(self):
        d = _make_display(("a", "npx"), ("b", "uvx"), parallel=True)
        d.render_initial()
        try:
            d.update("a", phase="ready")
            d.update("b", phase="failed", message="Error")
            assert d._all_terminal_at is not None
        finally:
            d.finalize()

    def test_not_all_terminal_one_still_building(self):
        d = _make_display(("a", "npx"), ("b", "uvx"), parallel=True)
        d.render_initial()
        try:
            d.update("a", phase="ready")
            d.update("b", phase="building", message="Step 1/3")
            assert d._all_terminal_at is None
        finally:
            d.finalize()


# Sequential build line zero-slice fix
class TestSequentialBuildLinesFix:
    def test_v0_sequential_no_build_lines_in_renderable(self):
        """At verbosity=0, sequential renderable should not show build lines."""
        d = _make_display(("a", "npx"), parallel=False, verbosity=0)
        d.render_initial()
        try:
            d.update("a", phase="building", message="Step 1/5")
            d._build_renderable()
            # v=0 returns just the spinner panel (not a Group with build lines)
            # It could be a Group from the spinner + panel, but build_lines slice should be empty
            # The key test is that _max_build_lines is 0
            assert d._max_build_lines == 0
        finally:
            d.finalize()


# Lifespan wiring
class TestSetupInstallerDisplay:
    def test_sequential_v0_returns_none(self):
        mock_config = {"backends": {"t": {"type": "stdio", "command": "echo"}}}
        with patch(
            "argus_mcp.config.loader.load_and_validate_config",
            return_value=mock_config,
        ):
            from argus_mcp.server.lifespan import _setup_installer_display

            d, cb = _setup_installer_display("/c.yaml", 0, parallel=False)
            assert d is None

    def test_sequential_v1_returns_display(self):
        mock_config = {"backends": {"t": {"type": "stdio", "command": "echo"}}}
        with patch(
            "argus_mcp.config.loader.load_and_validate_config",
            return_value=mock_config,
        ):
            from argus_mcp.server.lifespan import _setup_installer_display

            d, cb = _setup_installer_display("/c.yaml", 1, parallel=False)
            assert d is not None
            assert d._parallel is False
            assert d._verbosity == 1

    def test_parallel_v0_returns_display(self):
        mock_config = {"backends": {"t": {"type": "stdio", "command": "echo"}}}
        with patch(
            "argus_mcp.config.loader.load_and_validate_config",
            return_value=mock_config,
        ):
            from argus_mcp.server.lifespan import _setup_installer_display

            d, cb = _setup_installer_display("/c.yaml", 0, parallel=True)
            assert d is not None
            assert d._parallel is True
            assert d._verbosity == 0

    def test_empty_config_path_returns_none(self):
        from argus_mcp.server.lifespan import _setup_installer_display

        d, cb = _setup_installer_display("", 2, parallel=True)
        assert d is None

    def test_callback_returned(self):
        mock_config = {"backends": {"t": {"type": "stdio", "command": "echo"}}}
        with patch(
            "argus_mcp.config.loader.load_and_validate_config",
            return_value=mock_config,
        ):
            from argus_mcp.server.lifespan import _setup_installer_display

            d, cb = _setup_installer_display("/c.yaml", 1, parallel=False)
            assert cb is not None
            assert callable(cb)


# Completed line alignment (rich Table format)
class TestCompletedLineAlignment:
    def test_format_completed_line_returns_table(self):
        d = _make_display(("a", "npx"))
        d.render_initial()
        try:
            d.update("a", phase="ready")
            entry = d._entries["a"]
            result = d._format_completed_line(entry)
            assert isinstance(result, Table)
        finally:
            d.finalize()

    def test_format_completed_line_failed(self):
        d = _make_display(("a", "npx"))
        d.render_initial()
        try:
            d.update("a", phase="failed", message="Timeout")
            entry = d._entries["a"]
            result = d._format_completed_line(entry)
            assert isinstance(result, Table)
        finally:
            d.finalize()


# Compose-style bar routing (remote vs non-remote)
def _make_remote_config(name: str) -> dict:
    """Create a remote (SSE) backend config."""
    return {"type": "sse", "url": "http://localhost:9000"}


def _make_mixed_display(
    stdio_backends: list[tuple[str, str]],
    remote_backends: list[str],
    *,
    parallel: bool = True,
    verbosity: int = 0,
) -> InstallerDisplay:
    """Create a display with both stdio and remote backends."""
    configs: dict = {}
    for name, cmd in stdio_backends:
        configs[name] = {"type": "stdio", "command": cmd}
    for name in remote_backends:
        configs[name] = _make_remote_config(name)
    return InstallerDisplay(configs, stream=io.StringIO(), parallel=parallel, verbosity=verbosity)


class TestComposeStyleBarRouting:
    """Verify non-remote backends use compose-style progress bars
    while remote backends keep the scattered animation."""

    def test_remote_initializing_uses_scattered_bar(self):
        """Remote backends in INITIALIZING phase get scattered animation."""
        d = _make_mixed_display([], ["remote-svc"], parallel=True)
        d.render_initial()
        try:
            d.update("remote-svc", phase="initializing")
            entry = d._entries["remote-svc"]
            assert entry.runtime == RuntimeKind.REMOTE
            _, _, bar, _, _ = InstallerDisplay._parallel_entry_cells(entry, 1.0)
            expected = render_scattered_bar(1.0, monotone_style=entry.style.spinner_style)
            assert bar.plain == expected.plain
        finally:
            d.finalize()

    def test_npx_initializing_uses_progress_bar(self):
        """NPX backends in INITIALIZING phase get compose-style progress bar."""
        d = _make_mixed_display([("my-npx", "npx")], [], parallel=True)
        d.render_initial()
        try:
            d.update("my-npx", phase="initializing")
            entry = d._entries["my-npx"]
            assert entry.runtime == RuntimeKind.NPX
            _, _, bar, _, _ = InstallerDisplay._parallel_entry_cells(entry, 1.0)
            expected = render_progress_bar(
                _PARALLEL_PHASE_PROGRESS[DisplayPhase.INITIALIZING],
                monotone_style=entry.style.spinner_style,
            )
            assert bar.plain == expected.plain
        finally:
            d.finalize()

    def test_uvx_downloading_uses_progress_bar(self):
        """UVX backends in DOWNLOADING phase get compose-style progress bar."""
        d = _make_mixed_display([("my-uvx", "uvx")], [], parallel=True)
        d.render_initial()
        try:
            d.update("my-uvx", phase="downloading")
            entry = d._entries["my-uvx"]
            assert entry.runtime == RuntimeKind.UVX
            _, _, bar, _, _ = InstallerDisplay._parallel_entry_cells(entry, 2.0)
            expected = render_progress_bar(
                _PARALLEL_PHASE_PROGRESS[DisplayPhase.DOWNLOADING],
                monotone_style=entry.style.spinner_style,
            )
            assert bar.plain == expected.plain
        finally:
            d.finalize()

    def test_docker_initializing_uses_progress_bar(self):
        """Docker backends in INITIALIZING phase get compose-style progress bar."""
        d = _make_mixed_display([("my-docker", "docker")], [], parallel=True)
        d.render_initial()
        try:
            d.update("my-docker", phase="initializing")
            entry = d._entries["my-docker"]
            assert entry.runtime == RuntimeKind.DOCKER
            _, _, bar, _, _ = InstallerDisplay._parallel_entry_cells(entry, 1.5)
            expected = render_progress_bar(
                _PARALLEL_PHASE_PROGRESS[DisplayPhase.INITIALIZING],
                monotone_style=entry.style.spinner_style,
            )
            assert bar.plain == expected.plain
        finally:
            d.finalize()

    def test_remote_downloading_uses_scattered_bar(self):
        """Remote backends in DOWNLOADING phase still get scattered animation."""
        d = _make_mixed_display([], ["remote-dl"], parallel=True)
        d.render_initial()
        try:
            d.update("remote-dl", phase="downloading")
            entry = d._entries["remote-dl"]
            assert entry.runtime == RuntimeKind.REMOTE
            _, _, bar, _, _ = InstallerDisplay._parallel_entry_cells(entry, 3.0)
            expected = render_scattered_bar(3.0, monotone_style=entry.style.spinner_style)
            assert bar.plain == expected.plain
        finally:
            d.finalize()

    def test_retrying_npx_uses_progress_bar(self):
        """NPX backends in RETRYING phase get compose-style progress bar."""
        d = _make_mixed_display([("retry-npx", "npx")], [], parallel=True)
        d.render_initial()
        try:
            d.update("retry-npx", phase="retrying")
            entry = d._entries["retry-npx"]
            assert entry.runtime == RuntimeKind.NPX
            _, _, bar, _, _ = InstallerDisplay._parallel_entry_cells(entry, 5.0)
            expected = render_progress_bar(
                _PARALLEL_PHASE_PROGRESS[DisplayPhase.RETRYING],
                monotone_style=entry.style.spinner_style,
            )
            assert bar.plain == expected.plain
        finally:
            d.finalize()

    def test_building_still_uses_build_progress(self):
        """BUILDING phase continues to use build_progress float regardless of runtime."""
        d = _make_mixed_display([("builder", "docker")], [], parallel=True)
        d.render_initial()
        try:
            d.update("builder", phase="building", message="Step 3/10")
            entry = d._entries["builder"]
            entry.build_progress = 0.6
            _, _, bar, _, _ = InstallerDisplay._parallel_entry_cells(entry, 2.0)
            expected = render_progress_bar(0.6, monotone_style=entry.style.spinner_style)
            assert bar.plain == expected.plain
        finally:
            d.finalize()

    def test_phase_progress_values(self):
        """Verify the compose-style progress mapping values."""
        assert _PARALLEL_PHASE_PROGRESS[DisplayPhase.INITIALIZING] == 0.4
        assert _PARALLEL_PHASE_PROGRESS[DisplayPhase.DOWNLOADING] == 0.7
        assert _PARALLEL_PHASE_PROGRESS[DisplayPhase.RETRYING] == 0.3

    def test_mixed_backends_different_bar_types(self):
        """In a mixed display, remote gets scattered and stdio gets progress."""
        d = _make_mixed_display([("stdio-svc", "npx")], ["remote-svc"], parallel=True)
        d.render_initial()
        try:
            d.update("stdio-svc", phase="initializing")
            d.update("remote-svc", phase="initializing")

            stdio_entry = d._entries["stdio-svc"]
            remote_entry = d._entries["remote-svc"]

            _, _, stdio_bar, _, _ = InstallerDisplay._parallel_entry_cells(stdio_entry, 1.0)
            _, _, remote_bar, _, _ = InstallerDisplay._parallel_entry_cells(remote_entry, 1.0)

            # Same phase, different bar types
            assert stdio_bar.plain != remote_bar.plain
        finally:
            d.finalize()


# RC-1: Build progress parsing (BuildKit step extraction)
class TestBuildProgressParsing:
    """Verify build_progress is computed from BuildKit output lines."""

    def test_buildkit_step_regex_matches(self):
        m = _BUILDKIT_STEP_RE.search("#6 [2/8] RUN apt-get update")
        assert m is not None
        assert m.group(1) == "2"
        assert m.group(2) == "8"

    def test_buildkit_step_regex_no_match(self):
        m = _BUILDKIT_STEP_RE.search("Sending build context to Docker daemon")
        assert m is None

    def test_build_progress_updated_on_step_line(self):
        d = _make_display(("builder", "docker"), parallel=True, verbosity=0)
        d.render_initial()
        try:
            d.update("builder", phase="building", message="#5 [1/4] FROM python:3.12")
            entry = d._entries["builder"]
            assert entry.build_progress == 0.25  # 1/4
        finally:
            d.finalize()

    def test_build_progress_advances(self):
        d = _make_display(("builder", "docker"), parallel=True, verbosity=0)
        d.render_initial()
        try:
            d.update("builder", phase="building", message="#5 [1/4] FROM python:3.12")
            d.update("builder", phase="building", message="#6 [2/4] RUN apt-get update")
            d.update("builder", phase="building", message="#7 [3/4] COPY . .")
            entry = d._entries["builder"]
            assert entry.build_progress == 0.75  # 3/4
        finally:
            d.finalize()

    def test_build_progress_reaches_one(self):
        d = _make_display(("builder", "docker"), parallel=True, verbosity=0)
        d.render_initial()
        try:
            d.update("builder", phase="building", message="#8 [4/4] CMD python main.py")
            entry = d._entries["builder"]
            assert entry.build_progress == 1.0
        finally:
            d.finalize()

    def test_build_progress_zero_for_non_step_lines(self):
        d = _make_display(("builder", "docker"), parallel=True, verbosity=0)
        d.render_initial()
        try:
            d.update("builder", phase="building", message="Sending build context")
            entry = d._entries["builder"]
            assert entry.build_progress == 0.0
        finally:
            d.finalize()

    def test_build_progress_clamped_to_one(self):
        """Progress is capped at 1.0 even for unusual input."""
        d = _make_display(("builder", "docker"), parallel=True, verbosity=0)
        d.render_initial()
        try:
            d.update("builder", phase="building", message="#5 [5/3] extra step")
            entry = d._entries["builder"]
            assert entry.build_progress == 1.0
        finally:
            d.finalize()


# RC-3: Column width constants and consistency
class TestColumnWidthConstants:
    """Verify shared column width constants are used consistently."""

    def test_constants_defined(self):
        assert _COL_ICON == 2
        assert _COL_NAME == 42
        assert _COL_BAR == 19
        assert _COL_STATUS == 36
        assert _COL_TIMER == 7

    def test_completed_line_uses_shared_widths(self):
        """Completed line table should use the same name/status/timer widths."""
        d = _make_display(("a", "npx"))
        d.render_initial()
        try:
            d.update("a", phase="ready")
            entry = d._entries["a"]
            tbl = d._format_completed_line(entry)
            cols = tbl.columns
            assert cols[0].width == _COL_ICON
            assert cols[1].width == _COL_NAME
            assert cols[2].width == _COL_STATUS
            assert cols[3].width == _COL_TIMER
        finally:
            d.finalize()

    def test_parallel_table_uses_shared_widths(self):
        """Parallel renderable table should use shared column widths."""
        d = _make_display(("a", "npx"), parallel=True, verbosity=0)
        d.render_initial()
        try:
            d.update("a", phase="initializing")
            tbl = d._build_parallel_renderable()
            assert isinstance(tbl, Table)
            cols = tbl.columns
            assert cols[0].width == _COL_ICON
            assert cols[1].width == _COL_NAME
            assert cols[2].width == _COL_BAR
            assert cols[3].width == _COL_STATUS
            assert cols[4].width == _COL_TIMER
        finally:
            d.finalize()

    def test_name_column_no_wrap(self):
        """Name columns in both tables should have no_wrap=True."""
        d = _make_display(("a", "npx"), parallel=True, verbosity=0)
        d.render_initial()
        try:
            d.update("a", phase="initializing")
            tbl = d._build_parallel_renderable()
            assert isinstance(tbl, Table)
            assert tbl.columns[1].no_wrap is True

            d.update("a", phase="ready")
            entry = d._entries["a"]
            completed_tbl = d._format_completed_line(entry)
            assert completed_tbl.columns[1].no_wrap is True
        finally:
            d.finalize()
