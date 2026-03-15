"""Tests for argus_mcp.display.console — status display utilities.

Covers:
- gen_status_info() with various inputs
- disp_console_status() output formatting
- log_file_status() log writing
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from argus_mcp.display.console import (
    disp_console_status,
    gen_status_info,
    log_file_status,
)

# gen_status_info ─────────────────────────────────────────────────────


class TestGenStatusInfo:
    def test_minimal_no_app_state(self):
        info = gen_status_info(None, "Ready")
        assert info["status_msg"] == "Ready"
        assert info["host"] == "N/A"
        assert info["port"] == 0
        assert info["sse_url"] == "N/A"
        assert info["streamable_http_url"] == "N/A"
        assert info["err_msg"] is None
        assert "ts" in info
        assert info["tools"] == []
        assert info["resources"] == []
        assert info["prompts"] == []

    def test_with_app_state(self):
        state = MagicMock()
        state.host = "0.0.0.0"
        state.port = 8080
        state.actual_log_file = "my.log"
        state.file_log_level_configured = "DEBUG"
        state.transport_type = "sse"
        state.config_file_path = "/etc/argus.yaml"

        info = gen_status_info(state, "Running")
        assert info["host"] == "0.0.0.0"
        assert info["port"] == 8080
        assert "8080" in info["sse_url"]
        assert "8080" in info["streamable_http_url"]
        assert info["log_fpath"] == "my.log"
        assert info["log_lvl_cfg"] == "DEBUG"
        assert info["transport_type"] == "sse"
        assert info["cfg_fpath"] == "/etc/argus.yaml"

    def test_with_tools(self):
        tool = MagicMock()
        tool.name = "my-tool"
        tool.description = "A tool"
        info = gen_status_info(None, "Ready", tools=[tool])
        assert info["tools_count"] == 1
        assert len(info["tools"]) == 1

    def test_with_resources(self):
        res = MagicMock()
        res.name = "my-resource"
        info = gen_status_info(None, "Ready", resources=[res])
        assert info["resources_count"] == 1

    def test_with_prompts(self):
        prompt = MagicMock()
        prompt.name = "my-prompt"
        info = gen_status_info(None, "Ready", prompts=[prompt])
        assert info["prompts_count"] == 1

    def test_with_error(self):
        info = gen_status_info(None, "Error", err_msg="something broke")
        assert info["err_msg"] == "something broke"

    def test_with_server_counts(self):
        info = gen_status_info(None, "Ready", conn_svrs_num=3, total_svrs_num=5)
        assert info["conn_svrs_num"] == 3
        assert info["total_svrs_num"] == 5

    def test_with_route_map(self):
        rmap = {"tool1": ("backend-a", "orig")}
        info = gen_status_info(None, "Ready", route_map=rmap)
        assert info["route_map"] == rmap

    def test_optional_keys_absent_when_none(self):
        info = gen_status_info(None, "Ready")
        assert "tools_count" not in info
        assert "resources_count" not in info
        assert "prompts_count" not in info
        assert "conn_svrs_num" not in info
        assert "total_svrs_num" not in info
        assert "route_map" not in info


# disp_console_status ────────────────────────────────────────────────


class TestDispConsoleStatus:
    """Test console output formatting."""

    @pytest.fixture(autouse=True)
    def _reset_header(self):
        """Reset the header_printed state between tests."""
        if hasattr(disp_console_status, "header_printed"):
            delattr(disp_console_status, "header_printed")
        yield
        if hasattr(disp_console_status, "header_printed"):
            delattr(disp_console_status, "header_printed")

    def test_basic_output(self, capsys):
        info = gen_status_info(None, "Starting")
        disp_console_status("Boot", info)
        captured = capsys.readouterr()
        assert "Argus MCP" in captured.out
        assert "Starting" in captured.out

    def test_initialization_stage(self, capsys):
        state = MagicMock()
        state.host = "127.0.0.1"
        state.port = 9000
        state.actual_log_file = "argus.log"
        state.file_log_level_configured = "INFO"
        state.transport_type = "streamable-http"
        state.config_file_path = "/path/config.yaml"

        info = gen_status_info(state, "Initialized")
        disp_console_status("Initialization", info)
        captured = capsys.readouterr()
        assert "Argus MCP" in captured.out
        assert "Server Name" in captured.out
        assert "Endpoint" in captured.out

    def test_final_output(self, capsys):
        info = gen_status_info(None, "Shutdown")
        info["log_fpath"] = "logs/final.log"
        disp_console_status("Shutdown", info, is_final=True)
        captured = capsys.readouterr()
        assert "Shutdown" in captured.out
        assert "final.log" in captured.out

    def test_backend_counts_displayed(self, capsys):
        info = gen_status_info(None, "Running", conn_svrs_num=5, total_svrs_num=8)
        disp_console_status("Running", info)
        captured = capsys.readouterr()
        assert "5" in captured.out
        assert "8" in captured.out

    def test_tools_count_displayed(self, capsys):
        tool = MagicMock()
        tool.name = "t"
        info = gen_status_info(None, "Ready", tools=[tool, tool, tool])
        disp_console_status("Ready", info)
        captured = capsys.readouterr()
        assert "3" in captured.out

    def test_error_displayed(self, capsys):
        info = gen_status_info(None, "Error", err_msg="fatal crash")
        disp_console_status("Error", info)
        captured = capsys.readouterr()
        assert "fatal crash" in captured.out


# log_file_status ─────────────────────────────────────────────────────


class TestLogFileStatus:
    def test_basic_logging(self):
        info = gen_status_info(None, "Running")
        with patch("argus_mcp.display.console.logger") as mock_logger:
            log_file_status(info)
            mock_logger.log.assert_called_once()
            call_args = mock_logger.log.call_args
            assert call_args[0][0] == logging.INFO
            log_text = call_args[0][1]
            assert "Running" in log_text
            assert "SSE URL" in log_text

    def test_custom_log_level(self):
        info = gen_status_info(None, "Debug mode")
        with patch("argus_mcp.display.console.logger") as mock_logger:
            log_file_status(info, log_lvl=logging.DEBUG)
            assert mock_logger.log.call_args[0][0] == logging.DEBUG

    def test_error_included(self):
        info = gen_status_info(None, "Error", err_msg="bad config")
        with patch("argus_mcp.display.console.logger") as mock_logger:
            log_file_status(info)
            log_text = mock_logger.log.call_args[0][1]
            assert "bad config" in log_text

    def test_tool_details_logged(self):
        tool = MagicMock()
        tool.name = "my-tool"
        tool.description = "Does stuff"
        info = gen_status_info(None, "Ready", tools=[tool])
        with patch("argus_mcp.display.console.logger") as mock_logger:
            log_file_status(info)
            log_text = mock_logger.log.call_args[0][1]
            assert "my-tool" in log_text
            assert "Does stuff" in log_text

    def test_backend_counts_logged(self):
        info = gen_status_info(None, "OK", conn_svrs_num=2, total_svrs_num=3)
        with patch("argus_mcp.display.console.logger") as mock_logger:
            log_file_status(info)
            log_text = mock_logger.log.call_args[0][1]
            assert "2/3" in log_text
