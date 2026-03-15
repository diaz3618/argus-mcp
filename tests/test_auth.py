"""Tests for outgoing authentication"""

from __future__ import annotations

import asyncio
import time
from typing import Any
from unittest.mock import AsyncMock

import pytest

from argus_mcp.bridge.auth.provider import (
    OAuth2Provider,
    PKCEAuthProvider,
    StaticTokenProvider,
    _redact,
    create_auth_provider,
)
from argus_mcp.bridge.auth.token_cache import TokenCache

# TokenCache tests ───────────────────────────────────────────────────


class TestTokenCache:
    def test_empty_cache_returns_none(self) -> None:
        cache = TokenCache()
        assert cache.get() is None
        assert not cache.valid

    def test_set_and_get(self) -> None:
        cache = TokenCache(expiry_buffer=0.0)
        cache.set("tok123", expires_in=60.0)
        assert cache.valid
        assert cache.get() == "tok123"

    def test_expired_token_returns_none(self) -> None:
        cache = TokenCache(expiry_buffer=0.0)
        cache.set("tok", expires_in=0.01)
        time.sleep(0.02)
        assert cache.get() is None
        assert not cache.valid

    def test_expiry_buffer(self) -> None:
        cache = TokenCache(expiry_buffer=100.0)
        # Token expires in 50s, but buffer is 100s → immediately expired
        cache.set("tok", expires_in=50.0)
        assert cache.get() is None

    def test_invalidate(self) -> None:
        cache = TokenCache(expiry_buffer=0.0)
        cache.set("tok", expires_in=3600.0)
        assert cache.valid
        cache.invalidate()
        assert cache.get() is None
        assert not cache.valid


# StaticTokenProvider tests ───────────────────────────────────────


class TestStaticTokenProvider:
    def test_returns_headers(self) -> None:
        provider = StaticTokenProvider({"Authorization": "Bearer abc123"})
        headers = asyncio.run(provider.get_headers())
        assert headers == {"Authorization": "Bearer abc123"}

    def test_returns_copy(self) -> None:
        original = {"X-Key": "val"}
        provider = StaticTokenProvider(original)
        h1 = asyncio.run(provider.get_headers())
        h2 = asyncio.run(provider.get_headers())
        assert h1 is not h2
        assert h1 == h2

    def test_redacted_repr_masks_auth_headers(self) -> None:
        provider = StaticTokenProvider(
            {
                "Authorization": "Bearer ghp_1234567890abcdef",
                "X-Custom": "visible",
            }
        )
        r = provider.redacted_repr()
        assert "ghp_1234567890abcdef" not in r
        assert "visible" in r
        assert "StaticTokenProvider" in r


# OAuth2Provider tests ────────────────────────────────────────────


class TestOAuth2Provider:
    def test_redacted_repr(self) -> None:
        provider = OAuth2Provider(
            token_url="https://auth.example.com/token",
            client_id="my-client",
            client_secret="super-secret-value",
        )
        r = provider.redacted_repr()
        assert "super-secret-value" not in r
        assert "my-client" in r
        assert "OAuth2Provider" in r

    def test_get_headers_calls_fetch(self) -> None:
        provider = OAuth2Provider(
            token_url="https://auth.example.com/token",
            client_id="cid",
            client_secret="csec",
        )
        provider._fetch_token = AsyncMock(return_value="access_tok_xyz")  # type: ignore[method-assign]
        headers = asyncio.run(provider.get_headers())
        assert headers == {"Authorization": "Bearer access_tok_xyz"}
        provider._fetch_token.assert_called_once()

    def test_get_headers_uses_cache(self) -> None:
        provider = OAuth2Provider(
            token_url="https://auth.example.com/token",
            client_id="cid",
            client_secret="csec",
            expiry_buffer=0.0,
        )
        # Pre-fill cache
        provider._cache.set("cached_tok", expires_in=3600.0)
        provider._fetch_token = AsyncMock()  # type: ignore[method-assign]
        headers = asyncio.run(provider.get_headers())
        assert headers == {"Authorization": "Bearer cached_tok"}
        provider._fetch_token.assert_not_called()


# Factory tests ───────────────────────────────────────────────────


class TestCreateAuthProvider:
    def test_static(self) -> None:
        p = create_auth_provider({"type": "static", "headers": {"X": "Y"}})
        assert isinstance(p, StaticTokenProvider)

    def test_oauth2(self) -> None:
        p = create_auth_provider(
            {
                "type": "oauth2",
                "token_url": "https://ex.com/token",
                "client_id": "cid",
                "client_secret": "csec",
            }
        )
        assert isinstance(p, OAuth2Provider)

    def test_unknown_type_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown auth type"):
            create_auth_provider({"type": "magic"})

    def test_static_missing_headers_raises(self) -> None:
        with pytest.raises(ValueError, match="headers"):
            create_auth_provider({"type": "static"})

    def test_oauth2_missing_field_raises(self) -> None:
        with pytest.raises(ValueError, match="token_url"):
            create_auth_provider({"type": "oauth2", "client_id": "x", "client_secret": "y"})


# Redact helper tests ────────────────────────────────────────────


class TestRedact:
    def test_short_value(self) -> None:
        assert _redact("ab") == "****"

    def test_longer_value(self) -> None:
        result = _redact("1234567890", visible=4)
        assert result.endswith("7890")
        assert result.startswith("*")
        assert len(result) == 10


# Config schema tests ────────────────────────────────────────────


class TestAuthConfigSchema:
    def test_static_auth_config(self) -> None:
        from argus_mcp.config.schema import SseBackendConfig

        cfg = SseBackendConfig(
            type="sse",
            url="https://example.com/sse",
            auth={"type": "static", "headers": {"Authorization": "Bearer tok"}},
        )
        assert cfg.auth is not None
        assert cfg.auth.type == "static"

    def test_oauth2_auth_config(self) -> None:
        from argus_mcp.config.schema import StreamableHttpBackendConfig

        cfg = StreamableHttpBackendConfig(
            type="streamable-http",
            url="https://example.com/mcp",
            auth={
                "type": "oauth2",
                "token_url": "https://auth.example.com/token",
                "client_id": "cid",
                "client_secret": "csec",
            },
        )
        assert cfg.auth is not None
        assert cfg.auth.type == "oauth2"

    def test_no_auth_config(self) -> None:
        from argus_mcp.config.schema import SseBackendConfig

        cfg = SseBackendConfig(type="sse", url="https://example.com/sse")
        assert cfg.auth is None

    def test_sse_headers_field(self) -> None:
        from argus_mcp.config.schema import SseBackendConfig

        cfg = SseBackendConfig(
            type="sse",
            url="https://example.com/sse",
            headers={"X-Api-Key": "test"},
        )
        assert cfg.headers == {"X-Api-Key": "test"}


# Merge headers test ─────────────────────────────────────────────


class TestMergeHeaders:
    def test_both_none(self) -> None:
        from argus_mcp.bridge.transport_factory import _merge_headers

        assert _merge_headers(None, None) is None

    def test_only_static(self) -> None:
        from argus_mcp.bridge.transport_factory import _merge_headers

        assert _merge_headers({"X": "1"}, None) == {"X": "1"}

    def test_only_auth(self) -> None:
        from argus_mcp.bridge.transport_factory import _merge_headers

        assert _merge_headers(None, {"Authorization": "Bearer x"}) == {"Authorization": "Bearer x"}

    def test_auth_overrides_static(self) -> None:
        from argus_mcp.bridge.transport_factory import _merge_headers

        result = _merge_headers(
            {"Authorization": "old", "X-Other": "keep"},
            {"Authorization": "new"},
        )
        assert result == {"Authorization": "new", "X-Other": "keep"}


# OAuth discovery (discovery.py) ─────────────────────────────────────

from unittest.mock import MagicMock, patch

from argus_mcp.bridge.auth.discovery import (
    OAuthMetadata,
    _discover_oidc,
    _discover_resource_metadata,
    _metadata_cache,
    _parse_www_authenticate,
    _probe_www_authenticate,
    _validate_discovery_url,
    discover_oauth_metadata,
)


class TestValidateDiscoveryUrl:
    def test_valid_https(self):
        _validate_discovery_url("https://example.com/mcp")

    def test_valid_http(self):
        _validate_discovery_url("http://localhost:8080/mcp")

    def test_rejects_ftp(self):
        with pytest.raises(ValueError, match="Unsupported scheme"):
            _validate_discovery_url("ftp://example.com/file")

    def test_rejects_empty_host(self):
        with pytest.raises(ValueError, match="Missing host"):
            _validate_discovery_url("https:///no-host")

    def test_rejects_private_when_disallowed(self):
        with pytest.raises(ValueError, match="Private/loopback"):
            _validate_discovery_url("http://127.0.0.1/mcp", allow_private=False)

    def test_allows_private_by_default(self):
        _validate_discovery_url("http://192.168.1.1/mcp")

    def test_allows_dns_hostnames_even_private_false(self):
        _validate_discovery_url("http://internal.corp/mcp", allow_private=False)


class TestParseWwwAuthenticate:
    def test_empty_header(self):
        assert _parse_www_authenticate("") is None

    def test_authorization_uri(self):
        hdr = 'Bearer authorization_uri="https://auth.example.com"'
        assert _parse_www_authenticate(hdr) == "https://auth.example.com"

    def test_realm_url(self):
        hdr = 'Bearer realm="https://auth.example.com"'
        assert _parse_www_authenticate(hdr) == "https://auth.example.com"

    def test_realm_not_url(self):
        hdr = 'Bearer realm="my-realm"'
        assert _parse_www_authenticate(hdr) is None

    def test_no_match(self):
        hdr = "Basic"
        assert _parse_www_authenticate(hdr) is None


class TestOAuthMetadataProperties:
    def test_supports_pkce(self):
        meta = OAuthMetadata(code_challenge_methods_supported=["S256"])
        assert meta.supports_pkce is True

    def test_no_pkce(self):
        meta = OAuthMetadata(code_challenge_methods_supported=["plain"])
        assert meta.supports_pkce is False

    def test_supports_dynamic_registration(self):
        meta = OAuthMetadata(registration_endpoint="https://example.com/register")
        assert meta.supports_dynamic_registration is True

    def test_no_dynamic_registration(self):
        meta = OAuthMetadata()
        assert meta.supports_dynamic_registration is False


class TestDiscoverResourceMetadata:
    @pytest.mark.asyncio
    async def test_returns_auth_server_from_list(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"authorization_servers": ["https://auth.example.com"]}
        client = AsyncMock()
        client.get.return_value = resp
        result = await _discover_resource_metadata(client, "https://mcp.example.com/mcp")
        assert result == "https://auth.example.com"

    @pytest.mark.asyncio
    async def test_returns_auth_server_single(self):
        """Single authorization_server field used when list is absent."""
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "authorization_servers": [],
            "authorization_server": "https://auth.example.com",
        }
        client = AsyncMock()
        client.get.return_value = resp
        result = await _discover_resource_metadata(client, "https://mcp.example.com/mcp")
        assert result == "https://auth.example.com"

    @pytest.mark.asyncio
    async def test_returns_none_on_404(self):
        resp = MagicMock()
        resp.status_code = 404
        client = AsyncMock()
        client.get.return_value = resp
        result = await _discover_resource_metadata(client, "https://mcp.example.com/mcp")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self):
        client = AsyncMock()
        client.get.side_effect = OSError("conn error")
        result = await _discover_resource_metadata(client, "https://mcp.example.com/mcp")
        assert result is None


class TestProbeWwwAuthenticate:
    @pytest.mark.asyncio
    async def test_extracts_from_401(self):
        resp = MagicMock()
        resp.status_code = 401
        resp.headers = {"www-authenticate": 'Bearer realm="https://auth.example.com"'}
        client = AsyncMock()
        client.get.return_value = resp
        result = await _probe_www_authenticate(client, "https://mcp.example.com/mcp")
        assert result == "https://auth.example.com"

    @pytest.mark.asyncio
    async def test_returns_none_on_200(self):
        resp = MagicMock()
        resp.status_code = 200
        client = AsyncMock()
        client.get.return_value = resp
        result = await _probe_www_authenticate(client, "https://mcp.example.com/mcp")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_error(self):
        client = AsyncMock()
        client.get.side_effect = OSError("conn error")
        result = await _probe_www_authenticate(client, "https://mcp.example.com/mcp")
        assert result is None


class TestDiscoverOidc:
    @pytest.mark.asyncio
    async def test_rfc8414_only(self):
        rfc8414_resp = MagicMock()
        rfc8414_resp.status_code = 200
        rfc8414_resp.json.return_value = {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "code_challenge_methods_supported": ["S256"],
        }
        oidc_resp = MagicMock()
        oidc_resp.status_code = 404

        client = AsyncMock()
        client.get.side_effect = [rfc8414_resp, oidc_resp]
        result = await _discover_oidc(client, "https://auth.example.com")
        assert result is not None
        assert result.issuer == "https://auth.example.com"
        assert result.supports_pkce is True

    @pytest.mark.asyncio
    async def test_oidc_fallback(self):
        rfc8414_resp = MagicMock()
        rfc8414_resp.status_code = 404
        oidc_resp = MagicMock()
        oidc_resp.status_code = 200
        oidc_resp.json.return_value = {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
        }

        client = AsyncMock()
        client.get.side_effect = [rfc8414_resp, oidc_resp]
        result = await _discover_oidc(client, "https://auth.example.com")
        assert result is not None
        assert result.issuer == "https://auth.example.com"

    @pytest.mark.asyncio
    async def test_both_fail_returns_none(self):
        rfc8414_resp = MagicMock()
        rfc8414_resp.status_code = 404
        oidc_resp = MagicMock()
        oidc_resp.status_code = 404

        client = AsyncMock()
        client.get.side_effect = [rfc8414_resp, oidc_resp]
        result = await _discover_oidc(client, "https://auth.example.com")
        assert result is None

    @pytest.mark.asyncio
    async def test_merge_rfc8414_over_oidc(self):
        """RFC 8414 values take precedence over OIDC."""
        rfc8414_resp = MagicMock()
        rfc8414_resp.status_code = 200
        rfc8414_resp.json.return_value = {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize-rfc",
        }
        oidc_resp = MagicMock()
        oidc_resp.status_code = 200
        oidc_resp.json.return_value = {
            "issuer": "https://oidc.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize-oidc",
            "token_endpoint": "https://auth.example.com/token",
        }

        client = AsyncMock()
        client.get.side_effect = [rfc8414_resp, oidc_resp]
        result = await _discover_oidc(client, "https://auth.example.com")
        assert result is not None
        assert result.authorization_endpoint == "https://auth.example.com/authorize-rfc"
        assert result.token_endpoint == "https://auth.example.com/token"


class TestDiscoverOAuthMetadataIntegration:
    @pytest.fixture(autouse=True)
    def _clear_cache(self):
        _metadata_cache.clear()
        yield
        _metadata_cache.clear()

    @pytest.mark.asyncio
    async def test_cache_hit(self):
        import time

        meta = OAuthMetadata(issuer="cached")
        _metadata_cache["https://mcp.example.com/mcp"] = {
            "metadata": meta,
            "cached_at": time.monotonic(),
        }
        result = await discover_oauth_metadata("https://mcp.example.com/mcp")
        assert result is meta

    @pytest.mark.asyncio
    async def test_expired_cache_is_removed(self):
        import time

        old_meta = OAuthMetadata(issuer="stale")
        _metadata_cache["https://mcp.example.com/mcp"] = {
            "metadata": old_meta,
            "cached_at": time.monotonic() - 7200,  # 2 hours old, expired
        }
        # After expiry the stale entry should be removed on next call.
        # We mock _discover_resource_metadata and _probe_www_authenticate
        # to avoid real network calls and return no auth server.
        with (
            patch(
                "argus_mcp.bridge.auth.discovery._discover_resource_metadata",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch(
                "argus_mcp.bridge.auth.discovery._probe_www_authenticate",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            result = await discover_oauth_metadata("https://mcp.example.com/mcp")
        assert result is None
        assert "https://mcp.example.com/mcp" not in _metadata_cache


# Configurable token expiry buffer


class TestTokenExpiryBufferConfig:
    """Verify token_expiry_buffer_seconds propagates through config → factory → provider."""

    def test_oauth2_default_buffer(self) -> None:
        """Factory uses 300s default when token_expiry_buffer_seconds absent."""
        p = create_auth_provider(
            {
                "type": "oauth2",
                "token_url": "https://ex.com/token",
                "client_id": "cid",
                "client_secret": "csec",
            }
        )
        assert isinstance(p, OAuth2Provider)
        assert p._cache._expiry_buffer == 300.0

    def test_oauth2_custom_buffer(self) -> None:
        """Factory passes explicit token_expiry_buffer_seconds to OAuth2Provider."""
        p = create_auth_provider(
            {
                "type": "oauth2",
                "token_url": "https://ex.com/token",
                "client_id": "cid",
                "client_secret": "csec",
                "token_expiry_buffer_seconds": 120.0,
            }
        )
        assert isinstance(p, OAuth2Provider)
        assert p._cache._expiry_buffer == 120.0

    def test_pkce_default_buffer(self) -> None:
        """Factory uses 300s default for PKCE when field absent."""
        p = create_auth_provider(
            {
                "type": "pkce",
                "authorization_endpoint": "https://ex.com/auth",
                "token_endpoint": "https://ex.com/token",
                "client_id": "cid",
            },
            backend_name="test-backend",
        )
        assert isinstance(p, PKCEAuthProvider)
        assert p._cache._expiry_buffer == 300.0

    def test_pkce_custom_buffer(self) -> None:
        """Factory passes explicit token_expiry_buffer_seconds to PKCEAuthProvider."""
        p = create_auth_provider(
            {
                "type": "pkce",
                "authorization_endpoint": "https://ex.com/auth",
                "token_endpoint": "https://ex.com/token",
                "client_id": "cid",
                "token_expiry_buffer_seconds": 600,
            },
            backend_name="test-backend",
        )
        assert isinstance(p, PKCEAuthProvider)
        assert p._cache._expiry_buffer == 600.0

    def test_oauth2_schema_default(self) -> None:
        """OAuth2AuthConfig pydantic model defaults to 300s."""
        from argus_mcp.config.schema_backends import OAuth2AuthConfig

        cfg = OAuth2AuthConfig(
            type="oauth2",
            token_url="https://ex.com/token",
            client_id="cid",
            client_secret="csec",
        )
        assert cfg.token_expiry_buffer_seconds == 300.0

    def test_pkce_schema_default(self) -> None:
        """PKCEAuthConfig pydantic model defaults to 300s."""
        from argus_mcp.config.schema_backends import PKCEAuthConfig

        cfg = PKCEAuthConfig(
            type="pkce",
            authorization_endpoint="https://ex.com/auth",
            token_endpoint="https://ex.com/token",
            client_id="cid",
        )
        assert cfg.token_expiry_buffer_seconds == 300.0

    def test_oauth2_schema_custom(self) -> None:
        """OAuth2AuthConfig accepts custom expiry buffer."""
        from argus_mcp.config.schema_backends import OAuth2AuthConfig

        cfg = OAuth2AuthConfig(
            type="oauth2",
            token_url="https://ex.com/token",
            client_id="cid",
            client_secret="csec",
            token_expiry_buffer_seconds=60.0,
        )
        assert cfg.token_expiry_buffer_seconds == 60.0

    def test_oauth2_schema_rejects_negative(self) -> None:
        """OAuth2AuthConfig rejects negative buffer values."""
        from pydantic import ValidationError

        from argus_mcp.config.schema_backends import OAuth2AuthConfig

        with pytest.raises(ValidationError):
            OAuth2AuthConfig(
                type="oauth2",
                token_url="https://ex.com/token",
                client_id="cid",
                client_secret="csec",
                token_expiry_buffer_seconds=-1,
            )

    def test_cache_respects_custom_buffer(self) -> None:
        """TokenCache with custom buffer makes token expire early."""
        cache = TokenCache(expiry_buffer=300.0)
        cache.set("tok", expires_in=600.0)
        # With 300s buffer on 600s TTL, effective TTL is 300s — token is valid
        assert cache.get() == "tok"

        cache2 = TokenCache(expiry_buffer=600.0)
        cache2.set("tok2", expires_in=600.0)
        # With 600s buffer on 600s TTL, effective TTL is 0 — token already expired
        assert cache2.get() is None


# AuthRefreshService tests ───────────────────────────────────────────


class TestAuthRefreshService:
    """Unit tests for the background token refresh service."""

    def test_interval_clamped_to_minimum(self) -> None:
        """Interval below 5s is clamped to 5.0."""
        from argus_mcp.bridge.auth.refresh_service import AuthRefreshService

        svc = AuthRefreshService({}, interval=1.0)
        assert svc._interval == 5.0

    def test_interval_accepted_when_valid(self) -> None:
        from argus_mcp.bridge.auth.refresh_service import AuthRefreshService

        svc = AuthRefreshService({}, interval=120.0)
        assert svc._interval == 120.0

    def test_not_running_before_start(self) -> None:
        from argus_mcp.bridge.auth.refresh_service import AuthRefreshService

        svc = AuthRefreshService({})
        assert not svc.running

    @pytest.mark.asyncio
    async def test_start_and_running(self) -> None:
        from argus_mcp.bridge.auth.refresh_service import AuthRefreshService

        svc = AuthRefreshService({}, interval=5.0)
        svc.start()
        try:
            assert svc.running
        finally:
            await svc.stop()
        assert not svc.running

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self) -> None:
        from argus_mcp.bridge.auth.refresh_service import AuthRefreshService

        svc = AuthRefreshService({}, interval=5.0)
        svc.start()
        task1 = svc._task
        svc.start()
        task2 = svc._task
        try:
            assert task1 is task2
        finally:
            await svc.stop()

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self) -> None:
        from argus_mcp.bridge.auth.refresh_service import AuthRefreshService

        svc = AuthRefreshService({})
        # stop before start should be harmless
        await svc.stop()
        assert not svc.running

    @pytest.mark.asyncio
    async def test_sweep_calls_get_headers_on_oauth_provider(self) -> None:
        """_sweep() should call get_headers() on OAuth2Provider instances."""
        from argus_mcp.bridge.auth.refresh_service import AuthRefreshService

        mock_provider = AsyncMock(spec=OAuth2Provider)
        mock_provider.get_headers = AsyncMock(return_value={"Authorization": "Bearer tok"})
        providers: dict[str, Any] = {"backend-1": mock_provider}

        svc = AuthRefreshService(providers)
        await svc._sweep()

        mock_provider.get_headers.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sweep_skips_static_token_provider(self) -> None:
        """_sweep() should skip StaticTokenProvider instances."""
        from argus_mcp.bridge.auth.refresh_service import AuthRefreshService

        static_provider = StaticTokenProvider(headers={"Authorization": "Bearer static-tok"})
        providers: dict[str, Any] = {"static-backend": static_provider}

        svc = AuthRefreshService(providers)
        # No error expected — it simply skips
        await svc._sweep()

    @pytest.mark.asyncio
    async def test_sweep_handles_per_backend_errors(self) -> None:
        """_sweep() logs errors per-backend but keeps going."""
        from argus_mcp.bridge.auth.refresh_service import AuthRefreshService

        failing = AsyncMock(spec=OAuth2Provider)
        failing.get_headers = AsyncMock(side_effect=RuntimeError("token endpoint down"))
        ok = AsyncMock(spec=OAuth2Provider)
        ok.get_headers = AsyncMock(return_value={"Authorization": "Bearer tok"})

        providers: dict[str, Any] = {"fail-be": failing, "ok-be": ok}

        svc = AuthRefreshService(providers)
        await svc._sweep()

        failing.get_headers.assert_awaited_once()
        ok.get_headers.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_sweep_empty_providers(self) -> None:
        """_sweep() on empty providers dict does nothing."""
        from argus_mcp.bridge.auth.refresh_service import AuthRefreshService

        svc = AuthRefreshService({})
        await svc._sweep()  # no error

    @pytest.mark.asyncio
    async def test_sweep_skips_non_authprovider(self) -> None:
        """_sweep() skips values that are not AuthProvider instances."""
        from argus_mcp.bridge.auth.refresh_service import AuthRefreshService

        providers: dict[str, Any] = {"non-provider": "just a string"}
        svc = AuthRefreshService(providers)
        await svc._sweep()  # no error


# ServerSettings config field tests ──────────────────────────────────


class TestServerSettingsAuthConfig:
    """Test the auth background refresh config fields on ServerSettings."""

    def test_defaults(self) -> None:
        from argus_mcp.config.schema_server import ServerSettings

        settings = ServerSettings()
        assert settings.auth_background_refresh_enabled is True
        assert settings.auth_background_refresh_interval_seconds == 60.0

    def test_custom_values(self) -> None:
        from argus_mcp.config.schema_server import ServerSettings

        settings = ServerSettings(
            auth_background_refresh_enabled=False,
            auth_background_refresh_interval_seconds=120.0,
        )
        assert settings.auth_background_refresh_enabled is False
        assert settings.auth_background_refresh_interval_seconds == 120.0

    def test_interval_minimum_validation(self) -> None:
        from pydantic import ValidationError

        from argus_mcp.config.schema_server import ServerSettings

        with pytest.raises(ValidationError):
            ServerSettings(auth_background_refresh_interval_seconds=2.0)

    def test_interval_maximum_validation(self) -> None:
        from pydantic import ValidationError

        from argus_mcp.config.schema_server import ServerSettings

        with pytest.raises(ValidationError):
            ServerSettings(auth_background_refresh_interval_seconds=5000.0)


# ClientManager refresh service integration tests ────────────────────


class TestClientManagerRefreshIntegration:
    """Test ClientManager methods for refresh service lifecycle."""

    def test_start_refresh_service_disabled(self) -> None:
        """start_refresh_service(enabled=False) does not create service."""
        from argus_mcp.bridge.client_manager import ClientManager

        mgr = ClientManager()
        mgr.start_refresh_service(enabled=False)
        assert mgr._refresh_service is None

    def test_start_refresh_service_no_providers(self) -> None:
        """start_refresh_service with no providers does not create service."""
        from argus_mcp.bridge.client_manager import ClientManager

        mgr = ClientManager()
        mgr.start_refresh_service(enabled=True, interval=30.0)
        assert mgr._refresh_service is None

    @pytest.mark.asyncio
    async def test_start_and_stop_refresh_service(self) -> None:
        """Refresh service starts when enabled and providers exist."""
        from argus_mcp.bridge.client_manager import ClientManager

        mgr = ClientManager()
        mock_provider = AsyncMock(spec=OAuth2Provider)
        mgr._auth_providers["test-be"] = mock_provider

        mgr.start_refresh_service(enabled=True, interval=10.0)
        assert mgr._refresh_service is not None
        assert mgr._refresh_service.running

        await mgr._stop_refresh_service()
        assert mgr._refresh_service is None

    @pytest.mark.asyncio
    async def test_stop_all_clears_auth_providers(self) -> None:
        """stop_all() clears _auth_providers dict."""
        from argus_mcp.bridge.client_manager import ClientManager

        mgr = ClientManager()
        mock_provider = AsyncMock(spec=OAuth2Provider)
        mgr._auth_providers["be1"] = mock_provider

        await mgr.stop_all()
        assert len(mgr._auth_providers) == 0

    @pytest.mark.asyncio
    async def test_disconnect_one_removes_provider(self) -> None:
        """disconnect_one() pops the provider from _auth_providers."""
        from argus_mcp.bridge.client_manager import ClientManager

        mgr = ClientManager()
        mock_provider = AsyncMock(spec=OAuth2Provider)
        mgr._auth_providers["be1"] = mock_provider

        await mgr.disconnect_one("be1")
        assert "be1" not in mgr._auth_providers

    @pytest.mark.asyncio
    async def test_disconnect_one_missing_name_safe(self) -> None:
        """disconnect_one() with missing name doesn't error on auth_providers."""
        from argus_mcp.bridge.client_manager import ClientManager

        mgr = ClientManager()
        await mgr.disconnect_one("nonexistent")
        assert "nonexistent" not in mgr._auth_providers
