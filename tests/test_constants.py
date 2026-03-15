"""Tests for argus_mcp.constants — shared constant values.

Covers:
- All expected constant names exist
- Types are correct
- Default values match expected configuration
"""

from __future__ import annotations

from argus_mcp import constants


class TestServerIdentity:
    def test_server_name(self):
        assert constants.SERVER_NAME == "Argus MCP"

    def test_server_version_format(self):
        """Version should be semver-like X.Y.Z."""
        parts = constants.SERVER_VERSION.split(".")
        assert len(parts) == 3
        for part in parts:
            assert part.isdigit()


class TestNetworkDefaults:
    def test_default_host(self):
        assert constants.DEFAULT_HOST == "127.0.0.1"

    def test_default_port(self):
        assert constants.DEFAULT_PORT == 9000
        assert isinstance(constants.DEFAULT_PORT, int)


class TestTransportPaths:
    def test_sse_path(self):
        assert constants.SSE_PATH == "/sse"
        assert constants.SSE_PATH.startswith("/")

    def test_post_messages_path(self):
        assert constants.POST_MESSAGES_PATH == "/messages/"

    def test_streamable_http_path(self):
        assert constants.STREAMABLE_HTTP_PATH == "/mcp"
        assert constants.STREAMABLE_HTTP_PATH.startswith("/")

    def test_management_api_prefix(self):
        assert constants.MANAGEMENT_API_PREFIX == "/manage/v1"
        assert constants.MANAGEMENT_API_PREFIX.startswith("/")


class TestLoggingDefaults:
    def test_log_dir(self):
        assert constants.LOG_DIR == "logs"
        assert isinstance(constants.LOG_DIR, str)

    def test_default_log_file(self):
        assert constants.DEFAULT_LOG_FILE.endswith(".log")

    def test_default_log_level(self):
        assert constants.DEFAULT_LOG_LEVEL in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


class TestTimeouts:
    def test_sse_local_start_delay(self):
        assert isinstance(constants.SSE_LOCAL_START_DELAY, (int, float))
        assert constants.SSE_LOCAL_START_DELAY > 0

    def test_mcp_init_timeout(self):
        assert isinstance(constants.MCP_INIT_TIMEOUT, (int, float))
        assert constants.MCP_INIT_TIMEOUT > 0

    def test_cap_fetch_timeout(self):
        assert isinstance(constants.CAP_FETCH_TIMEOUT, (int, float))
        assert constants.CAP_FETCH_TIMEOUT > 0

    def test_startup_timeout(self):
        assert isinstance(constants.STARTUP_TIMEOUT, (int, float))
        assert constants.STARTUP_TIMEOUT > 0


class TestRetryDefaults:
    def test_backend_retries(self):
        assert isinstance(constants.BACKEND_RETRIES, int)
        assert constants.BACKEND_RETRIES >= 0

    def test_backend_retry_delay(self):
        assert isinstance(constants.BACKEND_RETRY_DELAY, (int, float))
        assert constants.BACKEND_RETRY_DELAY > 0


class TestConsistency:
    """Cross-cutting consistency between constants."""

    def test_startup_timeout_greater_than_init(self):
        assert constants.STARTUP_TIMEOUT > constants.MCP_INIT_TIMEOUT

    def test_default_port_in_valid_range(self):
        assert 1 <= constants.DEFAULT_PORT <= 65535

    def test_all_paths_start_with_slash(self):
        """Paths that represent routes should start with /."""
        for attr in ("SSE_PATH", "STREAMABLE_HTTP_PATH", "MANAGEMENT_API_PREFIX"):
            val = getattr(constants, attr)
            assert val.startswith("/"), f"{attr}={val!r} should start with /"
