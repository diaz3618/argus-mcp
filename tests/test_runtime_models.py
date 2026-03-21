"""Tests for argus_mcp.runtime.models — service/backend lifecycle models.

Covers:
- ServiceState enum values and valid transitions
- BackendPhase enum values and valid transitions
- BackendInfo model
- BackendCondition timestamping
- BackendStatusRecord: transition(), add_condition(), is_operational, recent_conditions
- CapabilityInfo defaults
- ServiceStatus defaults and compute_uptime()
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from argus_mcp.runtime.models import (
    _BACKEND_TRANSITIONS,
    _VALID_TRANSITIONS,
    BackendCondition,
    BackendInfo,
    BackendPhase,
    BackendStatusRecord,
    CapabilityInfo,
    ServiceState,
    ServiceStatus,
    is_valid_backend_transition,
    is_valid_transition,
)

# ServiceState


class TestServiceState:
    """ServiceState enum and transition validation."""

    def test_all_values(self):
        expected = {"pending", "starting", "running", "stopping", "stopped", "error"}
        assert {s.value for s in ServiceState} == expected

    def test_string_representation(self):
        assert ServiceState.RUNNING == "running"
        assert ServiceState.ERROR == "error"

    @pytest.mark.parametrize(
        "current,target,expected",
        [
            (ServiceState.PENDING, ServiceState.STARTING, True),
            (ServiceState.STARTING, ServiceState.RUNNING, True),
            (ServiceState.STARTING, ServiceState.ERROR, True),
            (ServiceState.RUNNING, ServiceState.STOPPING, True),
            (ServiceState.STOPPING, ServiceState.STOPPED, True),
            (ServiceState.STOPPING, ServiceState.ERROR, True),
            (ServiceState.ERROR, ServiceState.STARTING, True),
            # Invalid transitions
            (ServiceState.PENDING, ServiceState.RUNNING, False),
            (ServiceState.RUNNING, ServiceState.PENDING, False),
            (ServiceState.STOPPED, ServiceState.RUNNING, False),
            (ServiceState.STOPPED, ServiceState.STARTING, False),
            (ServiceState.RUNNING, ServiceState.ERROR, False),
            (ServiceState.PENDING, ServiceState.ERROR, False),
        ],
    )
    def test_transitions(self, current, target, expected):
        assert is_valid_transition(current, target) is expected

    def test_stopped_is_terminal(self):
        """STOPPED has no valid outgoing transitions."""
        for state in ServiceState:
            assert is_valid_transition(ServiceState.STOPPED, state) is False

    def test_all_states_have_transition_entry(self):
        """Every state appears in the transitions dict."""
        for state in ServiceState:
            assert state in _VALID_TRANSITIONS


# BackendPhase


class TestBackendPhase:
    """BackendPhase enum and transition validation."""

    def test_all_values(self):
        expected = {
            "pending",
            "initializing",
            "retrying",
            "ready",
            "degraded",
            "failed",
            "shutting_down",
        }
        assert {p.value for p in BackendPhase} == expected

    @pytest.mark.parametrize(
        "current,target,expected",
        [
            # Valid
            (BackendPhase.PENDING, BackendPhase.INITIALIZING, True),
            (BackendPhase.INITIALIZING, BackendPhase.READY, True),
            (BackendPhase.INITIALIZING, BackendPhase.FAILED, True),
            (BackendPhase.RETRYING, BackendPhase.INITIALIZING, True),
            (BackendPhase.RETRYING, BackendPhase.FAILED, True),
            (BackendPhase.READY, BackendPhase.DEGRADED, True),
            (BackendPhase.READY, BackendPhase.FAILED, True),
            (BackendPhase.READY, BackendPhase.SHUTTING_DOWN, True),
            (BackendPhase.DEGRADED, BackendPhase.READY, True),
            (BackendPhase.DEGRADED, BackendPhase.FAILED, True),
            (BackendPhase.DEGRADED, BackendPhase.SHUTTING_DOWN, True),
            (BackendPhase.FAILED, BackendPhase.INITIALIZING, True),
            (BackendPhase.FAILED, BackendPhase.RETRYING, True),
            (BackendPhase.FAILED, BackendPhase.SHUTTING_DOWN, True),
            # Invalid
            (BackendPhase.PENDING, BackendPhase.READY, False),
            (BackendPhase.SHUTTING_DOWN, BackendPhase.READY, False),
            (BackendPhase.SHUTTING_DOWN, BackendPhase.PENDING, False),
            (BackendPhase.READY, BackendPhase.INITIALIZING, False),
        ],
    )
    def test_transitions(self, current, target, expected):
        assert is_valid_backend_transition(current, target) is expected

    def test_shutting_down_is_terminal(self):
        for phase in BackendPhase:
            assert is_valid_backend_transition(BackendPhase.SHUTTING_DOWN, phase) is False

    def test_all_phases_have_transition_entry(self):
        for phase in BackendPhase:
            assert phase in _BACKEND_TRANSITIONS


# BackendInfo


class TestBackendInfo:
    def test_defaults(self):
        info = BackendInfo(name="srv", type="stdio")
        assert info.name == "srv"
        assert info.type == "stdio"
        assert info.connected is False
        assert info.error is None

    def test_with_error(self):
        info = BackendInfo(name="srv", type="sse", connected=False, error="timeout")
        assert info.error == "timeout"

    def test_json_schema_extra(self):
        schema = BackendInfo.model_json_schema()
        assert "examples" in schema

    def test_serialization(self):
        info = BackendInfo(name="test", type="stdio", connected=True)
        d = info.model_dump()
        assert d["name"] == "test"
        assert d["connected"] is True
        round_trip = BackendInfo.model_validate(d)
        assert round_trip == info


# BackendCondition


class TestBackendCondition:
    def test_default_timestamp(self):
        cond = BackendCondition(type="test", status="OK")
        assert isinstance(cond.timestamp, datetime)
        # Should be recent
        assert (datetime.now(timezone.utc) - cond.timestamp).total_seconds() < 5

    def test_with_message(self):
        cond = BackendCondition(type="Error", status="Error", message="connection refused")
        assert cond.message == "connection refused"

    def test_serialization(self):
        cond = BackendCondition(type="check", status="OK", message="good")
        d = cond.model_dump(mode="json")
        assert "timestamp" in d
        assert d["type"] == "check"


# BackendStatusRecord


class TestBackendStatusRecord:
    def test_defaults(self):
        rec = BackendStatusRecord(name="backend-1")
        assert rec.phase == BackendPhase.PENDING
        assert rec.tool_count == 0
        assert rec.resource_count == 0
        assert rec.prompt_count == 0
        assert rec.error is None
        assert rec.conditions == []

    def test_valid_transition_pending_to_init(self):
        rec = BackendStatusRecord(name="b")
        rec.transition(BackendPhase.INITIALIZING, "starting up")
        assert rec.phase == BackendPhase.INITIALIZING
        assert len(rec.conditions) == 1
        assert rec.conditions[0].status == "Warning"  # INITIALIZING → Warning
        assert rec.conditions[0].message == "starting up"

    def test_transition_to_ready_clears_error(self):
        rec = BackendStatusRecord(name="b")
        rec.transition(BackendPhase.INITIALIZING)
        rec.transition(BackendPhase.FAILED, "oops")
        assert rec.error == "oops"
        rec.transition(BackendPhase.INITIALIZING)
        rec.transition(BackendPhase.READY, "ok now")
        assert rec.error is None
        assert rec.phase == BackendPhase.READY
        assert rec.conditions[-1].status == "OK"

    def test_transition_to_failed_sets_error(self):
        rec = BackendStatusRecord(name="b")
        rec.transition(BackendPhase.INITIALIZING)
        rec.transition(BackendPhase.FAILED, "connection refused")
        assert rec.error == "connection refused"
        assert rec.conditions[-1].status == "Error"

    def test_invalid_transition_raises(self):
        rec = BackendStatusRecord(name="b")
        with pytest.raises(ValueError, match="Invalid backend transition"):
            rec.transition(BackendPhase.READY)  # PENDING → READY is invalid

    def test_add_condition_no_phase_change(self):
        rec = BackendStatusRecord(name="b")
        rec.add_condition("HealthCheck", "OK", "healthy")
        assert rec.phase == BackendPhase.PENDING  # unchanged
        assert len(rec.conditions) == 1
        assert rec.conditions[0].type == "HealthCheck"

    def test_is_operational(self):
        rec = BackendStatusRecord(name="b")
        assert rec.is_operational is False  # PENDING

        rec.transition(BackendPhase.INITIALIZING)
        assert rec.is_operational is False

        rec.transition(BackendPhase.READY)
        assert rec.is_operational is True

        rec.transition(BackendPhase.DEGRADED)
        assert rec.is_operational is True

        rec.transition(BackendPhase.FAILED)
        assert rec.is_operational is False

    def test_recent_conditions_limit(self):
        rec = BackendStatusRecord(name="b")
        for i in range(15):
            rec.add_condition(f"type-{i}", "OK", f"msg-{i}")
        recent = rec.recent_conditions
        assert len(recent) == 10
        # Newest first
        assert recent[0].type == "type-14"
        assert recent[-1].type == "type-5"

    def test_recent_conditions_empty(self):
        rec = BackendStatusRecord(name="b")
        assert rec.recent_conditions == []

    def test_full_lifecycle(self):
        """Walk through a complete lifecycle: PENDING → INIT → READY → DEGRADED → SHUTTING_DOWN."""
        rec = BackendStatusRecord(name="lifecycle")
        rec.transition(BackendPhase.INITIALIZING, "connecting")
        rec.transition(BackendPhase.READY, "all good")
        rec.transition(BackendPhase.DEGRADED, "health check slow")
        rec.transition(BackendPhase.SHUTTING_DOWN, "shutting down")
        assert rec.phase == BackendPhase.SHUTTING_DOWN
        assert len(rec.conditions) == 4

    def test_serialization(self):
        rec = BackendStatusRecord(name="b", tool_count=5)
        rec.transition(BackendPhase.INITIALIZING)
        d = rec.model_dump(mode="json")
        assert d["name"] == "b"
        assert d["tool_count"] == 5
        assert len(d["conditions"]) == 1


# CapabilityInfo


class TestCapabilityInfo:
    def test_defaults(self):
        cap = CapabilityInfo()
        assert cap.tools_count == 0
        assert cap.resources_count == 0
        assert cap.prompts_count == 0
        assert cap.tool_names == []
        assert cap.route_map == {}

    def test_with_data(self):
        cap = CapabilityInfo(
            tools_count=3,
            tool_names=["t1", "t2", "t3"],
            route_map={"t1": ("backend-a", "orig_t1")},
        )
        assert cap.tools_count == 3
        assert len(cap.tool_names) == 3
        assert cap.route_map["t1"] == ("backend-a", "orig_t1")


# ServiceStatus


class TestServiceStatus:
    def test_defaults(self):
        status = ServiceStatus()
        assert status.state == ServiceState.PENDING
        assert status.server_name == ""
        assert status.backends_total == 0
        assert status.uptime_seconds is None
        assert status.error_message is None

    def test_compute_uptime(self):
        started = datetime.now(timezone.utc) - timedelta(seconds=120)
        status = ServiceStatus(started_at=started)
        status.compute_uptime()
        assert status.uptime_seconds is not None
        assert status.uptime_seconds >= 119  # at least 119 seconds

    def test_compute_uptime_not_started(self):
        status = ServiceStatus()
        status.compute_uptime()
        assert status.uptime_seconds is None

    def test_with_backends(self):
        backends = [
            BackendInfo(name="a", type="stdio", connected=True),
            BackendInfo(name="b", type="sse", connected=False, error="timeout"),
        ]
        status = ServiceStatus(
            state=ServiceState.RUNNING,
            backends_total=2,
            backends_connected=1,
            backends=backends,
        )
        assert status.backends_total == 2
        assert status.backends_connected == 1
        assert len(status.backends) == 2

    def test_serialization(self):
        status = ServiceStatus(
            state=ServiceState.RUNNING,
            server_name="test",
            server_version="0.1.0",
        )
        d = status.model_dump(mode="json")
        assert d["state"] == "running"
        assert d["server_name"] == "test"
        rt = ServiceStatus.model_validate(d)
        assert rt.state == ServiceState.RUNNING
