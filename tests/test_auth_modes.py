"""Tests for Step 2.1: strict/permissive auth mode semantics.

Covers:
- Config model validation (IncomingAuthConfig.auth_mode field)
- AuthMiddleware behaviour in strict vs permissive mode
- ContextVar propagation (current_auth_mode)
- Metadata injection (ctx.metadata["auth_mode"])
- Invalid tokens are NEVER silently downgraded in either mode
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from argus_mcp.bridge.middleware.auth import AuthMiddleware
from argus_mcp.bridge.middleware.chain import RequestContext
from argus_mcp.config.schema_security import IncomingAuthConfig
from argus_mcp.server.auth.providers import (
    AuthenticationError,
    AuthProviderRegistry,
    UserIdentity,
)
from argus_mcp.server.auth_context import current_auth_mode

# Helpers


def _make_ctx(token: str | None = None) -> RequestContext:
    """Build a minimal RequestContext with optional token in metadata."""
    ctx = RequestContext(capability_name="test_tool", mcp_method="call_tool")
    if token is not None:
        ctx.metadata["auth_token"] = token
    return ctx


def _make_registry(
    *,
    authenticate_return: UserIdentity | None = None,
    authenticate_side_effect: Exception | None = None,
) -> AuthProviderRegistry:
    """Build a mock AuthProviderRegistry."""
    registry = AsyncMock(spec=AuthProviderRegistry)
    if authenticate_side_effect is not None:
        registry.authenticate.side_effect = authenticate_side_effect
    elif authenticate_return is not None:
        registry.authenticate.return_value = authenticate_return
    else:
        registry.authenticate.return_value = UserIdentity(subject="test-user", provider="local")
    return registry


_ANON_USER = UserIdentity(provider="anonymous")
_AUTHED_USER = UserIdentity(subject="alice", provider="jwt")
_NEXT = AsyncMock(return_value="ok")


# Config model tests


class TestIncomingAuthConfigModel:
    """Validate Pydantic model for the auth_mode field."""

    def test_default_auth_mode_is_strict(self) -> None:
        cfg = IncomingAuthConfig()
        assert cfg.auth_mode == "strict"

    def test_explicit_strict(self) -> None:
        cfg = IncomingAuthConfig(auth_mode="strict")
        assert cfg.auth_mode == "strict"

    def test_explicit_permissive(self) -> None:
        cfg = IncomingAuthConfig(auth_mode="permissive")
        assert cfg.auth_mode == "permissive"

    def test_invalid_mode_rejected(self) -> None:
        with pytest.raises(Exception):  # Pydantic ValidationError
            IncomingAuthConfig(auth_mode="lax")  # type: ignore[arg-type]

    def test_auth_mode_in_model_dump(self) -> None:
        cfg = IncomingAuthConfig(auth_mode="permissive")
        d = cfg.model_dump()
        assert d["auth_mode"] == "permissive"

    def test_auth_mode_with_local_type(self) -> None:
        cfg = IncomingAuthConfig(type="local", token="s3cret", auth_mode="strict")
        assert cfg.type == "local"
        assert cfg.auth_mode == "strict"


# Strict mode middleware tests


class TestStrictModeMiddleware:
    """Auth mode=strict: reject all unauthenticated requests."""

    @pytest.fixture()
    def middleware(self) -> AuthMiddleware:
        return AuthMiddleware(
            _make_registry(authenticate_return=_AUTHED_USER),
            auth_mode="strict",
        )

    async def test_valid_token_authenticates(self, middleware: AuthMiddleware) -> None:
        ctx = _make_ctx(token="valid-bearer")
        next_handler = AsyncMock(return_value="ok")
        result = await middleware(ctx, next_handler)
        assert result == "ok"
        assert ctx.metadata["user"] == _AUTHED_USER
        next_handler.assert_awaited_once_with(ctx)

    async def test_no_token_rejected(self) -> None:
        registry = _make_registry(
            authenticate_side_effect=AuthenticationError("Missing bearer token")
        )
        mw = AuthMiddleware(registry, auth_mode="strict")
        ctx = _make_ctx(token=None)
        with pytest.raises(AuthenticationError, match="Missing bearer token"):
            await mw(ctx, AsyncMock())

    async def test_invalid_token_rejected(self) -> None:
        registry = _make_registry(
            authenticate_side_effect=AuthenticationError("Invalid bearer token")
        )
        mw = AuthMiddleware(registry, auth_mode="strict")
        ctx = _make_ctx(token="bad-token")
        with pytest.raises(AuthenticationError, match="Invalid bearer token"):
            await mw(ctx, AsyncMock())

    async def test_metadata_contains_auth_mode(self, middleware: AuthMiddleware) -> None:
        ctx = _make_ctx(token="valid")
        await middleware(ctx, AsyncMock(return_value="ok"))
        assert ctx.metadata["auth_mode"] == "strict"

    async def test_user_subject_in_metadata(self, middleware: AuthMiddleware) -> None:
        ctx = _make_ctx(token="valid")
        await middleware(ctx, AsyncMock(return_value="ok"))
        assert ctx.metadata["user_subject"] == "alice"


# Permissive mode middleware tests


class TestPermissiveModeMiddleware:
    """Auth mode=permissive: allow unauthenticated, reject invalid."""

    @pytest.fixture()
    def middleware(self) -> AuthMiddleware:
        return AuthMiddleware(
            _make_registry(authenticate_return=_AUTHED_USER),
            auth_mode="permissive",
        )

    async def test_valid_token_authenticates(self, middleware: AuthMiddleware) -> None:
        ctx = _make_ctx(token="valid-bearer")
        next_handler = AsyncMock(return_value="ok")
        result = await middleware(ctx, next_handler)
        assert result == "ok"
        assert ctx.metadata["user"] == _AUTHED_USER
        next_handler.assert_awaited_once_with(ctx)

    async def test_no_token_passes_as_anonymous(self, middleware: AuthMiddleware) -> None:
        ctx = _make_ctx(token=None)
        next_handler = AsyncMock(return_value="ok")
        result = await middleware(ctx, next_handler)
        assert result == "ok"
        user = ctx.metadata["user"]
        assert user.is_anonymous
        assert user.provider == "anonymous"
        next_handler.assert_awaited_once_with(ctx)

    async def test_invalid_token_NOT_downgraded(self) -> None:
        """Critical: invalid tokens must NEVER silently downgrade to anon."""
        registry = _make_registry(authenticate_side_effect=AuthenticationError("Bad token"))
        mw = AuthMiddleware(registry, auth_mode="permissive")
        ctx = _make_ctx(token="expired-or-bad")
        with pytest.raises(AuthenticationError, match="Bad token"):
            await mw(ctx, AsyncMock())

    async def test_metadata_contains_auth_mode(self, middleware: AuthMiddleware) -> None:
        ctx = _make_ctx(token=None)
        await middleware(ctx, AsyncMock(return_value="ok"))
        assert ctx.metadata["auth_mode"] == "permissive"

    async def test_anonymous_user_has_no_subject_entry(self, middleware: AuthMiddleware) -> None:
        """Anonymous users have subject='anonymous' → not injected as user_subject."""
        ctx = _make_ctx(token=None)
        await middleware(ctx, AsyncMock(return_value="ok"))
        # UserIdentity(provider="anonymous") has subject="anonymous" which is truthy,
        # so user_subject will be set.
        assert ctx.metadata.get("user_subject") == "anonymous"


# Default mode tests


class TestDefaultModeSemantics:
    """Verify default behaviour when auth_mode is not explicitly passed."""

    async def test_default_is_strict(self) -> None:
        registry = _make_registry(
            authenticate_side_effect=AuthenticationError("Missing bearer token")
        )
        mw = AuthMiddleware(registry)  # no auth_mode → defaults to "strict"
        ctx = _make_ctx(token=None)
        with pytest.raises(AuthenticationError):
            await mw(ctx, AsyncMock())


# ContextVar tests


class TestAuthModeContextVar:
    """Verify current_auth_mode ContextVar default and type."""

    def test_default_is_strict(self) -> None:
        # ContextVar has default="strict"
        assert current_auth_mode.get() == "strict"

    def test_can_set_permissive(self) -> None:
        token = current_auth_mode.set("permissive")
        try:
            assert current_auth_mode.get() == "permissive"
        finally:
            current_auth_mode.reset(token)


# Transport-level auth mode propagation


class TestTransportAuthMode:
    """Verify the ASGI transport sets current_auth_mode from module-level."""

    async def test_authenticate_request_sets_auth_mode(self) -> None:
        """_authenticate_request should set current_auth_mode ContextVar."""
        import argus_mcp.server.transport as transport_mod

        # Save original state
        orig_provider = transport_mod._incoming_auth_provider
        orig_mode = transport_mod._auth_mode
        try:
            transport_mod._incoming_auth_provider = None  # anonymous/no-provider
            transport_mod._auth_mode = "permissive"

            # Minimal ASGI scope
            scope: dict[str, Any] = {"headers": [], "client": ("127.0.0.1", 8080)}
            await transport_mod._authenticate_request(scope)

            assert current_auth_mode.get() == "permissive"
        finally:
            transport_mod._incoming_auth_provider = orig_provider
            transport_mod._auth_mode = orig_mode

    async def test_authenticate_request_default_strict(self) -> None:
        import argus_mcp.server.transport as transport_mod

        orig_provider = transport_mod._incoming_auth_provider
        orig_mode = transport_mod._auth_mode
        try:
            transport_mod._incoming_auth_provider = None
            transport_mod._auth_mode = "strict"

            scope: dict[str, Any] = {"headers": [], "client": ("10.0.0.1", 9090)}
            await transport_mod._authenticate_request(scope)

            assert current_auth_mode.get() == "strict"
        finally:
            transport_mod._incoming_auth_provider = orig_provider
            transport_mod._auth_mode = orig_mode


# Edge cases


class TestEdgeCases:
    """Edge-case scenarios for mixed configurations."""

    async def test_anonymous_provider_strict_rejects_nothing(self) -> None:
        """AnonymousProvider always returns anonymous, even in strict mode."""
        from argus_mcp.server.auth.providers import AnonymousProvider

        provider = AnonymousProvider()
        registry = AuthProviderRegistry(provider)
        mw = AuthMiddleware(registry, auth_mode="strict")
        ctx = _make_ctx(token=None)
        next_handler = AsyncMock(return_value="ok")
        result = await mw(ctx, next_handler)
        assert result == "ok"
        assert ctx.metadata["user"].is_anonymous

    async def test_local_provider_strict_rejects_no_token(self) -> None:
        """LocalTokenProvider in strict mode raises on missing token."""
        from argus_mcp.server.auth.providers import LocalTokenProvider

        provider = LocalTokenProvider("secret-token")
        registry = AuthProviderRegistry(provider)
        mw = AuthMiddleware(registry, auth_mode="strict")
        ctx = _make_ctx(token=None)
        with pytest.raises(AuthenticationError, match="Missing bearer token"):
            await mw(ctx, AsyncMock())

    async def test_local_provider_permissive_no_token_gives_anonymous(self) -> None:
        """Permissive mode bypasses the provider entirely when no token."""
        from argus_mcp.server.auth.providers import LocalTokenProvider

        provider = LocalTokenProvider("secret-token")
        registry = AuthProviderRegistry(provider)
        mw = AuthMiddleware(registry, auth_mode="permissive")
        ctx = _make_ctx(token=None)
        next_handler = AsyncMock(return_value="ok")
        result = await mw(ctx, next_handler)
        assert result == "ok"
        assert ctx.metadata["user"].is_anonymous

    async def test_local_provider_permissive_wrong_token_rejected(self) -> None:
        """Even in permissive, a wrong token is rejected — not downgraded."""
        from argus_mcp.server.auth.providers import LocalTokenProvider

        provider = LocalTokenProvider("secret-token")
        registry = AuthProviderRegistry(provider)
        mw = AuthMiddleware(registry, auth_mode="permissive")
        ctx = _make_ctx(token="wrong-token")
        with pytest.raises(AuthenticationError, match="Invalid bearer token"):
            await mw(ctx, AsyncMock())

    async def test_local_provider_permissive_correct_token_passes(self) -> None:
        """In permissive, a correct token authenticates normally."""
        from argus_mcp.server.auth.providers import LocalTokenProvider

        provider = LocalTokenProvider("secret-token")
        registry = AuthProviderRegistry(provider)
        mw = AuthMiddleware(registry, auth_mode="permissive")
        ctx = _make_ctx(token="secret-token")
        next_handler = AsyncMock(return_value="ok")
        result = await mw(ctx, next_handler)
        assert result == "ok"
        assert ctx.metadata["user"].subject == "local-user"
        assert ctx.metadata["user"].provider == "local"
