"""Tests for the use_dhi_images feature flag and DHI runtime defaults."""

from __future__ import annotations

import pytest

from argus_mcp.bridge.container.templates.models import (
    DHI_RUNTIME_DEFAULTS,
    RUNTIME_DEFAULTS,
    RuntimeConfig,
)
from argus_mcp.config.flags import FLAG_REGISTRY, FeatureFlags, FlagSpec


class TestDhiFlagRegistration:
    """Verify use_dhi_images flag is correctly registered."""

    def test_flag_registered(self) -> None:
        assert "use_dhi_images" in FLAG_REGISTRY

    def test_flag_governance(self) -> None:
        spec = FLAG_REGISTRY["use_dhi_images"]
        assert isinstance(spec, FlagSpec)
        assert spec.default is False
        assert spec.risk == "high"

    def test_flag_default_disabled(self) -> None:
        flags = FeatureFlags()
        assert flags.is_enabled("use_dhi_images") is False

    def test_flag_explicit_enable(self) -> None:
        flags = FeatureFlags({"use_dhi_images": True})
        assert flags.is_enabled("use_dhi_images") is True

    def test_flag_in_all_flags(self) -> None:
        flags = FeatureFlags()
        assert "use_dhi_images" in flags.all_flags()

    def test_flag_describe(self) -> None:
        flags = FeatureFlags()
        spec = flags.describe("use_dhi_images")
        assert spec is not None
        assert "Chainguard" in spec.description


class TestDhiRuntimeDefaults:
    """Verify DHI_RUNTIME_DEFAULTS structure and content."""

    @pytest.mark.parametrize("transport", ["uvx", "npx", "go"])
    def test_transport_present(self, transport: str) -> None:
        assert transport in DHI_RUNTIME_DEFAULTS

    @pytest.mark.parametrize("transport", ["uvx", "npx", "go"])
    def test_chainguard_images(self, transport: str) -> None:
        image = str(DHI_RUNTIME_DEFAULTS[transport]["builder_image"])
        assert "cgr.dev/chainguard" in image

    @pytest.mark.parametrize("transport", ["uvx", "npx", "go"])
    def test_matches_standard_transports(self, transport: str) -> None:
        """DHI defaults cover the same transports as standard defaults."""
        assert transport in RUNTIME_DEFAULTS


class TestForTransportDhi:
    """Verify RuntimeConfig.for_transport() DHI integration."""

    def test_standard_default(self) -> None:
        config = RuntimeConfig.for_transport("uvx", use_dhi=False)
        assert "python:3.13-slim" in config.builder_image

    def test_dhi_enabled(self) -> None:
        config = RuntimeConfig.for_transport("uvx", use_dhi=True)
        assert "cgr.dev/chainguard" in config.builder_image

    def test_override_beats_dhi(self) -> None:
        config = RuntimeConfig.for_transport(
            "uvx",
            use_dhi=True,
            overrides={"builder_image": "custom:latest"},
        )
        assert config.builder_image == "custom:latest"

    def test_backward_compatible(self) -> None:
        """Calling without use_dhi (old style) still works."""
        config = RuntimeConfig.for_transport("uvx")
        assert "python:3.13-slim" in config.builder_image

    @pytest.mark.parametrize("transport", ["uvx", "npx", "go"])
    def test_all_transports_dhi(self, transport: str) -> None:
        config = RuntimeConfig.for_transport(transport, use_dhi=True)
        assert config.builder_image != ""
        assert "cgr.dev/chainguard" in config.builder_image
