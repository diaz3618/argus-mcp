"""Tests for argus_cli.widgets — banner, panels, spinners, tables."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from rich.panel import Panel
from rich.table import Table

# Mock color palette used by all widget modules
_MOCK_COLORS = {
    "highlight": "#cdd6f4",
    "overlay": "#6c7086",
    "accent": "#f5c2e7",
    "text": "#cdd6f4",
    "secondary": "#a6adc8",
    "success": "#a6e3a1",
    "warning": "#f9e2af",
    "error": "#f38ba8",
    "info": "#89b4fa",
    "subtext": "#bac2de",
}

_MOCK_STATUS_STYLES = {
    "healthy": "bold green",
    "unhealthy": "bold red",
    "degraded": "bold yellow",
    "connected": "bold green",
    "disconnected": "bold red",
    "unknown": "dim",
}


# ── Banner ────────────────────────────────────────────────────────────


@patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS)
@patch("argus_cli.widgets.banner.get_console")
def test_render_banner_with_version_and_url(mock_console_fn):
    from argus_cli.widgets.banner import render_banner

    console = MagicMock()
    mock_console_fn.return_value = console
    render_banner(version="1.2.3", server_url="http://localhost:8080")
    assert console.print.call_count >= 2  # art + meta + separator


@patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS)
@patch("argus_cli.widgets.banner.get_console")
def test_render_banner_no_args(mock_console_fn):
    from argus_cli.widgets.banner import render_banner

    console = MagicMock()
    mock_console_fn.return_value = console
    render_banner()
    assert console.print.called


@patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS)
@patch("argus_cli.widgets.banner.get_console")
def test_render_banner_version_only(mock_console_fn):
    from argus_cli.widgets.banner import render_banner

    console = MagicMock()
    mock_console_fn.return_value = console
    render_banner(version="0.9.0")
    assert console.print.called


# ── Panels ────────────────────────────────────────────────────────────


@patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS)
def test_info_panel_returns_panel():
    from argus_cli.widgets.panels import info_panel

    result = info_panel("Test", "Some content")
    assert isinstance(result, Panel)


@patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS)
def test_info_panel_with_subtitle():
    from argus_cli.widgets.panels import info_panel

    result = info_panel("Title", "Body", subtitle="sub")
    assert isinstance(result, Panel)


@patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS)
def test_key_value_panel_dict():
    from argus_cli.widgets.panels import key_value_panel

    result = key_value_panel("KV", {"name": "argus", "version": "1.0"})
    assert isinstance(result, Panel)


@patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS)
def test_key_value_panel_tuples():
    from argus_cli.widgets.panels import key_value_panel

    result = key_value_panel("KV", [("a", 1), ("b", 2)])
    assert isinstance(result, Panel)


@patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS)
def test_key_value_panel_empty():
    from argus_cli.widgets.panels import key_value_panel

    result = key_value_panel("Empty", {})
    assert isinstance(result, Panel)


@patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS)
def test_detail_panel_with_sections():
    from argus_cli.widgets.panels import detail_panel

    result = detail_panel(
        "Detail",
        {"name": "test", "status": "ok"},
        {"Notes": "Some notes here"},
    )
    assert isinstance(result, Panel)


@patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS)
def test_detail_panel_no_sections():
    from argus_cli.widgets.panels import detail_panel

    result = detail_panel("Detail", {"key": "val"})
    assert isinstance(result, Panel)


# ── Spinners ──────────────────────────────────────────────────────────


@patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS)
@patch("argus_cli.widgets.spinners.get_console")
def test_live_status_context_manager(mock_console_fn):
    from argus_cli.widgets.spinners import live_status

    console = MagicMock()
    mock_console_fn.return_value = console
    console.status.return_value.__enter__ = MagicMock()
    console.status.return_value.__exit__ = MagicMock(return_value=False)

    with live_status("Loading..."):
        pass
    console.status.assert_called_once()


@patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS)
@patch("argus_cli.widgets.spinners.get_console")
def test_progress_bar_returns_progress(mock_console_fn):
    from rich.progress import Progress

    from argus_cli.widgets.spinners import progress_bar

    console = MagicMock()
    mock_console_fn.return_value = console
    result = progress_bar(10, description="Testing")
    assert isinstance(result, Progress)


@patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS)
@patch("argus_cli.widgets.spinners.get_console")
def test_step_progress_executes_steps(mock_console_fn):
    from argus_cli.widgets.spinners import step_progress

    console = MagicMock()
    mock_console_fn.return_value = console
    console.status.return_value.__enter__ = MagicMock()
    console.status.return_value.__exit__ = MagicMock(return_value=False)

    step1 = MagicMock(return_value="result1")
    step2 = MagicMock(return_value="result2")
    results = step_progress([("Step 1", step1), ("Step 2", step2)])
    assert results == ["result1", "result2"]
    step1.assert_called_once()
    step2.assert_called_once()


@patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS)
@patch("argus_cli.widgets.spinners.get_console")
def test_step_progress_non_callable(mock_console_fn):
    from argus_cli.widgets.spinners import step_progress

    console = MagicMock()
    mock_console_fn.return_value = console
    console.status.return_value.__enter__ = MagicMock()
    console.status.return_value.__exit__ = MagicMock(return_value=False)

    results = step_progress([("Static value", "just a string")])
    assert results == ["just a string"]


# ── Tables ────────────────────────────────────────────────────────────


@patch.dict("argus_cli.theme.STATUS_STYLES", _MOCK_STATUS_STYLES)
@patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS)
def test_simple_table_returns_table():
    from argus_cli.widgets.tables import simple_table

    result = simple_table("Test", ["Name", "Status"], [["a", "ok"], ["b", "err"]])
    assert isinstance(result, Table)


@patch.dict("argus_cli.theme.STATUS_STYLES", _MOCK_STATUS_STYLES)
@patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS)
def test_simple_table_empty_rows():
    from argus_cli.widgets.tables import simple_table

    result = simple_table("Empty", ["Col1"], [])
    assert isinstance(result, Table)


@patch.dict("argus_cli.theme.STATUS_STYLES", _MOCK_STATUS_STYLES)
@patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS)
def test_status_table_with_styling():
    from argus_cli.widgets.tables import status_table

    result = status_table(
        "Status",
        ["name", "status"],
        [{"name": "a", "status": "healthy"}, {"name": "b", "status": "unhealthy"}],
    )
    assert isinstance(result, Table)


@patch.dict("argus_cli.theme.STATUS_STYLES", _MOCK_STATUS_STYLES)
@patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS)
def test_auto_table_from_dicts():
    from argus_cli.widgets.tables import auto_table

    data = [{"name": "x", "value": 1}, {"name": "y", "value": 2}]
    result = auto_table("Auto", data)
    assert isinstance(result, Table)


@patch.dict("argus_cli.theme.STATUS_STYLES", _MOCK_STATUS_STYLES)
@patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS)
def test_auto_table_empty_data():
    from argus_cli.widgets.tables import auto_table

    result = auto_table("Empty", [])
    assert isinstance(result, Table)


@patch.dict("argus_cli.theme.STATUS_STYLES", _MOCK_STATUS_STYLES)
@patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS)
def test_auto_table_with_key_field():
    from argus_cli.widgets.tables import auto_table

    data = [{"name": "a", "status": "healthy"}]
    result = auto_table("Keyed", data, key_field="status")
    assert isinstance(result, Table)


@patch.dict("argus_cli.theme.STATUS_STYLES", _MOCK_STATUS_STYLES)
@patch.dict("argus_cli.theme.COLORS", _MOCK_COLORS)
def test_auto_table_custom_columns():
    from argus_cli.widgets.tables import auto_table

    data = [{"a": 1, "b": 2, "c": 3}]
    result = auto_table("Custom", data, columns=["a", "c"])
    assert isinstance(result, Table)
