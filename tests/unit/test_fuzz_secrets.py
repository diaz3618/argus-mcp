"""Fuzz / property-based tests for SecretsConfig.

Uses Hypothesis to generate randomised inputs that exercise the
``enabled`` / ``strict`` booleans and ``provider`` / ``path`` string
fields on SecretsConfig.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from argus_mcp.config.schema import SecretsConfig

pytestmark = [pytest.mark.fuzz]


class TestSecretsConfigFuzz:
    """Property tests for SecretsConfig fields."""

    @given(
        enabled=st.booleans(),
        provider=st.text(min_size=1, max_size=50),
        path=st.text(max_size=200),
        strict=st.booleans(),
    )
    @settings(max_examples=200)
    def test_valid_config_accepted(
        self, enabled: bool, provider: str, path: str, strict: bool
    ) -> None:
        cfg = SecretsConfig(enabled=enabled, provider=provider, path=path, strict=strict)
        assert cfg.enabled is enabled
        assert cfg.provider == provider
        assert cfg.path == path
        assert cfg.strict is strict

    @given(provider=st.sampled_from(["env", "file", "keyring"]))
    @settings(max_examples=30)
    def test_known_providers_accepted(self, provider: str) -> None:
        cfg = SecretsConfig(provider=provider)
        assert cfg.provider == provider

    @given(path=st.from_regex(r"(/[a-zA-Z0-9._-]+)+", fullmatch=True))
    @settings(max_examples=100)
    def test_unix_like_paths_accepted(self, path: str) -> None:
        cfg = SecretsConfig(path=path)
        assert cfg.path == path

    @given(enabled=st.booleans(), strict=st.booleans())
    @settings(max_examples=50)
    def test_bool_fields_accept_valid_booleans(self, enabled: bool, strict: bool) -> None:
        cfg = SecretsConfig(enabled=enabled, strict=strict)
        assert cfg.enabled is enabled
        assert cfg.strict is strict
