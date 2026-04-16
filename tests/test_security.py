"""
Covers:
- JWT/OIDC Authentication (jwt, oidc, providers, auth middleware)
- Role-Based Authorization (policies, engine, authz middleware)
- OpenTelemetry (tracing, metrics — no-op paths)
- Encrypted Secret Management (store, providers, resolver)
"""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock

import pytest

# Middleware
from argus_mcp.bridge.middleware.auth import AuthMiddleware
from argus_mcp.bridge.middleware.authz import AuthorizationError, AuthzMiddleware
from argus_mcp.bridge.middleware.chain import RequestContext
from argus_mcp.bridge.middleware.telemetry import TelemetryMiddleware

# Errors
from argus_mcp.errors import ConfigurationError

# Secrets
from argus_mcp.secrets.providers import EnvProvider, FileProvider, create_provider
from argus_mcp.secrets.resolver import (
    SecretResolutionError,
    find_secret_references,
    resolve_secrets,
)
from argus_mcp.secrets.store import SecretStore

# JWT / Auth constructs
from argus_mcp.server.auth.jwt import (
    JWTConfig,
    TokenClaims,
    _norm_aud,
)
from argus_mcp.server.auth.providers import (
    AnonymousProvider,
    AuthenticationError,
    AuthProviderRegistry,
    LocalTokenProvider,
    UserIdentity,
)

# RBAC constructs
from argus_mcp.server.authz.engine import PolicyEngine
from argus_mcp.server.authz.policies import (
    AuthzPolicy,
    PolicyDecision,
    _resource_matches,
    load_policies,
)
from argus_mcp.telemetry.metrics import get_meter, record_request

# Telemetry (no-op paths)
from argus_mcp.telemetry.tracing import get_tracer, start_span

# JWT / OIDC / Auth


class TestTokenClaims:
    def test_frozen(self):
        tc = TokenClaims(sub="u1", iss="iss1", aud="aud1")
        assert tc.sub == "u1"
        with pytest.raises(AttributeError):
            tc.sub = "changed"  # type: ignore[misc]

    def test_defaults(self):
        tc = TokenClaims()
        assert tc.sub == ""
        assert tc.roles == []
        assert tc.raw == {}


class TestNormAud:
    def test_string(self):
        assert _norm_aud("my-aud") == "my-aud"

    def test_list(self):
        assert _norm_aud(["a", "b"]) == "a"

    def test_empty_list(self):
        assert _norm_aud([]) == ""

    def test_none(self):
        assert _norm_aud(None) == ""


class TestJWTConfig:
    def test_defaults(self):
        c = JWTConfig()
        assert c.jwks_uri == ""
        assert c.algorithms == ["RS256", "ES256"]
        assert c.key_ttl == 3600.0


class TestUserIdentity:
    def test_anonymous(self):
        u = UserIdentity()
        assert u.is_anonymous

    def test_not_anonymous(self):
        u = UserIdentity(provider="jwt", subject="u1")
        assert not u.is_anonymous

    def test_frozen(self):
        u = UserIdentity(subject="u1")
        with pytest.raises(AttributeError):
            u.subject = "changed"  # type: ignore[misc]


class TestAnonymousProvider:
    def test_returns_anonymous(self):
        prov = AnonymousProvider()
        user = asyncio.run(prov.authenticate(None))
        assert user.is_anonymous

    def test_ignores_token(self):
        prov = AnonymousProvider()
        user = asyncio.run(prov.authenticate("any-token"))
        assert user.is_anonymous


class TestLocalTokenProvider:
    def test_valid_token(self):
        prov = LocalTokenProvider("secret-123")
        user = asyncio.run(prov.authenticate("secret-123"))
        assert user.subject == "local-user"
        assert user.provider == "local"

    def test_invalid_token(self):
        prov = LocalTokenProvider("secret-123")
        with pytest.raises(AuthenticationError, match="Invalid"):
            asyncio.run(prov.authenticate("wrong"))

    def test_missing_token(self):
        prov = LocalTokenProvider("secret-123")
        with pytest.raises(AuthenticationError, match="Missing"):
            asyncio.run(prov.authenticate(None))


class TestAuthProviderRegistry:
    def test_from_config_none(self):
        with pytest.raises(ConfigurationError, match="Auth provider config is required"):
            AuthProviderRegistry.from_config(None)

    def test_from_config_anonymous(self):
        reg = AuthProviderRegistry.from_config({"type": "anonymous"})
        user = asyncio.run(reg.authenticate(None))
        assert user.is_anonymous

    def test_from_config_local(self):
        reg = AuthProviderRegistry.from_config({"type": "local", "token": "tok"})
        user = asyncio.run(reg.authenticate("tok"))
        assert user.provider == "local"

    def test_from_config_local_missing_token(self):
        with pytest.raises(ConfigurationError, match="token"):
            AuthProviderRegistry.from_config({"type": "local"})

    def test_from_config_jwt(self):
        reg = AuthProviderRegistry.from_config(
            {
                "type": "jwt",
                "jwks_uri": "https://example.com/.well-known/jwks.json",
            }
        )
        assert reg is not None

    def test_from_config_unknown(self):
        with pytest.raises(ConfigurationError, match="Unknown"):
            AuthProviderRegistry.from_config({"type": "magic"})


# Auth Middleware


class TestAuthMiddleware:
    def test_injects_user(self):
        reg = AuthProviderRegistry.from_config({"type": "anonymous"})
        mw = AuthMiddleware(reg)
        ctx = RequestContext(capability_name="test_tool", mcp_method="call_tool")

        handler = AsyncMock(return_value="ok")
        result = asyncio.run(mw(ctx, handler))

        assert result == "ok"
        assert "user" in ctx.metadata
        assert ctx.metadata["user"].is_anonymous
        handler.assert_called_once_with(ctx)

    def test_auth_failure_propagates(self):
        reg = AuthProviderRegistry.from_config({"type": "local", "token": "secret"})
        mw = AuthMiddleware(reg)
        ctx = RequestContext(
            capability_name="test_tool",
            mcp_method="call_tool",
            metadata={"auth_token": "wrong"},
        )
        handler = AsyncMock()

        with pytest.raises(AuthenticationError):
            asyncio.run(mw(ctx, handler))

        handler.assert_not_called()

    def test_local_token_success(self):
        reg = AuthProviderRegistry.from_config({"type": "local", "token": "my-tok"})
        mw = AuthMiddleware(reg)
        ctx = RequestContext(
            capability_name="test_tool",
            mcp_method="call_tool",
            metadata={"auth_token": "my-tok"},
        )
        handler = AsyncMock(return_value="done")
        result = asyncio.run(mw(ctx, handler))

        assert result == "done"
        assert ctx.metadata["user"].provider == "local"
        assert ctx.metadata["user_subject"] == "local-user"


# RBAC — Policies


class TestResourceMatches:
    def test_wildcard(self):
        assert _resource_matches("*", "tool:anything") is True

    def test_exact(self):
        assert _resource_matches("tool:read_file", "tool:read_file") is True

    def test_no_match(self):
        assert _resource_matches("tool:read_file", "tool:write_file") is False

    def test_glob(self):
        assert _resource_matches("tool:read_*", "tool:read_file") is True
        assert _resource_matches("tool:read_*", "tool:write_file") is False


class TestAuthzPolicy:
    def test_from_dict(self):
        p = AuthzPolicy.from_dict(
            {
                "effect": "allow",
                "roles": ["admin"],
                "resources": ["*"],
            }
        )
        assert p.effect == "allow"
        assert p.roles == ["admin"]

    def test_matches_wildcard_role(self):
        p = AuthzPolicy(effect="allow", roles=["*"], resources=["*"])
        assert p.matches(["user"], "tool:anything")

    def test_matches_specific_role(self):
        p = AuthzPolicy(effect="allow", roles=["admin"], resources=["*"])
        assert p.matches(["admin", "user"], "tool:anything")
        assert not p.matches(["user"], "tool:anything")

    def test_matches_resource_pattern(self):
        p = AuthzPolicy(effect="deny", roles=["*"], resources=["tool:dangerous_*"])
        assert p.matches(["user"], "tool:dangerous_delete")
        assert not p.matches(["user"], "tool:safe_read")

    def test_defaults(self):
        p = AuthzPolicy.from_dict({})
        assert p.effect == "deny"
        assert p.roles == ["*"]
        assert p.resources == ["*"]


class TestLoadPolicies:
    def test_valid_policies(self):
        policies = load_policies(
            [
                {"effect": "allow", "roles": ["admin"], "resources": ["*"]},
                {"effect": "deny", "roles": ["*"], "resources": ["tool:delete_*"]},
            ]
        )
        assert len(policies) == 2
        assert policies[0].effect == "allow"

    def test_empty(self):
        assert load_policies([]) == []


# RBAC — Engine


class TestPolicyEngine:
    def test_first_match_allow(self):
        engine = PolicyEngine(
            [
                AuthzPolicy(effect="allow", roles=["admin"], resources=["*"]),
                AuthzPolicy(effect="deny", roles=["*"], resources=["*"]),
            ]
        )
        assert engine.evaluate(["admin"], "tool:x") == PolicyDecision.ALLOW

    def test_first_match_deny(self):
        engine = PolicyEngine(
            [
                AuthzPolicy(effect="deny", roles=["*"], resources=["tool:danger*"]),
                AuthzPolicy(effect="allow", roles=["*"], resources=["*"]),
            ]
        )
        assert engine.evaluate(["user"], "tool:danger_delete") == PolicyDecision.DENY

    def test_default_deny(self):
        engine = PolicyEngine([], default_effect="deny")
        assert engine.evaluate(["user"], "tool:x") == PolicyDecision.DENY

    def test_default_allow(self):
        engine = PolicyEngine([], default_effect="allow")
        assert engine.evaluate(["user"], "tool:x") == PolicyDecision.ALLOW

    def test_filter_allowed(self):
        engine = PolicyEngine(
            [
                AuthzPolicy(effect="deny", roles=["*"], resources=["tool:secret"]),
                AuthzPolicy(effect="allow", roles=["*"], resources=["*"]),
            ]
        )
        result = engine.filter_allowed(["user"], ["tool:read", "tool:secret", "tool:write"])
        assert result == ["tool:read", "tool:write"]

    def test_reload(self):
        engine = PolicyEngine([])
        assert engine.evaluate(["admin"], "tool:x") == PolicyDecision.DENY
        engine.reload([{"effect": "allow", "roles": ["*"], "resources": ["*"]}])
        assert engine.evaluate(["admin"], "tool:x") == PolicyDecision.ALLOW

    def test_from_config(self):
        engine = PolicyEngine.from_config(
            {
                "policies": [{"effect": "allow", "roles": ["admin"], "resources": ["*"]}],
                "default_effect": "deny",
            }
        )
        assert engine.evaluate(["admin"], "tool:x") == PolicyDecision.ALLOW
        assert engine.evaluate(["user"], "tool:x") == PolicyDecision.DENY


# AuthZ Middleware


class TestAuthzMiddleware:
    def test_allow(self):
        engine = PolicyEngine(
            [
                AuthzPolicy(effect="allow", roles=["*"], resources=["*"]),
            ]
        )
        mw = AuthzMiddleware(engine)
        ctx = RequestContext(
            capability_name="test_tool",
            mcp_method="call_tool",
            metadata={"user": UserIdentity(roles=["user"])},
        )
        handler = AsyncMock(return_value="ok")
        result = asyncio.run(mw(ctx, handler))
        assert result == "ok"

    def test_deny(self):
        engine = PolicyEngine(
            [
                AuthzPolicy(effect="deny", roles=["*"], resources=["*"]),
            ]
        )
        mw = AuthzMiddleware(engine)
        ctx = RequestContext(
            capability_name="test_tool",
            mcp_method="call_tool",
            metadata={"user": UserIdentity(roles=["user"])},
        )
        handler = AsyncMock()

        with pytest.raises(AuthorizationError, match="Access denied"):
            asyncio.run(mw(ctx, handler))

        handler.assert_not_called()

    def test_no_user_uses_empty_roles(self):
        engine = PolicyEngine([], default_effect="allow")
        mw = AuthzMiddleware(engine)
        ctx = RequestContext(
            capability_name="test_tool",
            mcp_method="call_tool",
        )
        handler = AsyncMock(return_value="ok")
        result = asyncio.run(mw(ctx, handler))
        assert result == "ok"


# Telemetry (no-op paths)


class TestTracingNoOp:
    def test_get_tracer(self):
        tracer = get_tracer()
        assert tracer is not None

    def test_start_span(self):
        with start_span("test-span", attributes={"key": "val"}) as span:
            span.set_attribute("x", 1)
            span.set_status("ok")
        # Should not raise

    def test_span_record_exception(self):
        with start_span("test-span") as span:
            span.record_exception(ValueError("test"))
            span.end()


class TestMetricsNoOp:
    def test_get_meter(self):
        meter = get_meter()
        assert meter is not None

    def test_record_request(self):
        # Should not raise even without OTel
        record_request(
            tool_name="test",
            backend="test-backend",
            duration_ms=42.0,
            success=True,
        )

    def test_record_request_failure(self):
        record_request(
            tool_name="test",
            backend="test-backend",
            duration_ms=10.0,
            success=False,
        )


class TestTelemetryMiddleware:
    def test_passes_through(self):
        mw = TelemetryMiddleware()
        ctx = RequestContext(
            capability_name="test_tool",
            mcp_method="call_tool",
        )
        ctx.server_name = "backend1"

        handler = AsyncMock(return_value="result")
        result = asyncio.run(mw(ctx, handler))
        assert result == "result"
        handler.assert_called_once_with(ctx)

    def test_records_on_error(self):
        mw = TelemetryMiddleware()
        ctx = RequestContext(
            capability_name="test_tool",
            mcp_method="call_tool",
        )
        handler = AsyncMock(side_effect=RuntimeError("boom"))

        with pytest.raises(RuntimeError, match="boom"):
            asyncio.run(mw(ctx, handler))


# Secrets — Providers


class TestEnvProvider:
    def test_get_set(self, monkeypatch):
        prov = EnvProvider()
        monkeypatch.setenv("SECRET_MY_KEY", "val123")
        assert prov.get("my-key") == "val123"

    def test_get_missing(self, monkeypatch):
        prov = EnvProvider()
        monkeypatch.delenv("SECRET_MISSING_KEY", raising=False)
        assert prov.get("missing-key") is None

    def test_set_and_list(self, monkeypatch):
        prov = EnvProvider()
        for k in list(os.environ):
            if k.startswith("SECRET_"):
                monkeypatch.delenv(k)

        prov.set("test-key", "value")
        assert os.environ["SECRET_TEST_KEY"] == "value"
        assert "test-key" in prov.list_names()

    def test_delete(self, monkeypatch):
        prov = EnvProvider()
        monkeypatch.setenv("SECRET_DEL_KEY", "val")
        prov.delete("del-key")
        assert "SECRET_DEL_KEY" not in os.environ


class TestFileProvider:
    def test_roundtrip(self, tmp_path, monkeypatch):
        """Set a secret and retrieve it (requires cryptography)."""
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            pytest.skip("cryptography not installed")

        key = Fernet.generate_key().decode()
        monkeypatch.setenv("ARGUS_SECRET_KEY", key)

        path = str(tmp_path / "secrets.enc")
        prov = FileProvider(path=path)
        prov.set("api-key", "sk-12345")
        assert prov.get("api-key") == "sk-12345"
        assert "api-key" in prov.list_names()

    def test_delete(self, tmp_path, monkeypatch):
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            pytest.skip("cryptography not installed")

        key = Fernet.generate_key().decode()
        monkeypatch.setenv("ARGUS_SECRET_KEY", key)

        path = str(tmp_path / "secrets.enc")
        prov = FileProvider(path=path)
        prov.set("to-delete", "val")
        prov.delete("to-delete")
        assert prov.get("to-delete") is None

    def test_missing_key_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ARGUS_SECRET_KEY", raising=False)
        prov = FileProvider(path=str(tmp_path / "test.enc"))
        with pytest.raises(RuntimeError, match="ARGUS_SECRET_KEY"):
            prov.set("anything", "val")

    def test_missing_file_returns_empty(self, tmp_path, monkeypatch):
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            pytest.skip("cryptography not installed")

        key = Fernet.generate_key().decode()
        monkeypatch.setenv("ARGUS_SECRET_KEY", key)
        prov = FileProvider(path=str(tmp_path / "nonexistent.enc"))
        assert prov.get("anything") is None
        assert prov.list_names() == []


class TestCreateProvider:
    def test_env(self):
        p = create_provider("env")
        assert isinstance(p, EnvProvider)

    def test_file(self):
        p = create_provider("file", path="/tmp/test.enc")
        assert isinstance(p, FileProvider)

    def test_unknown(self):
        with pytest.raises(ValueError, match="Unknown"):
            create_provider("magic")


# Secrets — Store


class TestSecretStore:
    def test_env_store(self, monkeypatch):
        store = SecretStore(provider_type="env")
        monkeypatch.setenv("SECRET_MY_API", "key123")
        assert store.get("my-api") == "key123"
        assert store.exists("my-api")
        assert not store.exists("missing")

    def test_from_config(self):
        store = SecretStore.from_config({"provider": "env"})
        assert store.provider_type == "env"

    def test_from_config_defaults(self):
        store = SecretStore.from_config({})
        assert store.provider_type == "env"

    def test_set_delete(self, monkeypatch):
        # Clear
        for k in list(os.environ):
            if k.startswith("SECRET_"):
                monkeypatch.delenv(k)

        store = SecretStore(provider_type="env")
        store.set("test-item", "val")
        assert store.get("test-item") == "val"
        store.delete("test-item")
        assert store.get("test-item") is None


# Secrets — Resolver


class TestResolveSecrets:
    def test_no_secrets(self, monkeypatch):
        store = SecretStore(provider_type="env")
        config = {"key": "plain-value", "nested": {"a": 1}}
        result = resolve_secrets(config, store)
        assert result == config

    def test_resolves_secret(self, monkeypatch):
        monkeypatch.setenv("SECRET_MY_KEY", "resolved-val")
        store = SecretStore(provider_type="env")
        config = {"token": "secret:my-key"}
        result = resolve_secrets(config, store)
        assert result["token"] == "resolved-val"

    def test_nested_resolution(self, monkeypatch):
        monkeypatch.setenv("SECRET_DB_PASS", "p@ss")
        store = SecretStore(provider_type="env")
        config = {"db": {"password": "secret:db-pass", "host": "localhost"}}
        result = resolve_secrets(config, store)
        assert result["db"]["password"] == "p@ss"
        assert result["db"]["host"] == "localhost"

    def test_list_resolution(self, monkeypatch):
        monkeypatch.setenv("SECRET_TOK", "t1")
        store = SecretStore(provider_type="env")
        config = {"tokens": ["secret:tok", "plain"]}
        result = resolve_secrets(config, store)
        assert result["tokens"] == ["t1", "plain"]

    def test_missing_secret_warning(self, monkeypatch):
        monkeypatch.delenv("SECRET_MISSING", raising=False)
        store = SecretStore(provider_type="env")
        config = {"token": "secret:missing"}
        result = resolve_secrets(config, store, strict=False)
        # Should leave unresolved
        assert result["token"] == "secret:missing"

    def test_missing_secret_strict(self, monkeypatch):
        monkeypatch.delenv("SECRET_MISSING", raising=False)
        store = SecretStore(provider_type="env")
        config = {"token": "secret:missing"}
        with pytest.raises(SecretResolutionError, match="missing"):
            resolve_secrets(config, store, strict=True)

    def test_does_not_mutate_original(self, monkeypatch):
        monkeypatch.setenv("SECRET_X", "resolved")
        store = SecretStore(provider_type="env")
        config = {"a": "secret:x"}
        result = resolve_secrets(config, store)
        assert config["a"] == "secret:x"
        assert result["a"] == "resolved"


class TestFindSecretReferences:
    def test_finds_refs(self):
        config = {
            "token": "secret:api-key",
            "nested": {"pass": "secret:db-pass"},
            "plain": "no-secret-here",
            "list": ["secret:tok", "other"],
        }
        refs = find_secret_references(config)
        assert set(refs) == {"api-key", "db-pass", "tok"}

    def test_empty_config(self):
        assert find_secret_references({}) == []
