"""Tests for argus_mcp.server.auth.oidc — OIDC discovery client.

Covers:
- OIDCConfig dataclass construction
- OIDCDiscovery: fetch(), refresh(), caching, error handling
- OIDCDiscoveryError exception
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus_mcp.server.auth.oidc import (
    OIDCConfig,
    OIDCDiscovery,
    OIDCDiscoveryError,
)


class TestOIDCConfig:
    def test_construction(self):
        cfg = OIDCConfig(
            issuer="https://auth.example.com",
            jwks_uri="https://auth.example.com/.well-known/jwks.json",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            raw={"issuer": "https://auth.example.com"},
        )
        assert cfg.issuer == "https://auth.example.com"
        assert cfg.jwks_uri.endswith("jwks.json")

    def test_frozen(self):
        from dataclasses import FrozenInstanceError

        cfg = OIDCConfig(
            issuer="https://auth.example.com",
            jwks_uri="https://auth.example.com/jwks",
            authorization_endpoint="",
            token_endpoint="",
            raw={},
        )
        with pytest.raises(FrozenInstanceError):
            cfg.issuer = "changed"  # type: ignore[misc]


class TestOIDCDiscoveryError:
    def test_is_exception(self):
        err = OIDCDiscoveryError("something went wrong")
        assert isinstance(err, Exception)
        assert str(err) == "something went wrong"


class TestOIDCDiscovery:
    def test_init(self):
        disco = OIDCDiscovery("https://auth.example.com", timeout=5.0)
        assert disco._issuer == "https://auth.example.com"
        assert disco._timeout == 5.0
        assert disco._cached is None

    @pytest.mark.asyncio
    async def test_fetch_success(self):
        """Successful OIDC discovery fetch."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "issuer": "https://auth.example.com",
            "jwks_uri": "https://auth.example.com/.well-known/jwks.json",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            disco = OIDCDiscovery("https://auth.example.com")
            result = await disco.fetch()

        assert isinstance(result, OIDCConfig)
        assert result.issuer == "https://auth.example.com"
        assert result.jwks_uri.endswith("jwks.json")

    @pytest.mark.asyncio
    async def test_fetch_caches_result(self):
        """Second fetch returns cached result without HTTP call."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "issuer": "https://auth.example.com",
            "jwks_uri": "https://auth.example.com/jwks",
            "authorization_endpoint": "",
            "token_endpoint": "",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            disco = OIDCDiscovery("https://auth.example.com")
            r1 = await disco.fetch()
            r2 = await disco.fetch()

        assert r1 is r2  # Same object — cached
        mock_client.get.assert_called_once()  # Only 1 HTTP call

    @pytest.mark.asyncio
    async def test_fetch_missing_jwks_uri(self):
        """Raises OIDCDiscoveryError when jwks_uri is missing."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "issuer": "https://auth.example.com",
            # No jwks_uri!
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client):
            disco = OIDCDiscovery("https://auth.example.com")
            with pytest.raises(OIDCDiscoveryError):
                await disco.fetch()

    @pytest.mark.asyncio
    async def test_refresh_clears_cache(self):
        """refresh() clears the cached config so next fetch re-fetches."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "issuer": "https://auth.example.com",
            "jwks_uri": "https://auth.example.com/jwks",
            "authorization_endpoint": "",
            "token_endpoint": "",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.get = AsyncMock(return_value=mock_response)

        disco = OIDCDiscovery("https://auth.example.com")
        # Manually set cache
        disco._cached = OIDCConfig(
            issuer="old", jwks_uri="old", authorization_endpoint="", token_endpoint="", raw={}
        )
        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await disco.refresh()
        # refresh() should have re-fetched, returning new config
        assert result.issuer == "https://auth.example.com"
        assert result.jwks_uri.endswith("/jwks")
