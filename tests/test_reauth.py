"""Tests for Interactive Re-Authentication Flow."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request

from argus_mcp.bridge.auth.provider import AuthProvider
from argus_mcp.bridge.auth.refresh_service import AuthRefreshService
from argus_mcp.server.management.schemas import ReAuthResponse
from argus_mcp.tui.events import ReAuthRequired

# ReAuthRequired event ─────────────────────────────────────────────


class TestReAuthRequiredEvent:
    def test_attributes(self):
        ev = ReAuthRequired(backend_name="github", reason="token expired")
        assert ev.backend_name == "github"
        assert ev.reason == "token expired"

    def test_default_reason(self):
        ev = ReAuthRequired(backend_name="gitlab")
        assert ev.reason == ""


# ReAuthCallback type in refresh service ───────────────────────────


class TestReAuthCallbackInRefreshService:
    def test_init_stores_callback(self):
        providers: dict = {}
        cb = MagicMock()
        svc = AuthRefreshService(providers, interval=60.0, on_reauth_required=cb)
        assert svc._on_reauth_required is cb

    def test_init_default_no_callback(self):
        providers: dict = {}
        svc = AuthRefreshService(providers, interval=60.0)
        assert svc._on_reauth_required is None

    @pytest.mark.asyncio
    async def test_sweep_invokes_callback_on_failure(self):
        """When get_headers raises, the callback should be invoked."""
        bad_provider = MagicMock(spec=AuthProvider)
        bad_provider.get_headers = AsyncMock(side_effect=RuntimeError("refresh failed"))
        providers = {"broken": bad_provider}
        cb = MagicMock()
        svc = AuthRefreshService(providers, interval=60.0, on_reauth_required=cb)

        await svc._sweep()

        cb.assert_called_once()
        call_args = cb.call_args[0]
        assert call_args[0] == "broken"
        assert "refresh failed" in call_args[1]

    @pytest.mark.asyncio
    async def test_sweep_callback_error_does_not_propagate(self):
        """If the callback itself raises, _sweep must not crash."""
        bad_provider = MagicMock(spec=AuthProvider)
        bad_provider.get_headers = AsyncMock(side_effect=RuntimeError("fail"))
        providers = {"broken": bad_provider}
        cb = MagicMock(side_effect=Exception("callback boom"))
        svc = AuthRefreshService(providers, interval=60.0, on_reauth_required=cb)

        # Should not raise
        await svc._sweep()

    @pytest.mark.asyncio
    async def test_sweep_no_callback_still_works(self):
        """Without a callback, _sweep handles failures gracefully."""
        bad_provider = MagicMock(spec=AuthProvider)
        bad_provider.get_headers = AsyncMock(side_effect=RuntimeError("fail"))
        providers = {"broken": bad_provider}
        svc = AuthRefreshService(providers, interval=60.0)

        await svc._sweep()


# ReAuthResponse schema ───────────────────────────────────────────


class TestReAuthResponse:
    def test_defaults(self):
        r = ReAuthResponse(name="github")
        assert r.reauth_initiated is False
        assert r.error is None

    def test_success(self):
        r = ReAuthResponse(name="github", reauth_initiated=True)
        assert r.reauth_initiated is True
        assert r.error is None

    def test_failure_with_error(self):
        r = ReAuthResponse(name="github", reauth_initiated=False, error="token expired")
        assert r.reauth_initiated is False
        assert r.error == "token expired"

    def test_serialization_roundtrip(self):
        r = ReAuthResponse(name="x", reauth_initiated=True)
        data = r.model_dump()
        r2 = ReAuthResponse.model_validate(data)
        assert r2 == r


# Management API /reauth/{name} endpoint ──────────────────────────

from argus_mcp.server.management.router import handle_reauth


class TestHandleReauth:
    @staticmethod
    def _mock_request(service):
        req = MagicMock(spec=Request)
        req.app.state.argus_service = service
        return req

    @pytest.mark.asyncio
    async def test_reauth_success(self):
        service = MagicMock()
        service.is_running = True
        service.config_data = {"be1": {}}
        service.reauth_backend = AsyncMock(
            return_value={"name": "be1", "reauth_initiated": True, "error": None}
        )
        req = self._mock_request(service)
        req.path_params = {"name": "be1"}

        resp = await handle_reauth(req)
        assert resp.status_code == 200
        service.reauth_backend.assert_awaited_once_with("be1")

    @pytest.mark.asyncio
    async def test_reauth_empty_name(self):
        service = MagicMock()
        service.is_running = True
        req = self._mock_request(service)
        req.path_params = {"name": ""}

        resp = await handle_reauth(req)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_reauth_name_too_long(self):
        service = MagicMock()
        service.is_running = True
        req = self._mock_request(service)
        req.path_params = {"name": "a" * 300}

        resp = await handle_reauth(req)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_reauth_invalid_name(self):
        service = MagicMock()
        service.is_running = True
        req = self._mock_request(service)
        req.path_params = {"name": "bad name!@#"}

        resp = await handle_reauth(req)
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_reauth_not_running(self):
        service = MagicMock()
        service.is_running = False
        req = self._mock_request(service)
        req.path_params = {"name": "be1"}

        resp = await handle_reauth(req)
        assert resp.status_code == 503

    @pytest.mark.asyncio
    async def test_reauth_not_found(self):
        service = MagicMock()
        service.is_running = True
        service.config_data = {"other": {}}
        req = self._mock_request(service)
        req.path_params = {"name": "missing"}

        resp = await handle_reauth(req)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_reauth_failure_returns_500(self):
        service = MagicMock()
        service.is_running = True
        service.config_data = {"be1": {}}
        service.reauth_backend = AsyncMock(
            return_value={"name": "be1", "reauth_initiated": False, "error": "no PKCE provider"}
        )
        req = self._mock_request(service)
        req.path_params = {"name": "be1"}

        resp = await handle_reauth(req)
        assert resp.status_code == 500


# ArgusService.reauth_backend ─────────────────────────────────────

from argus_mcp.runtime.models import ServiceState


class TestReauthBackend:
    def _make_service(self):
        from argus_mcp.runtime.service import ArgusService

        svc = ArgusService()
        svc._state = ServiceState.RUNNING
        svc._config_data = {"pkce-be": {}, "static-be": {}}
        return svc

    @pytest.mark.asyncio
    async def test_not_running(self):
        from argus_mcp.runtime.service import ArgusService

        svc = ArgusService()
        svc._state = ServiceState.PENDING
        result = await svc.reauth_backend("be1")
        assert result["reauth_initiated"] is False
        assert "pending" in result["error"]

    @pytest.mark.asyncio
    async def test_backend_not_found(self):
        svc = self._make_service()
        result = await svc.reauth_backend("nonexistent")
        assert result["reauth_initiated"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_no_auth_provider(self):
        svc = self._make_service()
        svc._manager._auth_providers = {}
        result = await svc.reauth_backend("pkce-be")
        assert result["reauth_initiated"] is False
        assert "no auth provider" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_provider_no_trigger_reauth(self):
        svc = self._make_service()
        static_provider = MagicMock(spec=[])  # no trigger_reauth
        svc._manager._auth_providers = {"static-be": static_provider}
        result = await svc.reauth_backend("static-be")
        assert result["reauth_initiated"] is False
        assert "does not support" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_success(self):
        svc = self._make_service()
        pkce_provider = MagicMock()
        pkce_provider.trigger_reauth = AsyncMock(return_value="new-token")
        svc._manager._auth_providers = {"pkce-be": pkce_provider}
        svc.emit_event = MagicMock()

        result = await svc.reauth_backend("pkce-be")
        assert result["reauth_initiated"] is True
        assert result["error"] is None
        pkce_provider.trigger_reauth.assert_awaited_once()
        svc.emit_event.assert_called_once()

    @pytest.mark.asyncio
    async def test_trigger_reauth_raises(self):
        svc = self._make_service()
        pkce_provider = MagicMock()
        pkce_provider.trigger_reauth = AsyncMock(side_effect=RuntimeError("browser failed"))
        svc._manager._auth_providers = {"pkce-be": pkce_provider}
        svc.emit_event = MagicMock()

        result = await svc.reauth_backend("pkce-be")
        assert result["reauth_initiated"] is False
        assert "browser failed" in result["error"]


# CLI --auto-reauth flag ──────────────────────────────────────────

from argus_mcp.cli import _build_parser


class TestAutoReauthFlag:
    def test_default_false(self):
        parser = _build_parser()
        args = parser.parse_args(["server"])
        assert args.auto_reauth is False

    def test_set_true(self):
        parser = _build_parser()
        args = parser.parse_args(["server", "--auto-reauth"])
        assert args.auto_reauth is True


# Management auth mutating suffixes ───────────────────────────────

from argus_mcp.server.management.auth import BearerAuthMiddleware


class TestMutatingSuffixes:
    def test_reauth_is_mutating(self):
        assert "/reauth" in BearerAuthMiddleware._MUTATING_SUFFIXES


# TUI ApiClient.post_reauth ───────────────────────────────────────


class TestApiClientPostReauth:
    @pytest.mark.asyncio
    async def test_post_reauth_calls_correct_endpoint(self):
        from argus_mcp.tui.api_client import ApiClient

        client = ApiClient(base_url="http://127.0.0.1:9000")
        mock_http = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "name": "be1",
            "reauth_initiated": True,
            "error": None,
        }
        mock_resp.raise_for_status = MagicMock()
        mock_http.post = AsyncMock(return_value=mock_resp)
        mock_http.is_closed = False
        client._client = mock_http

        result = await client.post_reauth("be1")
        assert result.reauth_initiated is True
        assert result.name == "be1"
        mock_http.post.assert_awaited_once()
        call_args = mock_http.post.call_args
        assert "reauth/be1" in call_args[0][0]


# Auth __init__ exports ───────────────────────────────────────────


class TestAuthExports:
    def test_reauth_callback_exported(self):
        from argus_mcp.bridge.auth import ReAuthCallback

        assert callable(ReAuthCallback) or ReAuthCallback is not None
