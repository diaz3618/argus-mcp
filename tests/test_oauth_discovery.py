"""Tests for ``argus_mcp.bridge.auth.discovery`` — OAuth metadata discovery."""

from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import argus_mcp.bridge.auth.discovery as _discovery_mod
from argus_mcp.bridge.auth.discovery import (
    _METADATA_CACHE_TTL,
    OAuthMetadata,
    _parse_www_authenticate,
    _validate_discovery_url,
    discover_oauth_metadata,
)

# Helpers ─────────────────────────────────────────────────────────────


def _mock_response(
    status_code: int = 200,
    json_data: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> MagicMock:
    """Build a mock httpx.Response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.headers = headers or {}
    return resp


# _validate_discovery_url ─────────────────────────────────────────────


class TestValidateDiscoveryUrl:
    """Tests for SSRF validation of discovery URLs."""

    def test_accepts_https(self) -> None:
        _validate_discovery_url("https://auth.example.com/authorize")

    def test_accepts_http(self) -> None:
        _validate_discovery_url("http://auth.example.com/authorize")

    def test_rejects_ftp_scheme(self) -> None:
        with pytest.raises(ValueError, match="Unsupported scheme"):
            _validate_discovery_url("ftp://evil.com/file")

    def test_rejects_file_scheme(self) -> None:
        with pytest.raises(ValueError, match="Unsupported scheme"):
            _validate_discovery_url("file:///etc/passwd")

    def test_rejects_empty_host(self) -> None:
        with pytest.raises(ValueError, match="Missing host"):
            _validate_discovery_url("https:///no-host")

    def test_rejects_private_ip_when_disabled(self) -> None:
        with pytest.raises(ValueError, match="Private/loopback"):
            _validate_discovery_url("http://192.168.1.1/auth", allow_private=False)

    def test_rejects_loopback_when_disabled(self) -> None:
        with pytest.raises(ValueError, match="Private/loopback"):
            _validate_discovery_url("http://127.0.0.1/auth", allow_private=False)

    def test_rejects_link_local_when_disabled(self) -> None:
        with pytest.raises(ValueError, match="Private/loopback"):
            _validate_discovery_url("http://169.254.1.1/auth", allow_private=False)

    def test_allows_private_ip_by_default(self) -> None:
        _validate_discovery_url("http://192.168.1.1/auth")

    def test_allows_dns_names_even_when_private_disabled(self) -> None:
        _validate_discovery_url("https://internal.corp.com/auth", allow_private=False)

    def test_rejects_javascript_scheme(self) -> None:
        with pytest.raises(ValueError, match="Unsupported scheme"):
            _validate_discovery_url("javascript:alert(1)")


# OAuthMetadata ───────────────────────────────────────────────────────


class TestOAuthMetadata:
    """Tests for the OAuthMetadata dataclass."""

    def test_supports_pkce_true(self) -> None:
        meta = OAuthMetadata(code_challenge_methods_supported=["S256", "plain"])
        assert meta.supports_pkce is True

    def test_supports_pkce_false(self) -> None:
        meta = OAuthMetadata(code_challenge_methods_supported=["plain"])
        assert meta.supports_pkce is False

    def test_supports_pkce_empty(self) -> None:
        meta = OAuthMetadata()
        assert meta.supports_pkce is False

    def test_supports_dynamic_registration_true(self) -> None:
        meta = OAuthMetadata(registration_endpoint="https://auth.example.com/register")
        assert meta.supports_dynamic_registration is True

    def test_supports_dynamic_registration_false(self) -> None:
        meta = OAuthMetadata(registration_endpoint="")
        assert meta.supports_dynamic_registration is False

    def test_frozen(self) -> None:
        meta = OAuthMetadata(issuer="https://auth.example.com")
        with pytest.raises(AttributeError):
            meta.issuer = "changed"  # type: ignore[misc]


# _parse_www_authenticate ─────────────────────────────────────────────


class TestParseWwwAuthenticate:
    """Tests for extracting auth server URL from WWW-Authenticate header."""

    def test_empty_header(self) -> None:
        assert _parse_www_authenticate("") is None

    def test_authorization_uri(self) -> None:
        header = 'Bearer authorization_uri="https://auth.example.com"'
        assert _parse_www_authenticate(header) == "https://auth.example.com"

    def test_realm_with_url(self) -> None:
        header = 'Bearer realm="https://auth.example.com/authorize"'
        assert _parse_www_authenticate(header) == "https://auth.example.com/authorize"

    def test_realm_without_url(self) -> None:
        header = 'Bearer realm="my-app"'
        assert _parse_www_authenticate(header) is None

    def test_authorization_uri_takes_precedence(self) -> None:
        header = 'Bearer realm="https://realm.com", authorization_uri="https://uri.com"'
        assert _parse_www_authenticate(header) == "https://uri.com"

    def test_no_matching_fields(self) -> None:
        header = "Bearer error=invalid_token"
        assert _parse_www_authenticate(header) is None


# discover_oauth_metadata ─────────────────────────────────────────────


class TestDiscoverOAuthMetadata:
    """Tests for the main discovery function."""

    @pytest.fixture(autouse=True)
    def _clear_cache(self) -> None:
        """Clear the metadata cache before each test."""
        _discovery_mod._metadata_cache.clear()
        yield  # type: ignore[misc]
        _discovery_mod._metadata_cache.clear()

    @pytest.mark.asyncio
    async def test_rejects_invalid_url(self) -> None:
        with pytest.raises(ValueError, match="Unsupported scheme"):
            await discover_oauth_metadata("ftp://evil.com")

    @pytest.mark.asyncio
    async def test_returns_none_when_no_auth_server_found(self) -> None:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(404))

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await discover_oauth_metadata("https://mcp.example.com/mcp")

        assert result is None

    @pytest.mark.asyncio
    async def test_rfc9728_discovery_success(self) -> None:
        resource_resp = _mock_response(
            200,
            json_data={"authorization_servers": ["https://auth.example.com"]},
        )
        oidc_resp = _mock_response(
            200,
            json_data={
                "issuer": "https://auth.example.com",
                "authorization_endpoint": "https://auth.example.com/authorize",
                "token_endpoint": "https://auth.example.com/token",
                "code_challenge_methods_supported": ["S256"],
            },
        )
        rfc8414_resp = _mock_response(404)

        call_count = 0
        responses = [resource_resp, rfc8414_resp, oidc_resp]

        async def mock_get(url: str) -> MagicMock:
            nonlocal call_count
            idx = min(call_count, len(responses) - 1)
            call_count += 1
            return responses[idx]

        mock_client = AsyncMock()
        mock_client.get = mock_get

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await discover_oauth_metadata("https://mcp.example.com/mcp")

        assert result is not None
        assert result.issuer == "https://auth.example.com"
        assert result.authorization_endpoint == "https://auth.example.com/authorize"
        assert result.token_endpoint == "https://auth.example.com/token"
        assert result.supports_pkce is True

    @pytest.mark.asyncio
    async def test_www_authenticate_fallback(self) -> None:
        resource_resp = _mock_response(404)
        probe_resp = _mock_response(
            401,
            headers={"www-authenticate": 'Bearer realm="https://auth.example.com"'},
        )
        oidc_resp = _mock_response(
            200,
            json_data={
                "issuer": "https://auth.example.com",
                "authorization_endpoint": "https://auth.example.com/authorize",
                "token_endpoint": "https://auth.example.com/token",
            },
        )
        rfc8414_resp = _mock_response(404)

        call_count = 0
        responses = [resource_resp, probe_resp, rfc8414_resp, oidc_resp]

        async def mock_get(url: str) -> MagicMock:
            nonlocal call_count
            idx = min(call_count, len(responses) - 1)
            call_count += 1
            return responses[idx]

        mock_client = AsyncMock()
        mock_client.get = mock_get

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await discover_oauth_metadata("https://mcp.example.com/mcp")

        assert result is not None
        assert result.authorization_endpoint == "https://auth.example.com/authorize"

    @pytest.mark.asyncio
    async def test_cache_hit(self) -> None:
        import time

        cached_meta = OAuthMetadata(issuer="cached-issuer")
        _discovery_mod._metadata_cache["https://mcp.cached.com/mcp"] = {
            "metadata": cached_meta,
            "cached_at": time.monotonic(),
        }
        result = await discover_oauth_metadata("https://mcp.cached.com/mcp")
        assert result is not None
        assert result.issuer == "cached-issuer"

    @pytest.mark.asyncio
    async def test_cache_expired(self) -> None:
        import time

        cached_meta = OAuthMetadata(issuer="stale")
        _discovery_mod._metadata_cache["https://mcp.stale.com/mcp"] = {
            "metadata": cached_meta,
            "cached_at": time.monotonic() - _METADATA_CACHE_TTL - 100,
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_mock_response(404))

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await discover_oauth_metadata("https://mcp.stale.com/mcp")

        assert result is None

    @pytest.mark.asyncio
    async def test_discovered_auth_server_ssrf_rejected(self) -> None:
        resource_resp = _mock_response(
            200,
            json_data={"authorization_servers": ["ftp://evil.com/steal"]},
        )

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resource_resp)

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await discover_oauth_metadata("https://mcp.example.com/mcp")

        assert result is None

    @pytest.mark.asyncio
    async def test_rfc9728_single_value_field(self) -> None:
        """Single-value authorization_server field (not the list variant)."""
        resource_resp = _mock_response(
            200,
            # authorization_servers is empty list → fallback to singular field
            json_data={
                "authorization_servers": [],
                "authorization_server": "https://auth.single.com",
            },
        )
        oidc_resp = _mock_response(
            200,
            json_data={
                "issuer": "https://auth.single.com",
                "authorization_endpoint": "https://auth.single.com/authorize",
                "token_endpoint": "https://auth.single.com/token",
            },
        )
        rfc8414_resp = _mock_response(404)

        call_count = 0
        responses = [resource_resp, rfc8414_resp, oidc_resp]

        async def mock_get(url: str) -> MagicMock:
            nonlocal call_count
            idx = min(call_count, len(responses) - 1)
            call_count += 1
            return responses[idx]

        mock_client = AsyncMock()
        mock_client.get = mock_get

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await discover_oauth_metadata("https://mcp.example.com/v2")

        assert result is not None
        assert result.issuer == "https://auth.single.com"

    @pytest.mark.asyncio
    async def test_rfc8414_and_oidc_merge(self) -> None:
        resource_resp = _mock_response(
            200,
            json_data={"authorization_servers": ["https://auth.example.com"]},
        )
        rfc8414_resp = _mock_response(
            200,
            json_data={
                "issuer": "https://auth.example.com",
                "authorization_endpoint": "https://auth.example.com/authorize-8414",
                "token_endpoint": "https://auth.example.com/token-8414",
                "code_challenge_methods_supported": ["S256"],
            },
        )
        oidc_resp = _mock_response(
            200,
            json_data={
                "issuer": "https://auth.example.com",
                "authorization_endpoint": "https://auth.example.com/authorize-oidc",
                "token_endpoint": "https://auth.example.com/token-oidc",
                "registration_endpoint": "https://auth.example.com/register",
                "scopes_supported": ["openid", "profile"],
            },
        )

        call_count = 0
        responses = [resource_resp, rfc8414_resp, oidc_resp]

        async def mock_get(url: str) -> MagicMock:
            nonlocal call_count
            idx = min(call_count, len(responses) - 1)
            call_count += 1
            return responses[idx]

        mock_client = AsyncMock()
        mock_client.get = mock_get

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await discover_oauth_metadata("https://mcp.example.com/mcp")

        assert result is not None
        assert result.authorization_endpoint == "https://auth.example.com/authorize-8414"
        assert result.token_endpoint == "https://auth.example.com/token-8414"
        assert result.supports_pkce is True
        assert result.registration_endpoint == "https://auth.example.com/register"

    @pytest.mark.asyncio
    async def test_network_error_returns_none(self) -> None:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=OSError("connection reset"))

        with patch("httpx.AsyncClient") as mock_cls:
            mock_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await discover_oauth_metadata("https://mcp.example.com/mcp")

        assert result is None
