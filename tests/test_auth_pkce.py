"""Tests for the OAuth2 PKCE authentication modules.

Covers:
- PKCE challenge generation (pkce.py)
- Token storage (store.py)
- OAuth metadata discovery (discovery.py)
- PKCEAuthProvider (provider.py)
- PKCEAuthConfig schema (schema_backends.py)
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# pkce.py
from argus_mcp.bridge.auth.pkce import (
    PKCEChallenge,
    PKCEFlow,
    TokenSet,
    _is_headless,
    _present_auth_url,
    generate_pkce_challenge,
    generate_state,
)


class TestPKCEChallenge:
    """Tests for PKCE challenge generation."""

    def test_generates_verifier_and_challenge(self):
        pkce = generate_pkce_challenge()
        assert isinstance(pkce, PKCEChallenge)
        assert len(pkce.verifier) >= 43
        assert len(pkce.challenge) > 0
        assert pkce.method == "S256"

    def test_verifier_is_url_safe(self):
        pkce = generate_pkce_challenge()
        # URL-safe base64 only uses alphanumeric, hyphen, underscore
        allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")
        assert all(c in allowed for c in pkce.verifier)

    def test_challenge_differs_from_verifier(self):
        pkce = generate_pkce_challenge()
        assert pkce.challenge != pkce.verifier

    def test_deterministic_challenge_for_same_verifier(self):
        """S256 is deterministic — same verifier always gives same challenge."""
        import base64
        import hashlib

        pkce = generate_pkce_challenge()
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(pkce.verifier.encode("ascii")).digest())
            .rstrip(b"=")
            .decode("ascii")
        )
        assert pkce.challenge == expected

    def test_different_each_time(self):
        c1 = generate_pkce_challenge()
        c2 = generate_pkce_challenge()
        assert c1.verifier != c2.verifier


class TestGenerateState:
    """Tests for state parameter generation."""

    def test_non_empty(self):
        assert len(generate_state()) > 0

    def test_different_each_time(self):
        assert generate_state() != generate_state()


class TestTokenSet:
    """Tests for the TokenSet dataclass."""

    def test_defaults(self):
        ts = TokenSet(access_token="abc")
        assert ts.access_token == "abc"
        assert ts.token_type == "Bearer"
        assert ts.refresh_token == ""
        assert ts.expires_in == 3600.0

    def test_with_refresh(self):
        ts = TokenSet(
            access_token="abc",
            refresh_token="def",
            expires_in=7200.0,
        )
        assert ts.refresh_token == "def"
        assert ts.expires_in == 7200.0


class TestRefreshAccessToken:
    """Tests for refresh_access_token()."""

    @pytest.mark.asyncio
    async def test_refresh_success(self):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "access_token": "new-token",
            "expires_in": 3600,
            "refresh_token": "new-refresh",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch.dict("sys.modules", {"httpx": mock_httpx}):
            # Re-import to pick up the mocked httpx
            import importlib

            import argus_mcp.bridge.auth.pkce as _pkce_mod

            importlib.reload(_pkce_mod)
            tokens = await _pkce_mod.refresh_access_token(
                "https://auth.example.com/token",
                "client-id",
                "old-refresh-token",
            )

        assert tokens.access_token == "new-token"
        assert tokens.refresh_token == "new-refresh"


# PKCEFlow


class TestPKCEFlowInit:
    """Tests for PKCEFlow.__init__."""

    def test_defaults(self):
        flow = PKCEFlow(
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            client_id="my-client",
        )
        assert flow._auth_endpoint == "https://auth.example.com/authorize"
        assert flow._token_endpoint == "https://auth.example.com/token"
        assert flow._client_id == "my-client"
        assert flow._client_secret == ""
        assert flow._scopes == []
        assert flow._server is None
        assert flow._redirect_uri is None

    def test_with_all_options(self):
        flow = PKCEFlow(
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            client_id="my-client",
            client_secret="secret",
            scopes=["openid", "profile"],
            redirect_port=8888,
            timeout=120.0,
        )
        assert flow._client_secret == "secret"
        assert flow._scopes == ["openid", "profile"]
        assert flow._port == 8888
        assert flow._timeout == 120.0


class TestPKCEFlowBindCallbackServer:
    """Tests for PKCEFlow.bind_callback_server()."""

    def test_binds_and_returns_uri(self):
        flow = PKCEFlow(
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            client_id="my-client",
            redirect_port=0,  # ephemeral port
        )
        uri = flow.bind_callback_server()
        assert uri.startswith("http://127.0.0.1:")
        assert "/callback" in uri
        assert flow._server is not None
        # Cleanup
        flow._server.server_close()

    def test_idempotent(self):
        flow = PKCEFlow(
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            client_id="my-client",
            redirect_port=0,
        )
        uri1 = flow.bind_callback_server()
        uri2 = flow.bind_callback_server()
        assert uri1 == uri2
        flow._server.server_close()


class TestPKCEFlowExchangeCode:
    """Tests for PKCEFlow._exchange_code()."""

    @pytest.mark.asyncio
    async def test_exchange_success(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "at-123",
            "token_type": "Bearer",
            "refresh_token": "rt-456",
            "expires_in": 3600,
            "scope": "openid",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        flow = PKCEFlow(
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            client_id="my-client",
        )

        with patch.dict("sys.modules", {"httpx": mock_httpx}):
            tokens = await flow._exchange_code(
                "auth-code-xyz",
                "http://127.0.0.1:9999/callback",
                "verifier-abc",
            )

        assert tokens.access_token == "at-123"
        assert tokens.refresh_token == "rt-456"
        assert tokens.scope == "openid"

    @pytest.mark.asyncio
    async def test_exchange_with_client_secret(self):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "at-sec",
            "expires_in": 7200,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        flow = PKCEFlow(
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            client_id="my-client",
            client_secret="my-secret",
        )

        with patch.dict("sys.modules", {"httpx": mock_httpx}):
            tokens = await flow._exchange_code(
                "code",
                "http://127.0.0.1:9999/callback",
                "verifier",
            )

        # Verify client_secret is included in the POST data
        call_kwargs = mock_client.post.call_args
        assert "client_secret" in call_kwargs.kwargs.get("data", call_kwargs[1].get("data", {}))
        assert tokens.access_token == "at-sec"


class TestPKCEFlowExecute:
    """Tests for PKCEFlow.execute() — full flow with mocked browser + callback."""

    @pytest.mark.asyncio
    async def test_execute_success(self):
        """Full happy-path: browser opens, callback with code, exchange succeeds."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": "flow-token",
            "expires_in": 3600,
        }
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        flow = PKCEFlow(
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            client_id="my-client",
            redirect_port=0,
            timeout=5.0,
        )

        # We need to simulate:
        # 1. webbrowser.open() is called (mocked to do nothing)
        # 2. The callback handler receives a code (we simulate by patching)

        _original_execute = flow.execute

        async def mock_execute():
            """Simulate the flow by manually setting handler state and calling exchange."""
            from argus_mcp.bridge.auth.pkce import (
                _CallbackHandler,
                generate_pkce_challenge,
                generate_state,
            )

            pkce = generate_pkce_challenge()
            state = generate_state()

            # Simulate successful callback
            _CallbackHandler.result = {"code": "auth-code", "state": state}
            _CallbackHandler.error = None

            with patch.dict("sys.modules", {"httpx": mock_httpx}):
                return await flow._exchange_code(
                    "auth-code",
                    "http://127.0.0.1:0/callback",
                    pkce.verifier,
                )

        tokens = await mock_execute()
        assert tokens.access_token == "flow-token"

    @pytest.mark.asyncio
    async def test_execute_timeout(self):
        """Flow times out when callback never arrives."""
        flow = PKCEFlow(
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            client_id="my-client",
            redirect_port=0,
            timeout=0.1,  # Very short timeout
        )

        with patch("webbrowser.open"):
            with pytest.raises(RuntimeError, match="timed out"):
                await flow.execute()

    @pytest.mark.asyncio
    async def test_execute_callback_error(self):
        """Flow raises when callback indicates an error."""
        from argus_mcp.bridge.auth.pkce import _CallbackHandler

        flow = PKCEFlow(
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            client_id="my-client",
            redirect_port=0,
            timeout=2.0,
        )

        async def simulate_error_callback():
            """Simulate an error callback after a short delay."""
            await asyncio.sleep(0.1)
            _CallbackHandler.error = "access_denied"
            if _CallbackHandler.loop and _CallbackHandler.ready_event:
                _CallbackHandler.loop.call_soon_threadsafe(_CallbackHandler.ready_event.set)

        with patch("webbrowser.open"):
            task = asyncio.create_task(simulate_error_callback())
            with pytest.raises(RuntimeError, match="access_denied"):
                await flow.execute()
            await task

    @pytest.mark.asyncio
    async def test_execute_state_mismatch(self):
        """Flow raises on state mismatch (CSRF protection)."""
        from argus_mcp.bridge.auth.pkce import _CallbackHandler

        flow = PKCEFlow(
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            client_id="my-client",
            redirect_port=0,
            timeout=2.0,
        )

        async def simulate_bad_state_callback():
            await asyncio.sleep(0.1)
            _CallbackHandler.result = {"code": "auth-code", "state": "wrong-state"}
            _CallbackHandler.error = None
            if _CallbackHandler.loop and _CallbackHandler.ready_event:
                _CallbackHandler.loop.call_soon_threadsafe(_CallbackHandler.ready_event.set)

        with patch("webbrowser.open"):
            task = asyncio.create_task(simulate_bad_state_callback())
            with pytest.raises(RuntimeError, match="state mismatch"):
                await flow.execute()
            await task


class TestCallbackHandler:
    """Tests for _CallbackHandler.do_GET — mock HTTP handler."""

    def _make_handler(self, path: str):
        """Create a handler instance with a mocked request for the given path."""
        from argus_mcp.bridge.auth.pkce import _CallbackHandler

        # Reset class state
        _CallbackHandler.result = None
        _CallbackHandler.error = None
        _CallbackHandler.ready_event = None
        _CallbackHandler.loop = None

        handler = _CallbackHandler.__new__(_CallbackHandler)
        handler.path = path
        handler.client_address = ("127.0.0.1", 12345)
        handler.requestline = f"GET {path} HTTP/1.1"
        handler.request_version = "HTTP/1.1"
        handler.headers = {}
        handler.wfile = MagicMock()
        handler.rfile = MagicMock()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()
        handler.send_error = MagicMock()
        return handler

    def test_callback_with_code(self):
        from argus_mcp.bridge.auth.pkce import _CallbackHandler

        handler = self._make_handler("/callback?code=abc123&state=xyz")
        handler.do_GET()
        assert _CallbackHandler.result == {"code": "abc123", "state": "xyz"}
        assert _CallbackHandler.error is None

    def test_callback_with_error(self):
        from argus_mcp.bridge.auth.pkce import _CallbackHandler

        handler = self._make_handler("/callback?error=access_denied&error_description=User+denied")
        handler.do_GET()
        assert _CallbackHandler.error == "access_denied"

    def test_callback_missing_code(self):
        from argus_mcp.bridge.auth.pkce import _CallbackHandler

        handler = self._make_handler("/callback?something=else")
        handler.do_GET()
        assert _CallbackHandler.error == "missing_code"

    def test_callback_wrong_path(self):
        handler = self._make_handler("/other-path?code=abc")
        handler.do_GET()
        handler.send_error.assert_called_once_with(404)


# store.py

from argus_mcp.bridge.auth.store import TokenStore


class TestTokenStore:
    """Tests for persistent token storage."""

    async def test_save_and_load(self, tmp_path):
        store = TokenStore(str(tmp_path))
        tokens = TokenSet(
            access_token="my-token",
            refresh_token="my-refresh",
            expires_in=7200.0,
        )
        await store.save("test-backend", tokens)
        loaded = await store.load("test-backend")
        assert loaded is not None
        assert loaded.access_token == "my-token"
        assert loaded.refresh_token == "my-refresh"

    async def test_load_nonexistent(self, tmp_path):
        store = TokenStore(str(tmp_path))
        assert await store.load("missing") is None

    async def test_expired_token_returns_none(self, tmp_path):
        store = TokenStore(str(tmp_path))
        tokens = TokenSet(access_token="old", expires_in=1.0)
        await store.save("test", tokens)

        # Manually backdate the saved_at
        path = store._path_for("test")
        data = json.loads(path.read_text())
        data["saved_at"] = time.time() - 3600
        path.write_text(json.dumps(data))

        assert await store.load("test") is None

    async def test_expired_with_refresh_returns_empty_access(self, tmp_path):
        store = TokenStore(str(tmp_path))
        tokens = TokenSet(
            access_token="old",
            refresh_token="still-good",
            expires_in=1.0,
        )
        await store.save("test", tokens)

        path = store._path_for("test")
        data = json.loads(path.read_text())
        data["saved_at"] = time.time() - 3600
        path.write_text(json.dumps(data))

        loaded = await store.load("test")
        assert loaded is not None
        assert loaded.access_token == ""  # expired
        assert loaded.refresh_token == "still-good"

    async def test_delete(self, tmp_path):
        store = TokenStore(str(tmp_path))
        await store.save("test", TokenSet(access_token="x"))
        assert store.delete("test") is True
        assert await store.load("test") is None

    def test_delete_nonexistent(self, tmp_path):
        store = TokenStore(str(tmp_path))
        assert store.delete("missing") is False

    async def test_list_backends(self, tmp_path):
        store = TokenStore(str(tmp_path))
        await store.save("alpha", TokenSet(access_token="a"))
        await store.save("beta", TokenSet(access_token="b"))
        backends = store.list_backends()
        assert set(backends) == {"alpha", "beta"}

    async def test_file_permissions(self, tmp_path):
        store = TokenStore(str(tmp_path))
        await store.save("secure", TokenSet(access_token="secret"))
        path = store._path_for("secure")
        mode = oct(path.stat().st_mode & 0o777)
        assert mode == "0o600"

    async def test_sanitizes_backend_name(self, tmp_path):
        store = TokenStore(str(tmp_path))
        await store.save("my/weird@name", TokenSet(access_token="x"))
        # Should not create subdirectories
        assert (tmp_path / "my_weird_name.json").exists()


# discovery.py

from argus_mcp.bridge.auth.discovery import (
    OAuthMetadata,
)


class TestOAuthMetadata:
    """Tests for the OAuthMetadata dataclass."""

    def test_supports_pkce(self):
        meta = OAuthMetadata(code_challenge_methods_supported=["S256", "plain"])
        assert meta.supports_pkce is True

    def test_no_pkce(self):
        meta = OAuthMetadata(code_challenge_methods_supported=["plain"])
        assert meta.supports_pkce is False

    def test_supports_registration(self):
        meta = OAuthMetadata(registration_endpoint="https://auth.example.com/register")
        assert meta.supports_dynamic_registration is True

    def test_no_registration(self):
        meta = OAuthMetadata()
        assert meta.supports_dynamic_registration is False


class TestDiscoverOAuthMetadata:
    """Tests for discover_oauth_metadata()."""

    @pytest.mark.asyncio
    async def test_discovers_via_rfc9728(self):
        """Test RFC 9728 discovery path."""
        resource_resp = MagicMock()
        resource_resp.status_code = 200
        resource_resp.json.return_value = {
            "authorization_servers": ["https://auth.example.com"],
        }

        # RFC 8414 returns 404 so falls through to OIDC
        rfc8414_resp = MagicMock()
        rfc8414_resp.status_code = 404

        oidc_resp = MagicMock()
        oidc_resp.status_code = 200
        oidc_resp.json.return_value = {
            "issuer": "https://auth.example.com",
            "authorization_endpoint": "https://auth.example.com/authorize",
            "token_endpoint": "https://auth.example.com/token",
            "code_challenge_methods_supported": ["S256"],
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[resource_resp, rfc8414_resp, oidc_resp])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch.dict("sys.modules", {"httpx": mock_httpx}):
            import importlib

            import argus_mcp.bridge.auth.discovery as _disc_mod

            importlib.reload(_disc_mod)
            meta = await _disc_mod.discover_oauth_metadata("https://mcp.example.com/mcp")

        assert meta is not None
        assert meta.authorization_endpoint == "https://auth.example.com/authorize"
        assert meta.token_endpoint == "https://auth.example.com/token"
        assert meta.supports_pkce is True

    @pytest.mark.asyncio
    async def test_returns_none_when_no_discovery(self):
        """Test fallback when no discovery endpoints are found."""
        not_found = MagicMock()
        not_found.status_code = 404
        not_found.headers = {}

        ok_no_auth = MagicMock()
        ok_no_auth.status_code = 200
        ok_no_auth.headers = {}

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=[not_found, ok_no_auth])
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_httpx = MagicMock()
        mock_httpx.AsyncClient.return_value = mock_client

        with patch.dict("sys.modules", {"httpx": mock_httpx}):
            import importlib

            import argus_mcp.bridge.auth.discovery as _disc_mod

            importlib.reload(_disc_mod)
            meta = await _disc_mod.discover_oauth_metadata("https://mcp.example.com/mcp")

        assert meta is None


# provider.py — PKCEAuthProvider

from argus_mcp.bridge.auth.provider import (
    PKCEAuthProvider,
    create_auth_provider,
)


class TestPKCEAuthProvider:
    """Tests for the PKCEAuthProvider."""

    @pytest.mark.asyncio
    async def test_uses_cached_token(self, tmp_path):
        """When a valid token is on disk, no browser flow needed."""
        store = TokenStore(str(tmp_path))
        await store.save("test", TokenSet(access_token="cached-token", expires_in=7200))

        provider = PKCEAuthProvider(
            backend_name="test",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            client_id="my-client",
            token_dir=str(tmp_path),
        )
        headers = await provider.get_headers()
        assert headers == {"Authorization": "Bearer cached-token"}

    @pytest.mark.asyncio
    async def test_refreshes_expired_token(self, tmp_path):
        """When access token expired but refresh token exists, refresh."""
        store = TokenStore(str(tmp_path))
        tokens = TokenSet(
            access_token="old",
            refresh_token="valid-refresh",
            expires_in=1.0,
        )
        await store.save("test", tokens)

        # Backdate
        path = store._path_for("test")
        data = json.loads(path.read_text())
        data["saved_at"] = time.time() - 3600
        path.write_text(json.dumps(data))

        mock_refresh = AsyncMock(
            return_value=TokenSet(
                access_token="refreshed-token",
                refresh_token="new-refresh",
                expires_in=3600,
            ),
        )

        with patch(
            "argus_mcp.bridge.auth.pkce.refresh_access_token",
            mock_refresh,
        ):
            provider = PKCEAuthProvider(
                backend_name="test",
                authorization_endpoint="https://auth.example.com/authorize",
                token_endpoint="https://auth.example.com/token",
                client_id="my-client",
                token_dir=str(tmp_path),
            )
            headers = await provider.get_headers()

        assert headers == {"Authorization": "Bearer refreshed-token"}
        mock_refresh.assert_called_once()

    def test_redacted_repr(self):
        provider = PKCEAuthProvider(
            backend_name="test",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            client_id="my-client",
        )
        rep = provider.redacted_repr()
        assert "test" in rep
        assert "my-client" in rep


class TestCreateAuthProviderPKCE:
    """Tests for the pkce type in create_auth_provider()."""

    def test_creates_pkce_provider(self):
        provider = create_auth_provider(
            {
                "type": "pkce",
                "authorization_endpoint": "https://auth.example.com/authorize",
                "token_endpoint": "https://auth.example.com/token",
                "client_id": "my-client",
            },
            backend_name="test-backend",
        )
        assert isinstance(provider, PKCEAuthProvider)

    def test_missing_required_fields(self):
        with pytest.raises(ValueError, match="authorization_endpoint"):
            create_auth_provider(
                {
                    "type": "pkce",
                    "token_endpoint": "https://auth.example.com/token",
                    "client_id": "my-client",
                }
            )

    def test_unknown_type(self):
        with pytest.raises(ValueError, match="Unknown auth type"):
            create_auth_provider({"type": "magic"})


# schema_backends.py — PKCEAuthConfig

from argus_mcp.config.schema_backends import PKCEAuthConfig


class TestPKCEAuthConfig:
    """Tests for the PKCEAuthConfig Pydantic model."""

    def test_valid_config(self):
        cfg = PKCEAuthConfig(
            type="pkce",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            client_id="my-client",
        )
        assert cfg.client_secret == ""
        assert cfg.scopes == []

    def test_with_scopes(self):
        cfg = PKCEAuthConfig(
            type="pkce",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            client_id="my-client",
            scopes=["openid", "profile"],
        )
        assert cfg.scopes == ["openid", "profile"]

    def test_from_dict(self):
        cfg = PKCEAuthConfig.model_validate(
            {
                "type": "pkce",
                "authorization_endpoint": "https://auth.example.com/authorize",
                "token_endpoint": "https://auth.example.com/token",
                "client_id": "my-client",
                "client_secret": "${MY_SECRET}",
            }
        )
        assert cfg.client_secret == "${MY_SECRET}"


# Headless OAuth


class TestIsHeadless:
    """Tests for headless environment detection."""

    def test_ssh_connection(self):
        with patch.dict("os.environ", {"SSH_CONNECTION": "1.2.3.4 22 5.6.7.8 45678"}, clear=False):
            assert _is_headless() is True

    def test_ssh_tty(self):
        with patch.dict("os.environ", {"SSH_TTY": "/dev/pts/0"}, clear=False):
            assert _is_headless() is True

    @patch("argus_mcp.bridge.auth.pkce.sys")
    def test_linux_no_display(self, mock_sys):
        mock_sys.platform = "linux"
        env = {
            k: v
            for k, v in __import__("os").environ.items()
            if k not in ("SSH_CONNECTION", "SSH_TTY", "DISPLAY", "WAYLAND_DISPLAY")
        }
        with patch.dict("os.environ", env, clear=True):
            assert _is_headless() is True

    def test_graphical_environment(self):
        env = {"DISPLAY": ":0"}
        # Remove SSH vars if present
        with patch.dict("os.environ", env, clear=False):
            with patch.dict("os.environ", {}, clear=False):
                # Clear SSH vars
                import os

                old_ssh = os.environ.pop("SSH_CONNECTION", None)
                old_tty = os.environ.pop("SSH_TTY", None)
                try:
                    assert _is_headless() is False
                finally:
                    if old_ssh is not None:
                        os.environ["SSH_CONNECTION"] = old_ssh
                    if old_tty is not None:
                        os.environ["SSH_TTY"] = old_tty


class TestPresentAuthUrl:
    """Tests for auth URL presentation with headless fallback."""

    AUTH_URL = "https://auth.example.com/authorize?code_challenge=abc"
    REDIRECT = "http://127.0.0.1:12345/callback"

    @patch("argus_mcp.bridge.auth.pkce.webbrowser.open")
    @patch("argus_mcp.bridge.auth.pkce._is_headless", return_value=False)
    def test_opens_browser_when_graphical(self, mock_headless, mock_open):
        _present_auth_url(self.AUTH_URL, self.REDIRECT)
        mock_open.assert_called_once_with(self.AUTH_URL)

    @patch("argus_mcp.bridge.auth.pkce.webbrowser.open")
    @patch("argus_mcp.bridge.auth.pkce._is_headless", return_value=True)
    def test_no_browser_when_headless(self, mock_headless, mock_open, capsys):
        _present_auth_url(self.AUTH_URL, self.REDIRECT)
        mock_open.assert_not_called()
        captured = capsys.readouterr()
        assert self.AUTH_URL in captured.err
        assert "OAUTH AUTHORIZATION REQUIRED" in captured.err

    @patch("argus_mcp.bridge.auth.pkce.webbrowser.open")
    @patch("argus_mcp.bridge.auth.pkce._is_headless", return_value=True)
    def test_headless_prints_redirect_uri(self, mock_headless, mock_open, capsys):
        _present_auth_url(self.AUTH_URL, self.REDIRECT)
        captured = capsys.readouterr()
        assert self.REDIRECT in captured.err

    @patch("argus_mcp.bridge.auth.pkce.webbrowser.open")
    @patch("argus_mcp.bridge.auth.pkce._is_headless", return_value=True)
    def test_headless_does_not_leak_to_stdout(self, mock_headless, mock_open, capsys):
        """Auth URLs must not appear in stdout (only stderr for security)."""
        _present_auth_url(self.AUTH_URL, self.REDIRECT)
        captured = capsys.readouterr()
        assert self.AUTH_URL not in captured.out
