"""Tests for argus_mcp.config.schema* — configuration Pydantic models.

Covers:
- ArgusConfig (defaults, backend name validator)
- ServerSettings (transport normalizer, port range)
- BackendConfig discriminated union (stdio/sse/streamable-http)
- URL validators for SSE and streamable-http
- StdioBackendConfig command stripping
- SseBackendConfig command validation
- IncomingAuthConfig (types, default algorithms)
- AuthorizationConfig (defaults, policies)
- TimeoutConfig (defaults, constraints)
- ManagementSettings (defaults)
- AuditConfig, OptimizerConfig, TelemetrySettings, SecretsConfig
- AuthConfig discriminated union (static/oauth2)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from argus_mcp.config.schema import (
    ArgusConfig,
    AuditConfig,
    ConflictResolutionConfig,
    OptimizerConfig,
    SecretsConfig,
    TelemetrySettings,
)
from argus_mcp.config.schema_backends import (
    CapabilityFilterConfig,
    FiltersConfig,
    OAuth2AuthConfig,
    SseBackendConfig,
    StaticAuthConfig,
    StdioBackendConfig,
    StreamableHttpBackendConfig,
    TimeoutConfig,
    ToolOverrideEntry,
)
from argus_mcp.config.schema_security import AuthorizationConfig, IncomingAuthConfig
from argus_mcp.config.schema_server import ManagementSettings, ServerSettings

# ArgusConfig


class TestArgusConfig:
    def test_defaults(self):
        cfg = ArgusConfig()
        assert cfg.version == "1"
        assert cfg.server.host == "127.0.0.1"
        assert cfg.server.port == 9000
        assert cfg.backends == {}
        assert cfg.audit.enabled is True
        assert cfg.incoming_auth.type == "anonymous"

    def test_minimal_backend(self):
        cfg = ArgusConfig(backends={"srv": {"type": "stdio", "command": "python"}})
        assert "srv" in cfg.backends
        assert cfg.backends["srv"].type == "stdio"

    def test_backend_name_empty_rejected(self):
        with pytest.raises(ValidationError, match="non-empty"):
            ArgusConfig(backends={"": {"type": "stdio", "command": "x"}})

    def test_backend_name_whitespace_rejected(self):
        with pytest.raises(ValidationError, match="whitespace"):
            ArgusConfig(backends={" srv ": {"type": "stdio", "command": "x"}})

    def test_backend_name_valid(self):
        cfg = ArgusConfig(backends={"my-server": {"type": "stdio", "command": "x"}})
        assert "my-server" in cfg.backends

    def test_feature_flags(self):
        cfg = ArgusConfig(feature_flags={"beta_tools": True})
        assert cfg.feature_flags["beta_tools"] is True

    def test_skills_config_defaults(self):
        """ArgusConfig.skills should default to SkillsConfig(directory='skills', enabled=True)."""
        cfg = ArgusConfig()
        assert cfg.skills.directory == "skills"
        assert cfg.skills.enabled is True

    def test_skills_config_custom(self):
        """ArgusConfig should accept skills: {directory: 'examples/skills'} from YAML."""
        cfg = ArgusConfig(skills={"directory": "examples/skills", "enabled": False})
        assert cfg.skills.directory == "examples/skills"
        assert cfg.skills.enabled is False

    def test_workflows_config_defaults(self):
        """ArgusConfig.workflows should default to WorkflowsConfig(directory='workflows', enabled=True)."""
        cfg = ArgusConfig()
        assert cfg.workflows.directory == "workflows"
        assert cfg.workflows.enabled is True

    def test_workflows_config_custom(self):
        """ArgusConfig should accept workflows: {directory: 'examples/workflows'} from YAML."""
        cfg = ArgusConfig(workflows={"directory": "examples/workflows", "enabled": False})
        assert cfg.workflows.directory == "examples/workflows"
        assert cfg.workflows.enabled is False


# ServerSettings


class TestServerSettings:
    def test_defaults(self):
        s = ServerSettings()
        assert s.host == "127.0.0.1"
        assert s.port == 9000
        assert s.transport == "streamable-http"

    def test_transport_http_shorthand(self):
        s = ServerSettings(transport="http")
        assert s.transport == "streamable-http"

    def test_transport_http_case_insensitive(self):
        s = ServerSettings(transport="HTTP")
        assert s.transport == "streamable-http"

    def test_transport_sse(self):
        s = ServerSettings(transport="sse")
        assert s.transport == "sse"

    def test_port_min(self):
        s = ServerSettings(port=1)
        assert s.port == 1

    def test_port_max(self):
        s = ServerSettings(port=65535)
        assert s.port == 65535

    def test_port_zero_rejected(self):
        with pytest.raises(ValidationError):
            ServerSettings(port=0)

    def test_port_over_max_rejected(self):
        with pytest.raises(ValidationError):
            ServerSettings(port=70000)

    def test_management_defaults(self):
        s = ServerSettings()
        assert s.management.enabled is True
        assert s.management.token is None


# ManagementSettings


class TestManagementSettings:
    def test_defaults(self):
        m = ManagementSettings()
        assert m.enabled is True
        assert m.token is None

    def test_explicit(self):
        m = ManagementSettings(enabled=False, token="secret123")
        assert m.enabled is False
        assert m.token == "secret123"


# StdioBackendConfig


class TestStdioBackendConfig:
    def test_minimal(self):
        cfg = StdioBackendConfig(type="stdio", command="python")
        assert cfg.command == "python"
        assert cfg.args == []
        assert cfg.env is None
        assert cfg.group == "default"

    def test_command_stripped(self):
        cfg = StdioBackendConfig(type="stdio", command="  python  ")
        assert cfg.command == "python"

    def test_command_empty_rejected(self):
        with pytest.raises(ValidationError):
            StdioBackendConfig(type="stdio", command="")

    def test_full_config(self):
        cfg = StdioBackendConfig(
            type="stdio",
            command="python",
            args=["-m", "my_server"],
            env={"KEY": "val"},
            group="gpu-servers",
        )
        assert cfg.args == ["-m", "my_server"]
        assert cfg.env == {"KEY": "val"}
        assert cfg.group == "gpu-servers"


# SseBackendConfig


class TestSseBackendConfig:
    def test_minimal(self):
        cfg = SseBackendConfig(type="sse", url="http://localhost:8080/sse")
        assert cfg.url == "http://localhost:8080/sse"
        assert cfg.command is None

    def test_url_must_be_http(self):
        with pytest.raises(ValidationError, match="http://"):
            SseBackendConfig(type="sse", url="ftp://server/sse")

    def test_url_https_accepted(self):
        cfg = SseBackendConfig(type="sse", url="https://server/sse")
        assert cfg.url.startswith("https://")

    def test_url_stripped(self):
        cfg = SseBackendConfig(type="sse", url="  http://x  ")
        assert cfg.url == "http://x"

    def test_command_empty_string_rejected(self):
        with pytest.raises(ValidationError, match="non-empty"):
            SseBackendConfig(type="sse", url="http://x", command="   ")

    def test_command_none_ok(self):
        cfg = SseBackendConfig(type="sse", url="http://x", command=None)
        assert cfg.command is None

    def test_with_auth_static(self):
        cfg = SseBackendConfig(
            type="sse",
            url="http://x",
            auth={"type": "static", "headers": {"Authorization": "Bearer tok"}},
        )
        assert cfg.auth.type == "static"

    def test_with_headers(self):
        cfg = SseBackendConfig(type="sse", url="http://x", headers={"X-Custom": "val"})
        assert cfg.headers["X-Custom"] == "val"


# StreamableHttpBackendConfig


class TestStreamableHttpBackendConfig:
    def test_minimal(self):
        cfg = StreamableHttpBackendConfig(type="streamable-http", url="http://localhost:9000/mcp")
        assert cfg.url == "http://localhost:9000/mcp"

    def test_url_must_be_http(self):
        with pytest.raises(ValidationError, match="http://"):
            StreamableHttpBackendConfig(type="streamable-http", url="ws://server")

    def test_https_accepted(self):
        cfg = StreamableHttpBackendConfig(type="streamable-http", url="https://server/mcp")
        assert cfg.url.startswith("https://")

    def test_with_auth_oauth2(self):
        cfg = StreamableHttpBackendConfig(
            type="streamable-http",
            url="http://x",
            auth={
                "type": "oauth2",
                "token_url": "http://auth/token",
                "client_id": "cid",
                "client_secret": "csecret",
            },
        )
        assert cfg.auth.type == "oauth2"


# TimeoutConfig


class TestTimeoutConfig:
    def test_defaults(self):
        t = TimeoutConfig()
        assert t.init is None
        assert t.cap_fetch is None
        assert t.retries is None

    def test_explicit(self):
        t = TimeoutConfig(init=5.0, retries=3, retry_delay=2.0)
        assert t.init == 5.0
        assert t.retries == 3
        assert t.retry_delay == 2.0

    def test_negative_rejected(self):
        with pytest.raises(ValidationError):
            TimeoutConfig(init=-1)

    def test_retries_max(self):
        t = TimeoutConfig(retries=10)
        assert t.retries == 10

    def test_retries_over_max_rejected(self):
        with pytest.raises(ValidationError):
            TimeoutConfig(retries=11)


# Filter / Override models


class TestFiltersConfig:
    def test_defaults(self):
        f = FiltersConfig()
        assert f.tools.allow == []
        assert f.tools.deny == []

    def test_explicit(self):
        f = FiltersConfig(tools=CapabilityFilterConfig(allow=["my_*"], deny=["secret_*"]))
        assert f.tools.allow == ["my_*"]
        assert f.tools.deny == ["secret_*"]


class TestToolOverrideEntry:
    def test_defaults(self):
        o = ToolOverrideEntry()
        assert o.name is None
        assert o.description is None

    def test_explicit(self):
        o = ToolOverrideEntry(name="new_name", description="New desc")
        assert o.name == "new_name"


# Auth configs


class TestStaticAuthConfig:
    def test_minimal(self):
        c = StaticAuthConfig(type="static", headers={"Authorization": "Bearer t"})
        assert c.headers["Authorization"] == "Bearer t"

    def test_empty_headers_rejected(self):
        with pytest.raises(ValidationError):
            StaticAuthConfig(type="static", headers={})


class TestOAuth2AuthConfig:
    def test_minimal(self):
        c = OAuth2AuthConfig(
            type="oauth2",
            token_url="http://auth/token",
            client_id="cid",
            client_secret="csec",
        )
        assert c.scopes == []

    def test_with_scopes(self):
        c = OAuth2AuthConfig(
            type="oauth2",
            token_url="http://auth/token",
            client_id="cid",
            client_secret="csec",
            scopes=["read", "write"],
        )
        assert "read" in c.scopes


# Security configs


class TestIncomingAuthConfig:
    def test_defaults(self):
        c = IncomingAuthConfig()
        assert c.type == "anonymous"
        assert c.algorithms == ["RS256", "ES256"]
        assert c.token is None

    def test_local_type(self):
        c = IncomingAuthConfig(type="local", token="mytoken")
        assert c.token == "mytoken"

    def test_jwt_type(self):
        c = IncomingAuthConfig(type="jwt", jwks_uri="https://x/.well-known/jwks.json")
        assert c.jwks_uri is not None

    def test_invalid_type(self):
        with pytest.raises(ValidationError):
            IncomingAuthConfig(type="kerberos")


class TestAuthorizationConfig:
    def test_defaults(self):
        c = AuthorizationConfig()
        assert c.enabled is False
        assert c.default_effect == "deny"
        assert c.policies == []

    def test_enabled_with_policies(self):
        c = AuthorizationConfig(
            enabled=True,
            policies=[{"effect": "allow", "roles": ["admin"], "resources": ["*"]}],
        )
        assert len(c.policies) == 1


# Other sub-models


class TestAuditConfig:
    def test_defaults(self):
        c = AuditConfig()
        assert c.enabled is True
        assert c.max_size_mb == 100
        assert c.backup_count == 5

    def test_min_size(self):
        with pytest.raises(ValidationError):
            AuditConfig(max_size_mb=0)


class TestOptimizerConfig:
    def test_defaults(self):
        c = OptimizerConfig()
        assert c.enabled is False
        assert c.keep_tools == []


class TestTelemetrySettings:
    def test_defaults(self):
        c = TelemetrySettings()
        assert c.enabled is False
        assert c.service_name == "argus-mcp"


class TestSecretsConfig:
    def test_defaults(self):
        c = SecretsConfig()
        assert c.enabled is False
        assert c.provider == "env"
        assert c.strict is False


class TestConflictResolutionConfig:
    def test_defaults(self):
        c = ConflictResolutionConfig()
        assert c.strategy == "first-wins"
        assert c.separator == "_"
        assert c.order == []

    def test_prefix_strategy(self):
        c = ConflictResolutionConfig(strategy="prefix", separator=".")
        assert c.strategy == "prefix"
        assert c.separator == "."
