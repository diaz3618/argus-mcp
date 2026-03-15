"""Tests for argus_mcp.server.management.schemas — Management API Pydantic models."""

from argus_mcp.server.management.schemas import (
    BackendCapabilities,
    BackendDetail,
    BackendHealth,
    BackendsResponse,
    CapabilitiesResponse,
    ErrorResponse,
    EventItem,
    EventsResponse,
    HealthBackends,
    HealthResponse,
    PromptDetail,
    ReconnectResponse,
    ReloadResponse,
    ResourceDetail,
    SessionDetail,
    SessionsResponse,
    ShutdownResponse,
    StatusConfig,
    StatusResponse,
    StatusService,
    StatusTransport,
    ToolDetail,
)

# HealthResponse ──────────────────────────────────────────────────────


class TestHealthBackends:
    def test_defaults(self):
        hb = HealthBackends()
        assert hb.total == 0
        assert hb.connected == 0
        assert hb.healthy == 0

    def test_values(self):
        hb = HealthBackends(total=5, connected=4, healthy=3)
        assert hb.total == 5
        assert hb.connected == 4
        assert hb.healthy == 3


class TestHealthResponse:
    def test_defaults(self):
        hr = HealthResponse(status="healthy")
        assert hr.status == "healthy"
        assert hr.uptime_seconds is None
        assert hr.version == ""
        assert isinstance(hr.backends, HealthBackends)

    def test_full(self):
        hr = HealthResponse(
            status="degraded",
            uptime_seconds=3600.5,
            version="0.6.2",
            backends=HealthBackends(total=3, connected=2, healthy=2),
        )
        assert hr.uptime_seconds == 3600.5
        assert hr.backends.total == 3

    def test_serialization_roundtrip(self):
        hr = HealthResponse(status="unhealthy", version="1.0")
        d = hr.model_dump()
        assert d["status"] == "unhealthy"
        assert d["backends"]["total"] == 0
        hr2 = HealthResponse.model_validate(d)
        assert hr2 == hr


# StatusResponse ──────────────────────────────────────────────────────


class TestStatusService:
    def test_required_fields(self):
        ss = StatusService(name="argus", version="0.6.2", state="running")
        assert ss.name == "argus"
        assert ss.uptime_seconds is None
        assert ss.started_at is None

    def test_optional_fields(self):
        ss = StatusService(
            name="argus",
            version="0.6.2",
            state="running",
            uptime_seconds=100.0,
            started_at="2024-01-01T00:00:00Z",
        )
        assert ss.uptime_seconds == 100.0
        assert ss.started_at == "2024-01-01T00:00:00Z"


class TestStatusConfig:
    def test_defaults(self):
        sc = StatusConfig()
        assert sc.file_path is None
        assert sc.loaded_at is None
        assert sc.backend_count == 0


class TestStatusTransport:
    def test_defaults(self):
        st = StatusTransport()
        assert st.sse_url == ""
        assert st.streamable_http_url is None
        assert st.host == ""
        assert st.port == 0


class TestStatusResponse:
    def test_minimal(self):
        sr = StatusResponse(
            service=StatusService(name="argus", version="0.6.2", state="running"),
        )
        assert sr.config.backend_count == 0
        assert sr.transport.port == 0
        assert sr.feature_flags == {}


# BackendsResponse ────────────────────────────────────────────────────


class TestBackendDetail:
    def test_defaults(self):
        bd = BackendDetail(name="test", type="stdio")
        assert bd.group == "default"
        assert bd.phase == "pending"
        assert bd.state == "disconnected"
        assert bd.connected_at is None
        assert bd.error is None
        assert bd.capabilities.tools == 0
        assert bd.health.status == "unknown"
        assert bd.conditions == []
        assert bd.labels == {}

    def test_full(self):
        bd = BackendDetail(
            name="github",
            type="sse",
            group="dev",
            phase="ready",
            state="connected",
            connected_at="2024-01-01T00:00:00Z",
            capabilities=BackendCapabilities(tools=10, resources=5, prompts=2),
            health=BackendHealth(status="healthy", latency_ms=12.5),
            labels={"env": "prod"},
        )
        assert bd.capabilities.tools == 10
        assert bd.health.latency_ms == 12.5
        assert bd.labels["env"] == "prod"


class TestBackendsResponse:
    def test_empty(self):
        br = BackendsResponse()
        assert br.backends == []

    def test_with_entries(self):
        br = BackendsResponse(
            backends=[
                BackendDetail(name="a", type="stdio"),
                BackendDetail(name="b", type="sse"),
            ]
        )
        assert len(br.backends) == 2


# CapabilitiesResponse ────────────────────────────────────────────────


class TestToolDetail:
    def test_defaults(self):
        td = ToolDetail(name="search")
        assert td.original_name == ""
        assert td.description == ""
        assert td.backend == ""
        assert td.input_schema == {}
        assert td.filtered is False
        assert td.renamed is False

    def test_renamed(self):
        td = ToolDetail(
            name="github__search",
            original_name="search",
            backend="github",
            renamed=True,
        )
        assert td.renamed is True
        assert td.name != td.original_name


class TestResourceDetail:
    def test_defaults(self):
        rd = ResourceDetail()
        assert rd.uri == ""
        assert rd.name == ""
        assert rd.mime_type is None

    def test_mime(self):
        rd = ResourceDetail(uri="file://x.json", name="x", mime_type="application/json")
        assert rd.mime_type == "application/json"


class TestPromptDetail:
    def test_defaults(self):
        pd = PromptDetail(name="summarize")
        assert pd.description == ""
        assert pd.arguments == []


class TestCapabilitiesResponse:
    def test_empty(self):
        cr = CapabilitiesResponse()
        assert cr.tools == []
        assert cr.resources == []
        assert cr.prompts == []
        assert cr.route_map == {}

    def test_route_map_tuple(self):
        cr = CapabilitiesResponse(
            route_map={"search": ("github", "search"), "read": ("fs", "read_file")}
        )
        assert cr.route_map["search"] == ("github", "search")
        # Roundtrip via JSON serialization (tuples become lists)
        d = cr.model_dump(mode="json")
        assert d["route_map"]["search"] == ["github", "search"]


# EventsResponse ─────────────────────────────────────────────────────


class TestEventItem:
    def test_required(self):
        ei = EventItem(
            id="evt-1",
            timestamp="2024-01-01T00:00:00Z",
            stage="connect",
            message="Connected to backend",
        )
        assert ei.severity == "info"
        assert ei.backend is None
        assert ei.details is None

    def test_full(self):
        ei = EventItem(
            id="evt-2",
            timestamp="2024-01-01T00:00:00Z",
            stage="error",
            message="Timeout",
            severity="error",
            backend="github",
            details={"code": 408},
        )
        assert ei.severity == "error"
        assert ei.details["code"] == 408


class TestEventsResponse:
    def test_empty(self):
        er = EventsResponse()
        assert er.events == []


# Error, Reload, Reconnect, Shutdown ──────────────────────────────────


class TestErrorResponse:
    def test_required_only(self):
        er = ErrorResponse(error="not_found", message="Backend not found")
        assert er.details is None

    def test_with_details(self):
        er = ErrorResponse(error="conflict", message="Duplicate", details={"name": "github"})
        assert er.details["name"] == "github"


class TestReloadResponse:
    def test_defaults(self):
        rr = ReloadResponse()
        assert rr.reloaded is False
        assert rr.backends_added == []
        assert rr.backends_removed == []
        assert rr.backends_changed == []
        assert rr.errors == []

    def test_full(self):
        rr = ReloadResponse(
            reloaded=True,
            backends_added=["new"],
            backends_removed=["old"],
            backends_changed=["updated"],
        )
        assert rr.reloaded is True
        assert "new" in rr.backends_added


class TestReconnectResponse:
    def test_defaults(self):
        rr = ReconnectResponse(name="github")
        assert rr.reconnected is False
        assert rr.error is None

    def test_success(self):
        rr = ReconnectResponse(name="github", reconnected=True)
        assert rr.reconnected is True

    def test_failure(self):
        rr = ReconnectResponse(name="github", error="timeout")
        assert rr.error == "timeout"


class TestShutdownResponse:
    def test_defaults(self):
        sr = ShutdownResponse()
        assert sr.shutting_down is True

    def test_explicit(self):
        sr = ShutdownResponse(shutting_down=False)
        assert sr.shutting_down is False


# SessionsResponse ───────────────────────────────────────────────────


class TestSessionDetail:
    def test_defaults(self):
        sd = SessionDetail(id="abc-123")
        assert sd.transport_type == ""
        assert sd.tool_count == 0
        assert sd.capability_snapshot == {}
        assert sd.age_seconds == 0.0
        assert sd.idle_seconds == 0.0
        assert sd.ttl == 1800.0
        assert sd.expired is False

    def test_expired_session(self):
        sd = SessionDetail(id="abc-123", expired=True)
        assert sd.expired is True


class TestSessionsResponse:
    def test_empty(self):
        sr = SessionsResponse()
        assert sr.active_sessions == 0
        assert sr.sessions == []

    def test_with_sessions(self):
        sr = SessionsResponse(
            active_sessions=2,
            sessions=[
                SessionDetail(id="s1", tool_count=5),
                SessionDetail(id="s2", tool_count=3, expired=True),
            ],
        )
        assert sr.active_sessions == 2
        assert len(sr.sessions) == 2
        assert sr.sessions[1].expired is True
