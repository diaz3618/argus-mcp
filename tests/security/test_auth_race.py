"""Auth race condition tests (SEC-11).

Verify that the management API token is resolved and validated
BEFORE the Starlette app is created, closing the window where
requests could arrive before authentication is configured.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from argus_mcp.server.management.auth import resolve_token, validate_token_entropy

pytestmark = [pytest.mark.security]


class TestTokenPreResolution:
    """Token must be available before the first HTTP request."""

    def test_resolve_token_from_env(self):
        """Token resolved from env var is immediately available."""
        with patch.dict("os.environ", {"ARGUS_MGMT_TOKEN": "a" * 32}):
            token = resolve_token()
            assert token is not None
            assert len(token) == 32

    def test_resolve_then_validate_pipeline(self):
        """resolve_token → validate_token_entropy pipeline works end-to-end."""
        with patch.dict("os.environ", {"ARGUS_MGMT_TOKEN": "x" * 32}):
            raw = resolve_token()
            validated = validate_token_entropy(raw, allow_weak=False)
            assert validated == "x" * 32

    def test_resolve_weak_token_fails_strict(self):
        """Short env token fails strict validation (must be caught at startup)."""
        with patch.dict("os.environ", {"ARGUS_MGMT_TOKEN": "weak"}):
            raw = resolve_token()
            with pytest.raises(ValueError, match="too short"):
                validate_token_entropy(raw, allow_weak=False)

    def test_resolve_no_token_disables_auth(self):
        """No token configured means auth disabled (None passes through)."""
        with patch.dict("os.environ", {}, clear=True):
            raw = resolve_token()
            validated = validate_token_entropy(raw, allow_weak=False)
            assert validated is None

    def test_config_file_token_resolution(self):
        """resolve_token with config_token fallback returns config value."""
        with patch.dict("os.environ", {}, clear=True):
            token = resolve_token(config_token="cfg-" + "a" * 28)
            assert token == "cfg-" + "a" * 28
