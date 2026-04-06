"""Status endpoint information disclosure tests (SEC-17).

Verify that when redact_status is enabled, the /status and /backends
endpoints strip sensitive internal details like config file paths,
transport URLs, bind addresses, error messages, and health conditions.
"""

from __future__ import annotations

import pytest

from argus_mcp.server.management.router import _redact_backends_response, _redact_status_response

pytestmark = [pytest.mark.security]


class TestStatusRedaction:
    """Verify _redact_status_response strips sensitive fields."""

    def test_redacts_config_file_path(self):
        """Config file path should be replaced with a generic indicator."""
        status = {
            "service": {"name": "argus", "version": "1.0.0", "state": "running"},
            "config": {
                "file_path": "/home/user/.config/argus/config.yaml",
                "loaded_at": "2025-01-01T00:00:00",
                "backend_count": 3,
            },
            "transport": {
                "sse_url": "http://0.0.0.0:8080/sse",
                "streamable_http_url": "http://0.0.0.0:8080/mcp",
                "host": "0.0.0.0",
                "port": 8080,
            },
            "feature_flags": {"health_checks": True},
        }
        redacted = _redact_status_response(status)
        assert redacted["config"]["file_path"] == "[redacted]"

    def test_redacts_transport_urls(self):
        """Transport URLs and bind host/port should be redacted."""
        status = {
            "service": {"name": "argus", "version": "1.0.0", "state": "running"},
            "config": {
                "file_path": "/etc/argus/config.yaml",
                "loaded_at": None,
                "backend_count": 1,
            },
            "transport": {
                "sse_url": "http://10.0.0.5:9090/sse",
                "streamable_http_url": "http://10.0.0.5:9090/mcp",
                "host": "10.0.0.5",
                "port": 9090,
            },
            "feature_flags": {},
        }
        redacted = _redact_status_response(status)
        assert redacted["transport"]["host"] == "[redacted]"
        assert redacted["transport"]["port"] == 0
        assert "[redacted]" in redacted["transport"]["sse_url"]

    def test_preserves_service_info(self):
        """Service name, version, and state are NOT redacted."""
        status = {
            "service": {
                "name": "argus",
                "version": "1.0.0",
                "state": "running",
                "uptime_seconds": 3600,
            },
            "config": {"file_path": "/some/path", "loaded_at": None, "backend_count": 0},
            "transport": {"sse_url": "", "streamable_http_url": None, "host": "", "port": 0},
            "feature_flags": {},
        }
        redacted = _redact_status_response(status)
        assert redacted["service"]["name"] == "argus"
        assert redacted["service"]["version"] == "1.0.0"
        assert redacted["service"]["state"] == "running"

    def test_preserves_backend_count(self):
        """Backend count is safe to expose."""
        status = {
            "service": {"name": "argus", "version": "1.0.0", "state": "running"},
            "config": {"file_path": "/path", "loaded_at": None, "backend_count": 5},
            "transport": {"sse_url": "", "host": "", "port": 0},
            "feature_flags": {},
        }
        redacted = _redact_status_response(status)
        assert redacted["config"]["backend_count"] == 5


class TestBackendsRedaction:
    """Verify _redact_backends_response strips sensitive backend details."""

    def test_redacts_error_messages(self):
        """Backend error messages may contain internal details."""
        backends = {
            "backends": [
                {
                    "name": "my-backend",
                    "type": "stdio",
                    "state": "disconnected",
                    "error": "Connection refused at 10.0.0.5:3306 — ECONNREFUSED",
                    "conditions": [{"type": "Error", "message": "Internal stack trace here"}],
                    "health": {"status": "unhealthy"},
                    "capabilities": {"tools": 3, "resources": 0, "prompts": 0},
                },
            ]
        }
        redacted = _redact_backends_response(backends)
        backend = redacted["backends"][0]
        assert backend["error"] is None or backend["error"] == "[redacted]"
        assert backend["conditions"] == []

    def test_preserves_backend_name_and_state(self):
        """Backend name and connection state are safe to expose."""
        backends = {
            "backends": [
                {
                    "name": "weather-api",
                    "type": "sse",
                    "state": "connected",
                    "error": None,
                    "conditions": [],
                    "health": {"status": "healthy"},
                    "capabilities": {"tools": 5, "resources": 1, "prompts": 0},
                },
            ]
        }
        redacted = _redact_backends_response(backends)
        backend = redacted["backends"][0]
        assert backend["name"] == "weather-api"
        assert backend["state"] == "connected"
        assert backend["health"]["status"] == "healthy"

    def test_preserves_capability_counts(self):
        """Capability counts are safe metadata."""
        backends = {
            "backends": [
                {
                    "name": "backend-1",
                    "type": "stdio",
                    "state": "connected",
                    "error": None,
                    "conditions": [],
                    "health": {"status": "healthy"},
                    "capabilities": {"tools": 10, "resources": 2, "prompts": 1},
                },
            ]
        }
        redacted = _redact_backends_response(backends)
        caps = redacted["backends"][0]["capabilities"]
        assert caps["tools"] == 10
        assert caps["resources"] == 2
        assert caps["prompts"] == 1
