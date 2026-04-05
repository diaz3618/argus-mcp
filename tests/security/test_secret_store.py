"""Secret store audit tests (SEC-05).

Verify that documentation and example configs do not contain hardcoded
placeholder tokens that users might copy-paste into production, and that
the auth module emits a warning when tokens are sourced from config files
rather than environment variables or the encrypted secret store.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pytest

from argus_mcp.server.management.auth import resolve_token, validate_token_entropy

pytestmark = [pytest.mark.security]

# Repository root — two levels up from tests/security/
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


class TestDocHardcodedTokens:
    """Docs must not contain literal usable tokens."""

    _TOKEN_PATTERN = re.compile(
        r"ARGUS_MGMT_TOKEN\s*[=:]\s*(?P<value>\S+)",
    )

    # Values that are acceptable placeholders in docs
    _ALLOWED_DOC_VALUES = frozenset(
        {
            '"<generated-token>"',
            "<generated-token>",
            '"${ARGUS_MGMT_TOKEN}"',
            "${ARGUS_MGMT_TOKEN}",
            '"$secret:mgmt_token"',
            "$secret:mgmt_token",
            '"$(python',  # truncated command substitution
            "$(python",
        }
    )

    # Patterns that are shell syntax, not actual token values
    # Matches: ${VAR:-default}, ${VAR:?error}, ?VAR (from :?VAR), $VAR
    _SHELL_SYNTAX = re.compile(r"^['\"]?\$\{?\w+[}:?]|^\?")

    _DOC_FILES = [
        "docs/docker.md",
        "docs/cli/server.md",
        "docs/security/deployment-hardening.md",
    ]

    @pytest.mark.parametrize("doc_path", _DOC_FILES)
    def test_no_hardcoded_tokens_in_docs(self, doc_path: str):
        """Documentation should not contain literal usable token values."""
        full_path = _REPO_ROOT / doc_path
        if not full_path.exists():
            pytest.skip(f"{doc_path} not found")

        content = full_path.read_text(encoding="utf-8")
        for match in self._TOKEN_PATTERN.finditer(content):
            value = match.group("value").strip()
            # Allow documented placeholders and env var references
            if any(value.startswith(prefix) for prefix in self._ALLOWED_DOC_VALUES):
                continue
            # Allow Helm template references
            if "{{" in value and "}}" in value:
                continue
            # Allow shell parameter expansion (e.g. ${VAR:?msg}, ${VAR:-default})
            if self._SHELL_SYNTAX.match(value):
                continue
            pytest.fail(
                f"{doc_path} contains hardcoded token value: "
                f"ARGUS_MGMT_TOKEN={value!r} (line context: {match.group()!r}). "
                f"Replace with a placeholder like '<generated-token>' or "
                f"'$(python -c \"import secrets; print(secrets.token_urlsafe(32))\")'."
            )


class TestConfigFileTokenWarning:
    """Auth module warns when tokens come from config files."""

    def test_config_token_logs_warning(self, caplog):
        """resolve_token() should log an info message when using config_token."""
        import os

        # Clear env var so config_token is used
        env_backup = os.environ.pop("ARGUS_MGMT_TOKEN", None)
        try:
            with caplog.at_level(logging.INFO, logger="argus_mcp.server.management.auth"):
                result = resolve_token(config_token="a-valid-config-token-value")
            assert result == "a-valid-config-token-value"
            assert any(
                "config file" in rec.message.lower() and "env var" in rec.message.lower()
                for rec in caplog.records
            ), "Expected warning about using config file token instead of env var"
        finally:
            if env_backup is not None:
                os.environ["ARGUS_MGMT_TOKEN"] = env_backup

    def test_env_token_no_warning(self, caplog, monkeypatch):
        """resolve_token() should NOT warn when token comes from env var."""
        monkeypatch.setenv("ARGUS_MGMT_TOKEN", "secure-env-token-value-ok")
        with caplog.at_level(logging.INFO, logger="argus_mcp.server.management.auth"):
            result = resolve_token()
        assert result == "secure-env-token-value-ok"
        assert not any("config file" in rec.message.lower() for rec in caplog.records), (
            "Should not mention config file when env var is used"
        )


class TestEntropyBlocksPlaceholders:
    """validate_token_entropy rejects all known doc placeholders."""

    @pytest.mark.parametrize(
        "placeholder",
        [
            "my-secret-token",
            "changeme",
            "secret",
            "password",
            "token",
            "replace-me",
            "your-token-here",
        ],
    )
    def test_rejects_known_placeholder(self, placeholder: str):
        """Known placeholder tokens are always rejected."""
        with pytest.raises(ValueError, match="placeholder"):
            validate_token_entropy(placeholder, allow_weak=False)

    @pytest.mark.parametrize(
        "placeholder",
        [
            "my-secret-token",
            "changeme",
        ],
    )
    def test_rejects_placeholder_even_with_allow_weak(self, placeholder: str):
        """Placeholders are rejected even when allow_weak=True."""
        with pytest.raises(ValueError, match="placeholder"):
            validate_token_entropy(placeholder, allow_weak=True)
