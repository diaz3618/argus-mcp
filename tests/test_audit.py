"""Tests for argus_mcp.audit — models and logger.

Covers:
- AuditSource, AuditTarget, AuditOutcome, AuditEvent model defaults and validation
- AuditLogger init, emit, emit_dict, disabled mode, close
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from argus_mcp.audit.logger import AUDIT_LEVEL, AuditLogger
from argus_mcp.audit.models import (
    AuditEvent,
    AuditOutcome,
    AuditSource,
    AuditTarget,
)

# AuditSource


class TestAuditSource:
    def test_defaults_are_none(self):
        src = AuditSource()
        assert src.session_id is None
        assert src.client_ip is None
        assert src.user_id is None

    def test_explicit_values(self):
        src = AuditSource(session_id="s1", client_ip="10.0.0.1", user_id="alice")
        assert src.session_id == "s1"
        assert src.client_ip == "10.0.0.1"
        assert src.user_id == "alice"

    def test_serialization_round_trip(self):
        src = AuditSource(session_id="abc")
        data = src.model_dump()
        assert data["session_id"] == "abc"
        restored = AuditSource.model_validate(data)
        assert restored == src


# AuditTarget


class TestAuditTarget:
    def test_required_fields(self):
        target = AuditTarget(method="call_tool", capability_name="echo")
        assert target.method == "call_tool"
        assert target.capability_name == "echo"
        assert target.backend is None
        assert target.original_name is None

    def test_all_fields(self):
        target = AuditTarget(
            backend="server-a",
            method="read_resource",
            capability_name="docs_readme",
            original_name="readme",
        )
        assert target.backend == "server-a"
        assert target.original_name == "readme"

    def test_missing_required_raises(self):
        with pytest.raises(Exception):
            AuditTarget()  # method and capability_name are required


# AuditOutcome


class TestAuditOutcome:
    def test_defaults(self):
        outcome = AuditOutcome()
        assert outcome.status == "success"
        assert outcome.latency_ms == 0.0
        assert outcome.error is None
        assert outcome.error_type is None

    def test_error_outcome(self):
        outcome = AuditOutcome(
            status="error",
            latency_ms=123.4,
            error="connection refused",
            error_type="ConnectionError",
        )
        assert outcome.status == "error"
        assert outcome.latency_ms == 123.4
        assert outcome.error == "connection refused"
        assert outcome.error_type == "ConnectionError"


# AuditEvent


class TestAuditEvent:
    def test_defaults(self):
        event = AuditEvent(target=AuditTarget(method="call_tool", capability_name="echo"))
        assert event.event_type == "mcp_operation"
        assert event.metadata == {}
        # event_id should be a UUID string
        uuid.UUID(event.event_id)  # raises if invalid

    def test_timestamp_is_utc_iso(self):
        event = AuditEvent(target=AuditTarget(method="call_tool", capability_name="echo"))
        ts = datetime.fromisoformat(event.timestamp)
        assert ts.tzinfo is not None  # should be timezone-aware

    def test_each_event_gets_unique_id(self):
        ids = set()
        for _ in range(50):
            event = AuditEvent(target=AuditTarget(method="call_tool", capability_name="test"))
            ids.add(event.event_id)
        assert len(ids) == 50

    def test_custom_metadata(self):
        event = AuditEvent(
            target=AuditTarget(method="call_tool", capability_name="echo"),
            metadata={"custom_key": "custom_value"},
        )
        assert event.metadata["custom_key"] == "custom_value"

    def test_model_dump_json(self):
        event = AuditEvent(
            target=AuditTarget(method="call_tool", capability_name="echo"),
            outcome=AuditOutcome(status="error", error="boom"),
        )
        raw = event.model_dump_json()
        parsed = json.loads(raw)
        assert parsed["event_type"] == "mcp_operation"
        assert parsed["target"]["capability_name"] == "echo"
        assert parsed["outcome"]["error"] == "boom"

    def test_source_defaults_to_empty(self):
        event = AuditEvent(target=AuditTarget(method="call_tool", capability_name="echo"))
        assert event.source.session_id is None

    def test_explicit_source(self):
        event = AuditEvent(
            source=AuditSource(session_id="s1", user_id="bob"),
            target=AuditTarget(method="call_tool", capability_name="echo"),
        )
        assert event.source.user_id == "bob"


# AuditLogger


class TestAuditLogger:
    def test_disabled_logger_skips_emit(self, tmp_path):
        logger = AuditLogger(log_dir=str(tmp_path), enabled=False)
        assert logger.enabled is False
        event = AuditEvent(target=AuditTarget(method="call_tool", capability_name="echo"))
        logger.emit(event)  # should not raise or write
        logger.emit_dict({"key": "val"})  # also safe
        # No log file should be created
        assert not list(tmp_path.iterdir())

    def test_enabled_logger_writes_json_lines(self, tmp_path):
        logger = AuditLogger(
            log_dir=str(tmp_path),
            filename="test_audit.jsonl",
            enabled=True,
        )
        assert logger.enabled is True

        event = AuditEvent(target=AuditTarget(method="call_tool", capability_name="echo"))
        logger.emit(event)
        logger.close()

        log_file = tmp_path / "test_audit.jsonl"
        assert log_file.exists()
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) >= 1
        parsed = json.loads(lines[-1])
        assert parsed["target"]["capability_name"] == "echo"

    def test_emit_dict_writes_json(self, tmp_path):
        logger = AuditLogger(
            log_dir=str(tmp_path),
            filename="test_audit.jsonl",
            enabled=True,
        )
        logger.emit_dict({"action": "test", "count": 42})
        logger.close()

        log_file = tmp_path / "test_audit.jsonl"
        lines = log_file.read_text().strip().splitlines()
        assert len(lines) >= 1
        parsed = json.loads(lines[-1])
        assert parsed["action"] == "test"
        assert parsed["count"] == 42

    def test_close_and_reclose_is_safe(self, tmp_path):
        logger = AuditLogger(log_dir=str(tmp_path), enabled=True)
        logger.close()
        logger.close()  # second close should not raise

    def test_creates_log_directory(self, tmp_path):
        nested = tmp_path / "sub" / "deep"
        logger = AuditLogger(log_dir=str(nested), enabled=True)
        assert nested.exists()
        logger.close()

    def test_audit_level_is_between_warning_and_error(self):
        import logging

        assert logging.WARNING < AUDIT_LEVEL < logging.ERROR
        assert AUDIT_LEVEL == 35

    def test_emit_with_broken_event_does_not_raise(self, tmp_path):
        """Emit should catch exceptions gracefully."""
        logger = AuditLogger(log_dir=str(tmp_path), enabled=True)
        # Patch model_dump_json to raise
        bad_event = MagicMock()
        bad_event.model_dump_json.side_effect = RuntimeError("serialize fail")
        # Should not raise — emit catches exceptions
        logger.emit(bad_event)
        logger.close()
