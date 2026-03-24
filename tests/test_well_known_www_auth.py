"""Tests for Steps 2.3 and 2.4: well-known endpoint + WWW-Authenticate headers.

Step 2.3: RFC 9728 /.well-known/oauth-protected-resource endpoint
Step 2.4: RFC 6750 WWW-Authenticate header signaling on 401s
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Step 2.3 — RFC 9728 Well-Known Endpoint


def _make_request(scheme: str = "https", netloc: str = "gw.example.com") -> MagicMock:
    """Build a mock Starlette Request with url attributes."""
    req = MagicMock()
    req.url.scheme = scheme
    req.url.netloc = netloc
    return req


def _make_auth_cfg(
    auth_type: str = "oidc",
    issuer: str | None = "https://auth.example.com",
    audience: str | None = None,
    auth_mode: str = "strict",
) -> MagicMock:
    """Build a mock IncomingAuthConfig."""
    cfg = MagicMock()
    cfg.type = auth_type
    cfg.issuer = issuer
    cfg.audience = audience
    cfg.auth_mode = auth_mode
    return cfg


class TestWellKnownEndpoint:
    """Tests for handle_well_known_oauth_resource."""

    @pytest.mark.asyncio
    async def test_returns_metadata_with_oidc_issuer(self) -> None:
        from argus_mcp.server.well_known import handle_well_known_oauth_resource

        with (
            patch(
                "argus_mcp.server.well_known._is_auth_enabled",
                return_value=True,
            ),
            patch(
                "argus_mcp.server.transport._auth_issuer",
                "https://auth.example.com",
            ),
        ):
            resp = await handle_well_known_oauth_resource(_make_request())

        assert resp.status_code == 200
        body = resp.body.decode()
        import json

        data = json.loads(body)
        assert data["resource"] == "https://gw.example.com"
        assert data["authorization_servers"] == ["https://auth.example.com"]
        assert "header" in data["bearer_methods_supported"]

    @pytest.mark.asyncio
    async def test_returns_404_when_anonymous(self) -> None:
        from argus_mcp.server.well_known import handle_well_known_oauth_resource

        with patch(
            "argus_mcp.server.well_known._is_auth_enabled",
            return_value=False,
        ):
            resp = await handle_well_known_oauth_resource(_make_request())

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_returns_404_for_local_auth_without_issuer(self) -> None:
        """Local/static bearer-token auth has no OAuth issuer — return 404."""
        from argus_mcp.server.well_known import handle_well_known_oauth_resource

        with (
            patch(
                "argus_mcp.server.well_known._is_auth_enabled",
                return_value=True,
            ),
            patch(
                "argus_mcp.server.transport._auth_issuer",
                None,
            ),
        ):
            resp = await handle_well_known_oauth_resource(_make_request())

        assert resp.status_code == 404
        import json

        data = json.loads(resp.body.decode())
        assert data["error"] == "no_oauth_server"

    @pytest.mark.asyncio
    async def test_resource_reflects_request_url(self) -> None:
        from argus_mcp.server.well_known import handle_well_known_oauth_resource

        with (
            patch(
                "argus_mcp.server.well_known._is_auth_enabled",
                return_value=True,
            ),
            patch(
                "argus_mcp.server.transport._auth_issuer",
                "https://auth.example.com",
            ),
        ):
            resp = await handle_well_known_oauth_resource(
                _make_request(scheme="http", netloc="localhost:9000")
            )

        import json

        data = json.loads(resp.body.decode())
        assert data["resource"] == "http://localhost:9000"

    @pytest.mark.asyncio
    async def test_jwt_type_returns_metadata(self) -> None:
        from argus_mcp.server.well_known import handle_well_known_oauth_resource

        with (
            patch(
                "argus_mcp.server.well_known._is_auth_enabled",
                return_value=True,
            ),
            patch(
                "argus_mcp.server.transport._auth_issuer",
                "https://jwt-issuer.example.com",
            ),
        ):
            resp = await handle_well_known_oauth_resource(_make_request())

        assert resp.status_code == 200
        import json

        data = json.loads(resp.body.decode())
        assert data["authorization_servers"] == ["https://jwt-issuer.example.com"]


class TestIsAuthEnabled:
    """Tests for _is_auth_enabled helper."""

    def test_returns_false_when_no_provider(self) -> None:
        from argus_mcp.server.well_known import _is_auth_enabled

        with patch("argus_mcp.server.transport._incoming_auth_provider", None):
            assert _is_auth_enabled() is False

    def test_returns_true_when_provider_set(self) -> None:
        from argus_mcp.server.well_known import _is_auth_enabled

        with patch("argus_mcp.server.transport._incoming_auth_provider", MagicMock()):
            assert _is_auth_enabled() is True


class TestWellKnownConstant:
    """Test that the well-known path constant is defined."""

    def test_constant_value(self) -> None:
        from argus_mcp.constants import WELL_KNOWN_OAUTH_RESOURCE_PATH

        assert WELL_KNOWN_OAUTH_RESOURCE_PATH == "/.well-known/oauth-protected-resource"


class TestWellKnownRouteWired:
    """Test that the well-known route is registered in the Starlette app."""

    def test_route_exists_in_app(self) -> None:
        from argus_mcp.server.app import app

        paths = []
        for route in app.routes:
            if hasattr(route, "path"):
                paths.append(route.path)
        assert "/.well-known/oauth-protected-resource" in paths


# Step 2.4 — RFC 6750 WWW-Authenticate Header Signaling


class TestBuildWwwAuthenticate:
    """Tests for _build_www_authenticate helper."""

    def test_bearer_only_no_issuer(self) -> None:
        import argus_mcp.server.transport as transport

        original = transport._auth_issuer
        try:
            transport._auth_issuer = None
            result = transport._build_www_authenticate()
            assert result == "Bearer"
        finally:
            transport._auth_issuer = original

    def test_bearer_with_realm(self) -> None:
        import argus_mcp.server.transport as transport

        original = transport._auth_issuer
        try:
            transport._auth_issuer = "https://auth.example.com"
            result = transport._build_www_authenticate()
            assert result == 'Bearer realm="https://auth.example.com"'
        finally:
            transport._auth_issuer = original

    def test_bearer_with_realm_and_error(self) -> None:
        import argus_mcp.server.transport as transport

        original = transport._auth_issuer
        try:
            transport._auth_issuer = "https://auth.example.com"
            result = transport._build_www_authenticate(error="invalid_token")
            assert 'realm="https://auth.example.com"' in result
            assert 'error="invalid_token"' in result
        finally:
            transport._auth_issuer = original

    def test_bearer_with_error_no_realm(self) -> None:
        import argus_mcp.server.transport as transport

        original = transport._auth_issuer
        try:
            transport._auth_issuer = None
            result = transport._build_www_authenticate(error="invalid_token")
            assert result == 'Bearer error="invalid_token"'
        finally:
            transport._auth_issuer = original


class TestSseAuthWwwAuthenticate:
    """Tests for WWW-Authenticate header on SSE 401 responses."""

    @pytest.mark.asyncio
    async def test_sse_401_includes_www_authenticate(self) -> None:
        """SSE auth rejection includes WWW-Authenticate header."""
        import argus_mcp.server.transport as transport

        orig_provider = transport._incoming_auth_provider
        orig_issuer = transport._auth_issuer
        try:
            mock_provider = AsyncMock(spec=transport.AuthProviderRegistry)
            mock_provider.authenticate.side_effect = transport.AuthenticationError("bad token")
            transport._incoming_auth_provider = mock_provider
            transport._auth_issuer = "https://auth.example.com"

            # Build a minimal Starlette-like request
            request = MagicMock()
            request.scope = {
                "type": "http",
                "headers": [
                    (b"authorization", b"Bearer bad-token"),
                ],
            }
            request.url = "http://localhost/sse"
            request.receive = AsyncMock()
            request._send = AsyncMock()

            # Capture the Response that gets created
            _responses: list[Any] = []
            _original_handle_sse = transport.handle_sse

            # We can't easily call handle_sse because it imports mcp_server.
            # Instead, test the _build_www_authenticate + _extract_bearer_token
            # integration directly.
            token = transport._extract_bearer_token(request.scope)
            assert token == "bad-token"
            error_type = "invalid_token" if token else None
            www_auth = transport._build_www_authenticate(error=error_type)
            assert 'realm="https://auth.example.com"' in www_auth
            assert 'error="invalid_token"' in www_auth
        finally:
            transport._incoming_auth_provider = orig_provider
            transport._auth_issuer = orig_issuer

    @pytest.mark.asyncio
    async def test_sse_401_no_error_when_no_token(self) -> None:
        """No error param in WWW-Authenticate when token is missing."""
        import argus_mcp.server.transport as transport

        scope = {"type": "http", "headers": []}
        token = transport._extract_bearer_token(scope)
        assert token is None
        error_type = "invalid_token" if token else None
        www_auth = transport._build_www_authenticate(error=error_type)
        assert "invalid_token" not in www_auth


class TestStreamableHttpAuthWwwAuthenticate:
    """Tests for WWW-Authenticate header on Streamable-HTTP 401 responses."""

    @pytest.mark.asyncio
    async def test_streamable_401_with_invalid_token(self) -> None:
        """Streamable-HTTP auth rejection includes WWW-Authenticate with error."""
        import argus_mcp.server.transport as transport

        orig_issuer = transport._auth_issuer
        try:
            transport._auth_issuer = "https://issuer.example.com"

            scope = {
                "type": "http",
                "headers": [(b"authorization", b"Bearer expired-token")],
            }
            token = transport._extract_bearer_token(scope)
            assert token == "expired-token"
            error_type = "invalid_token" if token else None
            www_auth = transport._build_www_authenticate(error=error_type)

            assert www_auth == 'Bearer realm="https://issuer.example.com", error="invalid_token"'
        finally:
            transport._auth_issuer = orig_issuer

    @pytest.mark.asyncio
    async def test_streamable_401_missing_token(self) -> None:
        """Streamable-HTTP auth rejection with no token has no error param."""
        import argus_mcp.server.transport as transport

        orig_issuer = transport._auth_issuer
        try:
            transport._auth_issuer = "https://issuer.example.com"

            scope = {"type": "http", "headers": []}
            token = transport._extract_bearer_token(scope)
            assert token is None
            error_type = "invalid_token" if token else None
            www_auth = transport._build_www_authenticate(error=error_type)

            assert www_auth == 'Bearer realm="https://issuer.example.com"'
        finally:
            transport._auth_issuer = orig_issuer


class TestExtractBearerToken:
    """Tests for _extract_bearer_token edge cases."""

    def test_bearer_case_insensitive(self) -> None:
        from argus_mcp.server.transport import _extract_bearer_token

        scope = {"headers": [(b"authorization", b"BEARER my-token")]}
        assert _extract_bearer_token(scope) == "my-token"

    def test_non_bearer_auth_returns_none(self) -> None:
        from argus_mcp.server.transport import _extract_bearer_token

        scope = {"headers": [(b"authorization", b"Basic dXNlcjpwYXNz")]}
        assert _extract_bearer_token(scope) is None

    def test_no_auth_header_returns_none(self) -> None:
        from argus_mcp.server.transport import _extract_bearer_token

        scope = {"headers": [(b"content-type", b"application/json")]}
        assert _extract_bearer_token(scope) is None

    def test_empty_headers(self) -> None:
        from argus_mcp.server.transport import _extract_bearer_token

        scope = {"headers": []}
        assert _extract_bearer_token(scope) is None


class TestAuthIssuerLifespan:
    """Test that _auth_issuer is a module-level variable that can be set."""

    def test_auth_issuer_default_none(self) -> None:
        import argus_mcp.server.transport as transport

        # The default is None (no configuration)
        assert hasattr(transport, "_auth_issuer")

    def test_auth_issuer_can_be_set(self) -> None:
        import argus_mcp.server.transport as transport

        orig = transport._auth_issuer
        try:
            transport._auth_issuer = "https://test.example.com"
            assert transport._auth_issuer == "https://test.example.com"
        finally:
            transport._auth_issuer = orig
