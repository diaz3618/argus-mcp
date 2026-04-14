"""Tests for Phase 21 AUTH-01, AUTH-05, AUTH-06 hardening.

AUTH-01: Empty/missing auth config raises at startup
AUTH-05: OIDC SSRF guard blocks private/loopback/link-local addresses
AUTH-06: LocalTokenProvider uses hmac.compare_digest (regression guard)
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, patch

import pytest

from argus_mcp.errors import ConfigurationError
from argus_mcp.server.auth.oidc import OIDCDiscovery, OIDCDiscoveryError
from argus_mcp.server.auth.providers import (
    AnonymousProvider,
    AuthProviderRegistry,
    LocalTokenProvider,
)

# ── AUTH-01: Startup guard for missing/empty auth config ─────────────


class TestAuthProviderFailsafe:
    def test_from_config_none_raises(self):
        with pytest.raises(ValueError, match="Auth provider config is required"):
            AuthProviderRegistry.from_config(None)

    def test_from_config_empty_dict_raises(self):
        with pytest.raises(ValueError, match="Auth provider config is required"):
            AuthProviderRegistry.from_config({})

    def test_from_config_explicit_anonymous_works(self):
        reg = AuthProviderRegistry.from_config({"type": "anonymous"})
        assert isinstance(reg._provider, AnonymousProvider)

    def test_from_config_local_works(self):
        reg = AuthProviderRegistry.from_config({"type": "local", "token": "secret"})
        assert isinstance(reg._provider, LocalTokenProvider)

    def test_setup_incoming_auth_none_raises(self):
        from argus_mcp.server.lifespan import _setup_incoming_auth

        with pytest.raises(ConfigurationError, match="Auth configuration is required"):
            _setup_incoming_auth(None)


# ── AUTH-05: OIDC SSRF guard ─────────────────────────────────────────


class TestOIDCSSRFGuard:
    @pytest.mark.asyncio
    async def test_oidc_ssrf_loopback_blocked(self):
        d = OIDCDiscovery("http://127.0.0.1:8080")
        with pytest.raises(OIDCDiscoveryError, match="private/loopback/reserved"):
            await d.fetch()

    @pytest.mark.asyncio
    async def test_oidc_ssrf_private_10_blocked(self):
        d = OIDCDiscovery("http://10.0.0.1:8080")
        with pytest.raises(OIDCDiscoveryError, match="private/loopback/reserved"):
            await d.fetch()

    @pytest.mark.asyncio
    async def test_oidc_ssrf_private_172_blocked(self):
        d = OIDCDiscovery("http://172.16.0.1:8080")
        with pytest.raises(OIDCDiscoveryError, match="private/loopback/reserved"):
            await d.fetch()

    @pytest.mark.asyncio
    async def test_oidc_ssrf_private_192_blocked(self):
        d = OIDCDiscovery("http://192.168.1.1:8080")
        with pytest.raises(OIDCDiscoveryError, match="private/loopback/reserved"):
            await d.fetch()

    @pytest.mark.asyncio
    async def test_oidc_ssrf_link_local_blocked(self):
        d = OIDCDiscovery("http://169.254.169.254")
        with pytest.raises(OIDCDiscoveryError, match="private/loopback/reserved"):
            await d.fetch()

    def test_oidc_validate_bad_scheme(self):
        d = OIDCDiscovery("ftp://example.com")
        with pytest.raises(OIDCDiscoveryError, match="http or https"):
            d._validate_issuer_url()

    def test_oidc_validate_no_hostname(self):
        d = OIDCDiscovery("http://")
        with pytest.raises(OIDCDiscoveryError, match="no hostname"):
            d._validate_issuer_url()

    @pytest.mark.asyncio
    async def test_oidc_follow_redirects_disabled(self):
        """Verify follow_redirects=False is passed to httpx client.get()."""
        from unittest.mock import MagicMock

        d = OIDCDiscovery("https://accounts.google.com")

        mock_response = MagicMock()
        mock_response.raise_for_status = lambda: None
        mock_response.json.return_value = {
            "issuer": "https://accounts.google.com",
            "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            # Patch DNS resolution to return a public IP (not blocked by SSRF guard)
            with patch("socket.getaddrinfo") as mock_dns:
                mock_dns.return_value = [
                    (2, 1, 6, "", ("142.250.80.46", 0)),
                ]
                await d.fetch()

        # Verify follow_redirects=False was passed
        call_kwargs = mock_client.get.call_args
        assert call_kwargs.kwargs.get("follow_redirects") is False or (
            len(call_kwargs.args) > 1 and call_kwargs.args[1] is False
        ), "follow_redirects=False must be passed to client.get()"


# ── AUTH-06: HMAC timing-safe comparison regression guard ────────────


class TestHMACRegression:
    def test_local_token_provider_uses_hmac_compare_digest(self):
        """Verify LocalTokenProvider.authenticate uses hmac.compare_digest."""
        source = inspect.getsource(LocalTokenProvider.authenticate)
        assert "hmac.compare_digest" in source, (
            "LocalTokenProvider.authenticate must use hmac.compare_digest for timing-safe comparison"
        )

    @pytest.mark.asyncio
    async def test_local_token_valid(self):
        provider = LocalTokenProvider("test-token-123")
        user = await provider.authenticate("test-token-123")
        assert user.provider == "local"
        assert user.subject == "local-user"

    @pytest.mark.asyncio
    async def test_local_token_invalid_raises(self):
        from argus_mcp.server.auth.providers import AuthenticationError

        provider = LocalTokenProvider("test-token-123")
        with pytest.raises(AuthenticationError, match="Invalid bearer token"):
            await provider.authenticate("wrong-token")

    @pytest.mark.asyncio
    async def test_local_token_missing_raises(self):
        from argus_mcp.server.auth.providers import AuthenticationError

        provider = LocalTokenProvider("test-token-123")
        with pytest.raises(AuthenticationError, match="Missing bearer token"):
            await provider.authenticate(None)
