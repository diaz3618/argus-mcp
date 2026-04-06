"""Token entropy validation tests (SEC-06, SEC-11).

Verify that management API tokens meet minimum entropy requirements:
- Tokens shorter than 16 characters are rejected (weak)
- Valid tokens (>=16 chars) pass validation
- Empty/None tokens are handled gracefully (auth disabled)
- `allow_weak_tokens` flag overrides minimum length check
"""

from __future__ import annotations

import pytest

from argus_mcp.server.management.auth import validate_token_entropy

pytestmark = [pytest.mark.security]


class TestTokenEntropyValidation:
    """Validate token entropy enforcement."""

    def test_short_token_rejected(self):
        """Tokens under 16 chars must raise ValueError."""
        with pytest.raises(ValueError, match="too short"):
            validate_token_entropy("short", allow_weak=False)

    def test_minimum_length_token_accepted(self):
        """16-character token is the minimum accepted length."""
        token = "a" * 16
        # Should not raise
        result = validate_token_entropy(token, allow_weak=False)
        assert result == token

    def test_strong_token_accepted(self):
        """Long random-looking token passes validation."""
        token = "xK9mP2vL8nQ4wR7tY5uH3jF6gB0cD1eA"
        result = validate_token_entropy(token, allow_weak=False)
        assert result == token

    def test_none_token_returns_none(self):
        """None token means auth disabled — no validation needed."""
        result = validate_token_entropy(None, allow_weak=False)
        assert result is None

    def test_empty_string_returns_none(self):
        """Empty string token means auth disabled."""
        result = validate_token_entropy("", allow_weak=False)
        assert result is None

    def test_whitespace_only_returns_none(self):
        """Whitespace-only token means auth disabled."""
        result = validate_token_entropy("   ", allow_weak=False)
        assert result is None

    def test_allow_weak_bypasses_length_check(self):
        """When allow_weak=True, short tokens are accepted with a warning."""
        token = "short"
        result = validate_token_entropy(token, allow_weak=True)
        assert result == token

    def test_common_placeholder_rejected(self):
        """Well-known placeholder tokens must be rejected."""
        with pytest.raises(ValueError, match="placeholder"):
            validate_token_entropy("my-secret-token", allow_weak=False)

    def test_another_placeholder_rejected(self):
        """'changeme' is a common insecure placeholder."""
        with pytest.raises(ValueError, match="placeholder"):
            validate_token_entropy("changeme-changeme", allow_weak=False)

    def test_allow_weak_still_rejects_placeholders(self):
        """Even with allow_weak, known placeholders are rejected."""
        with pytest.raises(ValueError, match="placeholder"):
            validate_token_entropy("my-secret-token", allow_weak=True)
