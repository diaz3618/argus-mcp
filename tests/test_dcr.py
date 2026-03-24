"""Tests for Dynamic Client Registration (RFC 7591) — ``argus_mcp.bridge.auth.dcr``."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from argus_mcp.bridge.auth.dcr import (
    _DEFAULT_CACHE_TTL,
    _GATEWAY_GRANT_TYPES,
    ClientRegistration,
    DCRClient,
    _registration_cache,
)
from argus_mcp.bridge.auth.discovery import OAuthMetadata

# Helpers


def _make_metadata(
    *,
    issuer: str = "https://auth.example.com",
    registration_endpoint: str = "https://auth.example.com/register",
    grant_types_supported: Optional[List[str]] = None,
    **kwargs: Any,
) -> OAuthMetadata:
    raw: Dict[str, Any] = {"issuer": issuer}
    if grant_types_supported is not None:
        raw["grant_types_supported"] = grant_types_supported
    raw.update(kwargs)
    return OAuthMetadata(
        issuer=issuer,
        authorization_endpoint=f"{issuer}/authorize",
        token_endpoint=f"{issuer}/token",
        registration_endpoint=registration_endpoint,
        raw=raw,
    )


def _make_dcr_response(
    *,
    client_id: str = "test-client-id",
    client_secret: str = "test-secret",
    grant_types: Optional[List[str]] = None,
    **extra: Any,
) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_types": grant_types or ["authorization_code", "client_credentials"],
        "token_endpoint_auth_method": "client_secret_post",
    }
    data.update(extra)
    return data


def _mock_httpx_response(
    status_code: int = 201,
    json_data: Optional[Dict[str, Any]] = None,
    text: str = "",
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text or str(json_data or {})
    return resp


# Fixtures


@pytest.fixture(autouse=True)
def _clear_cache():
    """Clear DCR cache before and after each test."""
    _registration_cache.clear()
    yield
    _registration_cache.clear()


# ClientRegistration dataclass


class TestClientRegistration:
    def test_basic_creation(self):
        reg = ClientRegistration(client_id="cid", client_secret="sec")
        assert reg.client_id == "cid"
        assert reg.client_secret == "sec"
        assert reg.is_expired is False

    def test_not_expired_when_zero(self):
        reg = ClientRegistration(client_id="cid", client_secret_expires_at=0)
        assert reg.is_expired is False

    def test_not_expired_when_future(self):
        future = int(time.time()) + 86400
        reg = ClientRegistration(client_id="cid", client_secret_expires_at=future)
        assert reg.is_expired is False

    def test_expired_when_past(self):
        past = int(time.time()) - 1
        reg = ClientRegistration(client_id="cid", client_secret_expires_at=past)
        assert reg.is_expired is True

    def test_frozen(self):
        reg = ClientRegistration(client_id="cid")
        with pytest.raises(AttributeError):
            reg.client_id = "new"  # type: ignore[misc]


# DCRClient construction


class TestDCRClientInit:
    def test_default_params(self):
        dcr = DCRClient()
        assert dcr._allowlist == frozenset()
        assert dcr._cache_ttl == _DEFAULT_CACHE_TTL
        assert dcr._client_name == "argus-mcp-gateway"
        assert dcr._redirect_uris == []

    def test_custom_params(self):
        dcr = DCRClient(
            issuer_allowlist=["https://a.example.com"],
            cache_ttl=600,
            client_name="test",
            redirect_uris=["https://localhost/callback"],
        )
        assert dcr._allowlist == frozenset({"https://a.example.com"})
        assert dcr._cache_ttl == 600
        assert dcr._client_name == "test"
        assert dcr._redirect_uris == ["https://localhost/callback"]

    def test_negative_ttl_clamps_to_zero(self):
        dcr = DCRClient(cache_ttl=-5)
        assert dcr._cache_ttl == 0.0


# Grant type negotiation


class TestGrantTypeNegotiation:
    def test_full_overlap(self):
        dcr = DCRClient()
        meta = _make_metadata(
            grant_types_supported=["authorization_code", "client_credentials", "refresh_token"]
        )
        result = dcr._negotiate_grant_types(meta)
        assert set(result) == _GATEWAY_GRANT_TYPES

    def test_partial_overlap(self):
        dcr = DCRClient()
        meta = _make_metadata(grant_types_supported=["client_credentials", "device_code"])
        result = dcr._negotiate_grant_types(meta)
        assert result == ["client_credentials"]

    def test_no_overlap(self):
        dcr = DCRClient()
        meta = _make_metadata(grant_types_supported=["device_code", "urn:custom"])
        result = dcr._negotiate_grant_types(meta)
        assert result == []

    def test_as_does_not_advertise_grants(self):
        dcr = DCRClient()
        meta = _make_metadata()  # No grant_types_supported in raw
        result = dcr._negotiate_grant_types(meta)
        assert set(result) == _GATEWAY_GRANT_TYPES


# Registration body


class TestRegistrationBody:
    def test_client_credentials_only(self):
        dcr = DCRClient(client_name="test-gw")
        body = dcr._build_registration_body(["client_credentials"])
        assert body["client_name"] == "test-gw"
        assert body["grant_types"] == ["client_credentials"]
        assert "response_types" not in body
        assert "redirect_uris" not in body

    def test_authorization_code_includes_response_types(self):
        dcr = DCRClient(redirect_uris=["https://localhost/callback"])
        body = dcr._build_registration_body(["authorization_code"])
        assert body["response_types"] == ["code"]
        assert body["redirect_uris"] == ["https://localhost/callback"]

    def test_no_redirect_uris_when_empty(self):
        dcr = DCRClient()
        body = dcr._build_registration_body(["client_credentials"])
        assert "redirect_uris" not in body


# register() — success path


class TestRegisterSuccess:
    async def test_successful_registration(self):
        dcr = DCRClient()
        meta = _make_metadata()
        resp = _mock_httpx_response(201, _make_dcr_response())

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            reg = await dcr.register(meta)

        assert reg is not None
        assert reg.client_id == "test-client-id"
        assert reg.client_secret == "test-secret"

    async def test_200_also_accepted(self):
        dcr = DCRClient()
        meta = _make_metadata()
        resp = _mock_httpx_response(200, _make_dcr_response(client_id="ok"))

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            reg = await dcr.register(meta)

        assert reg is not None
        assert reg.client_id == "ok"


# register() — caching


class TestRegisterCaching:
    async def test_cached_result_returned(self):
        dcr = DCRClient()
        meta = _make_metadata()

        # Pre-populate cache
        _registration_cache["https://auth.example.com/register"] = {
            "registration": ClientRegistration(client_id="cached"),
            "cached_at": time.monotonic(),
        }

        reg = await dcr.register(meta)
        assert reg is not None
        assert reg.client_id == "cached"

    async def test_expired_cache_triggers_new_registration(self):
        dcr = DCRClient(cache_ttl=1)
        meta = _make_metadata()

        # Pre-populate with expired entry
        _registration_cache["https://auth.example.com/register"] = {
            "registration": ClientRegistration(client_id="old"),
            "cached_at": time.monotonic() - 10,
        }

        resp = _mock_httpx_response(201, _make_dcr_response(client_id="fresh"))
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            reg = await dcr.register(meta)

        assert reg is not None
        assert reg.client_id == "fresh"

    async def test_expired_client_secret_triggers_re_registration(self):
        dcr = DCRClient(cache_ttl=9999)
        meta = _make_metadata()

        past = int(time.time()) - 1
        _registration_cache["https://auth.example.com/register"] = {
            "registration": ClientRegistration(
                client_id="sec-expired", client_secret_expires_at=past
            ),
            "cached_at": time.monotonic(),
        }

        resp = _mock_httpx_response(201, _make_dcr_response(client_id="renewed"))
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            reg = await dcr.register(meta)

        assert reg is not None
        assert reg.client_id == "renewed"

    async def test_successful_registration_populates_cache(self):
        dcr = DCRClient()
        meta = _make_metadata()
        resp = _mock_httpx_response(201, _make_dcr_response(client_id="new"))

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            await dcr.register(meta)

        assert "https://auth.example.com/register" in _registration_cache

    def test_clear_cache(self):
        _registration_cache["x"] = {"cached_at": 0}
        dcr = DCRClient()
        dcr.clear_cache()
        assert len(_registration_cache) == 0


# register() — failure paths


class TestRegisterFailures:
    async def test_no_registration_endpoint(self):
        dcr = DCRClient()
        meta = _make_metadata(registration_endpoint="")
        result = await dcr.register(meta)
        assert result is None

    async def test_issuer_not_in_allowlist(self):
        dcr = DCRClient(issuer_allowlist=["https://trusted.example.com"])
        meta = _make_metadata(issuer="https://untrusted.example.com")
        with pytest.raises(ValueError, match="not in the allowed issuers"):
            await dcr.register(meta)

    async def test_http_error(self):
        dcr = DCRClient()
        meta = _make_metadata()
        resp = _mock_httpx_response(400, text="Bad Request")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await dcr.register(meta)

        assert result is None

    async def test_connection_error(self):
        dcr = DCRClient()
        meta = _make_metadata()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=ConnectionError("refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await dcr.register(meta)

        assert result is None

    async def test_invalid_json_response(self):
        dcr = DCRClient()
        meta = _make_metadata()

        resp = _mock_httpx_response(201)
        resp.json.side_effect = ValueError("not json")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await dcr.register(meta)

        assert result is None

    async def test_missing_client_id_in_response(self):
        dcr = DCRClient()
        meta = _make_metadata()

        resp = _mock_httpx_response(201, {"client_secret": "sec_only"})

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await dcr.register(meta)

        assert result is None

    async def test_ssrf_rejected_endpoint(self):
        dcr = DCRClient()
        meta = _make_metadata(registration_endpoint="ftp://malicious.example.com/register")
        with pytest.raises(ValueError, match="Unsupported scheme"):
            await dcr.register(meta)

    async def test_no_overlap_still_attempts(self):
        """When grant type intersection is empty, registration is still attempted."""
        dcr = DCRClient()
        meta = _make_metadata(grant_types_supported=["device_code"])

        resp = _mock_httpx_response(201, _make_dcr_response(client_id="fallback"))
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            reg = await dcr.register(meta)

        assert reg is not None
        assert reg.client_id == "fallback"


# Issuer allowlist


class TestIssuerAllowlist:
    async def test_empty_allowlist_allows_all(self):
        dcr = DCRClient(issuer_allowlist=[])
        meta = _make_metadata(issuer="https://any.example.com")

        resp = _mock_httpx_response(201, _make_dcr_response())
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            reg = await dcr.register(meta)

        assert reg is not None

    async def test_allowlist_accepts_matching_issuer(self):
        dcr = DCRClient(issuer_allowlist=["https://auth.example.com"])
        meta = _make_metadata(issuer="https://auth.example.com")

        resp = _mock_httpx_response(201, _make_dcr_response())
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            reg = await dcr.register(meta)

        assert reg is not None

    async def test_allowlist_rejects_non_matching(self):
        dcr = DCRClient(issuer_allowlist=["https://only-this.example.com"])
        meta = _make_metadata(issuer="https://other.example.com")
        with pytest.raises(ValueError, match="not in the allowed issuers"):
            await dcr.register(meta)
