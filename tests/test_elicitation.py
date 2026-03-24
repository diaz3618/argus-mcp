"""Tests for argus_mcp.bridge.elicitation — ElicitationBridge protocol.

Covers:
- ElicitationField.from_schema
- ElicitationRequest construction, from_message, fields property
- ElicitationResponse.to_message
- ElicitationBridge: no handler (auto-deny), timeout, NULL result (deny),
  successful approval, pending tracking
"""

from __future__ import annotations

import asyncio

import pytest

from argus_mcp.bridge.elicitation import (
    ElicitationBridge,
    ElicitationField,
    ElicitationRequest,
    ElicitationResponse,
    ElicitationStatus,
)

# ElicitationField


class TestElicitationField:
    def test_defaults(self):
        f = ElicitationField(name="username")
        assert f.field_type == "string"
        assert f.description == ""
        assert f.required is False
        assert f.default is None
        assert f.enum_values == []

    def test_from_schema_basic(self):
        prop = {"type": "integer", "description": "Age in years"}
        f = ElicitationField.from_schema("age", prop, required_list=["age"])
        assert f.name == "age"
        assert f.field_type == "integer"
        assert f.description == "Age in years"
        assert f.required is True

    def test_from_schema_not_required(self):
        prop = {"type": "string", "default": "N/A"}
        f = ElicitationField.from_schema("notes", prop, required_list=[])
        assert f.required is False
        assert f.default == "N/A"

    def test_from_schema_with_enum(self):
        prop = {"type": "string", "enum": ["red", "green", "blue"]}
        f = ElicitationField.from_schema("color", prop, required_list=[])
        assert f.enum_values == ["red", "green", "blue"]

    def test_from_schema_missing_type_defaults_to_string(self):
        f = ElicitationField.from_schema("x", {}, required_list=[])
        assert f.field_type == "string"


# ElicitationRequest


class TestElicitationRequest:
    def test_defaults(self):
        req = ElicitationRequest()
        assert len(req.request_id) == 12
        assert req.tool_name == ""
        assert req.message == ""
        assert req.schema == {}
        assert req.timeout_seconds == 120.0

    def test_from_message(self):
        data = {
            "requestId": "abc123def456",
            "toolName": "search",
            "message": "Enter query",
            "schema": {"properties": {"q": {"type": "string"}}, "required": ["q"]},
            "timeout": 30.0,
        }
        req = ElicitationRequest.from_message(data)
        assert req.request_id == "abc123def456"
        assert req.tool_name == "search"
        assert req.timeout_seconds == 30.0

    def test_from_message_defaults(self):
        req = ElicitationRequest.from_message({})
        assert req.tool_name == ""
        assert req.timeout_seconds == 120.0
        assert len(req.request_id) == 12

    def test_fields_property(self):
        req = ElicitationRequest(
            schema={
                "properties": {
                    "name": {"type": "string", "description": "Your name"},
                    "age": {"type": "integer"},
                },
                "required": ["name"],
            }
        )
        fields = req.fields
        assert len(fields) == 2
        names = {f.name for f in fields}
        assert names == {"name", "age"}
        name_field = next(f for f in fields if f.name == "name")
        assert name_field.required is True
        assert name_field.description == "Your name"

    def test_fields_empty_schema(self):
        req = ElicitationRequest(schema={})
        assert req.fields == []


# ElicitationResponse


class TestElicitationResponse:
    def test_to_message_approved(self):
        resp = ElicitationResponse(
            request_id="r1",
            status=ElicitationStatus.APPROVED,
            data={"name": "Alice"},
        )
        msg = resp.to_message()
        assert msg == {
            "requestId": "r1",
            "status": "approved",
            "data": {"name": "Alice"},
        }

    def test_to_message_denied(self):
        resp = ElicitationResponse(
            request_id="r2",
            status=ElicitationStatus.DENIED,
        )
        msg = resp.to_message()
        assert msg["status"] == "denied"
        assert msg["data"] == {}

    def test_to_message_timeout(self):
        resp = ElicitationResponse(
            request_id="r3",
            status=ElicitationStatus.TIMEOUT,
        )
        assert resp.to_message()["status"] == "timeout"


# ElicitationBridge


class TestElicitationBridge:
    @pytest.mark.asyncio
    async def test_no_handler_auto_denies(self):
        bridge = ElicitationBridge()
        req = ElicitationRequest(request_id="test1", tool_name="search")

        resp = await bridge.handle_request(req)
        assert resp.status == ElicitationStatus.DENIED
        assert resp.request_id == "test1"

    @pytest.mark.asyncio
    async def test_handler_returns_none_means_denied(self):
        bridge = ElicitationBridge()

        async def handler(request):
            return None

        bridge.register_handler(handler)
        req = ElicitationRequest(request_id="test2")

        resp = await bridge.handle_request(req)
        assert resp.status == ElicitationStatus.DENIED

    @pytest.mark.asyncio
    async def test_handler_returns_data_means_approved(self):
        bridge = ElicitationBridge()

        async def handler(request):
            return {"answer": 42}

        bridge.register_handler(handler)
        req = ElicitationRequest(request_id="test3")

        resp = await bridge.handle_request(req)
        assert resp.status == ElicitationStatus.APPROVED
        assert resp.data == {"answer": 42}

    @pytest.mark.asyncio
    async def test_timeout_returns_timeout_status(self):
        bridge = ElicitationBridge()

        async def slow_handler(request):
            await asyncio.sleep(10)
            return {"late": True}

        bridge.register_handler(slow_handler)
        req = ElicitationRequest(request_id="test4", timeout_seconds=0.05)

        resp = await bridge.handle_request(req)
        assert resp.status == ElicitationStatus.TIMEOUT

    def test_has_pending_false_initially(self):
        bridge = ElicitationBridge()
        assert bridge.has_pending is False

    @pytest.mark.asyncio
    async def test_pending_cleared_after_completion(self):
        bridge = ElicitationBridge()

        async def handler(request):
            return {"ok": True}

        bridge.register_handler(handler)
        req = ElicitationRequest(request_id="test5")
        await bridge.handle_request(req)
        assert bridge.has_pending is False

    @pytest.mark.asyncio
    async def test_pending_cleared_after_timeout(self):
        bridge = ElicitationBridge()

        async def slow_handler(request):
            await asyncio.sleep(10)
            return {}

        bridge.register_handler(slow_handler)
        req = ElicitationRequest(request_id="test6", timeout_seconds=0.05)
        await bridge.handle_request(req)
        assert bridge.has_pending is False

    @pytest.mark.asyncio
    async def test_default_timeout_used_when_request_timeout_is_zero(self):
        bridge = ElicitationBridge(default_timeout=0.05)

        async def slow_handler(request):
            await asyncio.sleep(10)
            return {}

        bridge.register_handler(slow_handler)
        req = ElicitationRequest(request_id="test7", timeout_seconds=0.0)

        resp = await bridge.handle_request(req)
        assert resp.status == ElicitationStatus.TIMEOUT
