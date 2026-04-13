"""Fuzz / property-based tests for TelemetrySettings.

Uses Hypothesis to generate randomised inputs that exercise the
``enabled`` boolean, ``otlp_endpoint`` URL string, and ``service_name``
string fields on TelemetrySettings.
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from argus_mcp.config.schema import TelemetrySettings

pytestmark = [pytest.mark.fuzz]


class TestTelemetrySettingsFuzz:
    """Property tests for TelemetrySettings fields."""

    @given(
        enabled=st.booleans(),
        otlp_endpoint=st.text(min_size=1, max_size=200),
        service_name=st.text(min_size=1, max_size=100),
    )
    @settings(max_examples=200)
    def test_valid_config_accepted(
        self, enabled: bool, otlp_endpoint: str, service_name: str
    ) -> None:
        cfg = TelemetrySettings(
            enabled=enabled,
            otlp_endpoint=otlp_endpoint,
            service_name=service_name,
        )
        assert cfg.enabled is enabled
        assert cfg.otlp_endpoint == otlp_endpoint
        assert cfg.service_name == service_name

    @given(
        otlp_endpoint=st.from_regex(
            r"https?://[a-z0-9.-]+(:[0-9]{1,5})?(/[a-z0-9._-]*)*", fullmatch=True
        )
    )
    @settings(max_examples=100)
    def test_url_like_endpoints_accepted(self, otlp_endpoint: str) -> None:
        cfg = TelemetrySettings(otlp_endpoint=otlp_endpoint)
        assert cfg.otlp_endpoint == otlp_endpoint

    @given(service_name=st.text(max_size=200))
    @settings(max_examples=100)
    def test_arbitrary_service_name_accepted(self, service_name: str) -> None:
        cfg = TelemetrySettings(service_name=service_name)
        assert cfg.service_name == service_name

    def test_defaults_are_consistent(self) -> None:
        cfg = TelemetrySettings()
        assert cfg.enabled is False
        assert cfg.otlp_endpoint == "http://localhost:4317"
        assert cfg.service_name == "argus-mcp"
