"""
Covers:
  Workflow DSL, executor, composite tool
  Elicitation bridge
  Version drift detection
  Skills manifest + manager
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from typing import Any, Dict

import pytest

# 5.1 Workflow — Steps
from argus_mcp.workflows.steps import Step, StepResult, StepStatus


class TestStepStatus:
    def test_enum_values(self):
        assert StepStatus.PENDING.value == "pending"
        assert StepStatus.COMPLETED.value == "completed"
        assert StepStatus.FAILED.value == "failed"
        assert StepStatus.SKIPPED.value == "skipped"


class TestStepResult:
    def test_defaults(self):
        r = StepResult(step_id="s1", status=StepStatus.COMPLETED)
        assert r.output is None
        assert r.error is None
        assert r.duration_ms == 0.0

    def test_with_output(self):
        r = StepResult(step_id="s1", status=StepStatus.COMPLETED, output={"key": 1})
        assert r.output == {"key": 1}


class TestStep:
    def test_from_dict_minimal(self):
        s = Step.from_dict({"id": "a", "tool": "t.do"})
        assert s.id == "a"
        assert s.tool == "t.do"
        assert s.args == {}
        assert s.depends_on == []
        assert s.retry == 0
        assert s.on_error == "fail"

    def test_from_dict_full(self):
        s = Step.from_dict(
            {
                "id": "b",
                "tool": "x.y",
                "args": {"k": "v"},
                "depends_on": ["a"],
                "condition": "${a.status} == 'completed'",
                "retry": 2,
                "on_error": "skip",
                "description": "do stuff",
            }
        )
        assert s.depends_on == ["a"]
        assert s.retry == 2
        assert s.on_error == "skip"


# 5.1 Workflow — DSL
from argus_mcp.workflows.dsl import (
    WorkflowValidationError,
    parse_workflow,
)


class TestParseWorkflow:
    def test_valid_linear(self):
        wf = parse_workflow(
            {
                "name": "test-wf",
                "steps": [
                    {"id": "s1", "tool": "t1"},
                    {"id": "s2", "tool": "t2", "depends_on": ["s1"]},
                ],
            }
        )
        assert wf.name == "test-wf"
        assert len(wf.steps) == 2

    def test_missing_name(self):
        with pytest.raises(WorkflowValidationError, match="name"):
            parse_workflow({"steps": [{"id": "s1", "tool": "t"}]})

    def test_no_steps(self):
        with pytest.raises(WorkflowValidationError, match="no steps"):
            parse_workflow({"name": "empty"})

    def test_duplicate_ids(self):
        with pytest.raises(WorkflowValidationError, match="Duplicate"):
            parse_workflow(
                {
                    "name": "dup",
                    "steps": [
                        {"id": "s1", "tool": "t"},
                        {"id": "s1", "tool": "t2"},
                    ],
                }
            )

    def test_bad_dependency(self):
        with pytest.raises(WorkflowValidationError, match="unknown step"):
            parse_workflow(
                {
                    "name": "bad-dep",
                    "steps": [
                        {"id": "s1", "tool": "t", "depends_on": ["nope"]},
                    ],
                }
            )

    def test_cycle_detected(self):
        with pytest.raises(WorkflowValidationError, match="Cycle"):
            parse_workflow(
                {
                    "name": "cycle",
                    "steps": [
                        {"id": "a", "tool": "t", "depends_on": ["b"]},
                        {"id": "b", "tool": "t", "depends_on": ["a"]},
                    ],
                }
            )


class TestTopologicalOrder:
    def test_parallel_steps(self):
        wf = parse_workflow(
            {
                "name": "par",
                "steps": [
                    {"id": "a", "tool": "t"},
                    {"id": "b", "tool": "t"},
                ],
            }
        )
        levels = wf.topological_order()
        assert len(levels) == 1
        ids = {s.id for s in levels[0]}
        assert ids == {"a", "b"}

    def test_sequential_levels(self):
        wf = parse_workflow(
            {
                "name": "seq",
                "steps": [
                    {"id": "a", "tool": "t"},
                    {"id": "b", "tool": "t", "depends_on": ["a"]},
                    {"id": "c", "tool": "t", "depends_on": ["b"]},
                ],
            }
        )
        levels = wf.topological_order()
        assert len(levels) == 3
        assert levels[0][0].id == "a"
        assert levels[1][0].id == "b"
        assert levels[2][0].id == "c"

    def test_diamond(self):
        wf = parse_workflow(
            {
                "name": "diamond",
                "steps": [
                    {"id": "a", "tool": "t"},
                    {"id": "b", "tool": "t", "depends_on": ["a"]},
                    {"id": "c", "tool": "t", "depends_on": ["a"]},
                    {"id": "d", "tool": "t", "depends_on": ["b", "c"]},
                ],
            }
        )
        levels = wf.topological_order()
        assert len(levels) == 3
        level2_ids = {s.id for s in levels[1]}
        assert level2_ids == {"b", "c"}


# 5.1 Workflow — Executor
from argus_mcp.workflows.executor import WorkflowExecutor


def _make_tool_invoker(results: Dict[str, Any] | None = None):
    """Return an async callable that returns canned results by tool name."""
    mapping = results or {}

    async def invoke(tool_name: str, args: Dict[str, Any]) -> Any:
        if tool_name in mapping:
            val = mapping[tool_name]
            if callable(val):
                return val(args)
            return val
        return {"ok": True, "tool": tool_name, "args": args}

    return invoke


class TestWorkflowExecutor:
    def test_single_step(self):
        wf = parse_workflow(
            {
                "name": "one",
                "steps": [{"id": "s1", "tool": "echo"}],
            }
        )
        invoker = _make_tool_invoker({"echo": "hello"})
        executor = WorkflowExecutor(invoker)
        results = asyncio.run(executor.execute(wf))
        assert results["s1"].status == StepStatus.COMPLETED
        assert results["s1"].output == "hello"

    def test_sequential_interpolation(self):
        wf = parse_workflow(
            {
                "name": "interp",
                "steps": [
                    {"id": "s1", "tool": "echo"},
                    {
                        "id": "s2",
                        "tool": "consume",
                        "depends_on": ["s1"],
                        "args": {"data": "${s1.output}"},
                    },
                ],
            }
        )

        async def invoker(tool: str, args: dict) -> Any:
            if tool == "echo":
                return {"value": 42}
            return args

        executor = WorkflowExecutor(invoker)
        results = asyncio.run(executor.execute(wf))
        assert results["s2"].output["data"] == {"value": 42}

    def test_parallel_execution(self):
        wf = parse_workflow(
            {
                "name": "par",
                "steps": [
                    {"id": "a", "tool": "t"},
                    {"id": "b", "tool": "t"},
                ],
            }
        )
        call_order = []

        async def invoker(tool: str, args: dict) -> Any:
            call_order.append(tool)
            return None

        executor = WorkflowExecutor(invoker)
        asyncio.run(executor.execute(wf))
        # Both should run (order may vary since they're in same level)
        assert len(call_order) == 2

    def test_retry_on_failure(self):
        wf = parse_workflow(
            {
                "name": "retry",
                "steps": [{"id": "s1", "tool": "flaky", "retry": 2, "on_error": "continue"}],
            }
        )
        attempt_count = {"n": 0}

        async def invoker(tool: str, args: dict) -> Any:
            attempt_count["n"] += 1
            if attempt_count["n"] < 3:
                raise RuntimeError("fail")
            return "ok"

        executor = WorkflowExecutor(invoker)
        results = asyncio.run(executor.execute(wf))
        assert results["s1"].status == StepStatus.COMPLETED
        assert attempt_count["n"] == 3

    def test_condition_skip(self):
        wf = parse_workflow(
            {
                "name": "cond",
                "steps": [
                    {"id": "s1", "tool": "t"},
                    {
                        "id": "s2",
                        "tool": "t",
                        "depends_on": ["s1"],
                        "condition": "${s1.status} == 'failed'",
                    },
                ],
            }
        )
        invoker = _make_tool_invoker({"t": "done"})
        executor = WorkflowExecutor(invoker)
        results = asyncio.run(executor.execute(wf))
        assert results["s2"].status == StepStatus.SKIPPED

    def test_fail_fast(self):
        wf = parse_workflow(
            {
                "name": "failfast",
                "steps": [
                    {"id": "s1", "tool": "boom"},
                    {"id": "s2", "tool": "t", "depends_on": ["s1"]},
                ],
            }
        )

        async def invoker(tool: str, args: dict) -> Any:
            if tool == "boom":
                raise RuntimeError("kaboom")
            return "ok"

        executor = WorkflowExecutor(invoker)
        results = asyncio.run(executor.execute(wf))
        # s1 should fail (caught by _execute_step retry)
        assert results["s1"].status == StepStatus.FAILED
        assert "kaboom" in results["s1"].error
        # s2 should fail because its dependency s1 failed (default on_error=fail)
        assert results["s2"].status == StepStatus.FAILED

    def test_input_interpolation(self):
        wf = parse_workflow(
            {
                "name": "inp",
                "steps": [
                    {"id": "s1", "tool": "echo", "args": {"q": "${inputs.query}"}},
                ],
                "inputs": {"query": {"type": "string"}},
            }
        )

        async def invoker(tool: str, args: dict) -> Any:
            return args

        executor = WorkflowExecutor(invoker)
        results = asyncio.run(executor.execute(wf, inputs={"query": "hello"}))
        assert results["s1"].output["q"] == "hello"

    def test_condition_neq(self):
        wf = parse_workflow(
            {
                "name": "neq",
                "steps": [
                    {"id": "s1", "tool": "t"},
                    {
                        "id": "s2",
                        "tool": "t",
                        "depends_on": ["s1"],
                        "condition": "${s1.status} != 'failed'",
                    },
                ],
            }
        )
        invoker = _make_tool_invoker({"t": "done"})
        executor = WorkflowExecutor(invoker)
        results = asyncio.run(executor.execute(wf))
        assert results["s2"].status == StepStatus.COMPLETED


# 5.1 Workflow — Composite Tool
from argus_mcp.workflows.composite_tool import CompositeTool, load_composite_tools


class TestCompositeTool:
    def test_properties(self):
        wf = parse_workflow(
            {
                "name": "my-tool",
                "description": "desc",
                "steps": [{"id": "s1", "tool": "t"}],
                "inputs": {"x": {"type": "string", "description": "param x"}},
            }
        )
        invoker = _make_tool_invoker()
        ct = CompositeTool(wf, invoker)
        assert ct.name == "my-tool"
        assert ct.description == "desc"
        schema = ct.input_schema
        assert "x" in schema["properties"]
        assert schema["properties"]["x"]["type"] == "string"

    def test_invoke_returns_output(self):
        wf = parse_workflow(
            {
                "name": "ct",
                "steps": [{"id": "s1", "tool": "echo"}],
            }
        )
        invoker = _make_tool_invoker({"echo": {"result": 42}})
        ct = CompositeTool(wf, invoker)
        result = asyncio.run(ct.invoke({}))
        assert result == {"result": 42}

    def test_to_tool_info(self):
        wf = parse_workflow(
            {
                "name": "info",
                "description": "info tool",
                "steps": [{"id": "s1", "tool": "t"}],
            }
        )
        ct = CompositeTool(wf, _make_tool_invoker())
        info = ct.to_tool_info()
        assert info["name"] == "info"
        assert "inputSchema" in info

    def test_load_composite_tools(self):
        defs = [
            {"name": "w1", "steps": [{"id": "s", "tool": "t"}]},
            {"name": "w2", "steps": [{"id": "s", "tool": "t"}]},
        ]
        tools = load_composite_tools(defs, _make_tool_invoker())
        assert len(tools) == 2
        assert tools[0].name == "w1"

    def test_output_template(self):
        wf = parse_workflow(
            {
                "name": "tmpl",
                "steps": [{"id": "s1", "tool": "echo"}],
                "output": "${s1.output}",
            }
        )
        invoker = _make_tool_invoker({"echo": "final"})
        ct = CompositeTool(wf, invoker)
        result = asyncio.run(ct.invoke({}))
        assert result == "final"


# 5.2 Elicitation
from argus_mcp.bridge.elicitation import (
    ElicitationBridge,
    ElicitationField,
    ElicitationRequest,
    ElicitationResponse,
    ElicitationStatus,
)


class TestElicitationField:
    def test_from_schema(self):
        f = ElicitationField.from_schema(
            "email",
            {"type": "string", "description": "User email"},
            ["email"],
        )
        assert f.name == "email"
        assert f.field_type == "string"
        assert f.required is True

    def test_optional_field(self):
        f = ElicitationField.from_schema("age", {"type": "integer"}, [])
        assert f.required is False
        assert f.field_type == "integer"


class TestElicitationRequest:
    def test_from_message(self):
        req = ElicitationRequest.from_message(
            {
                "requestId": "abc123",
                "toolName": "my-tool",
                "message": "Need info",
                "schema": {
                    "properties": {
                        "name": {"type": "string"},
                        "age": {"type": "integer"},
                    },
                    "required": ["name"],
                },
            }
        )
        assert req.request_id == "abc123"
        assert req.tool_name == "my-tool"
        fields = req.fields
        assert len(fields) == 2
        name_field = next(f for f in fields if f.name == "name")
        assert name_field.required is True

    def test_auto_id_generation(self):
        req = ElicitationRequest.from_message({"message": "hi"})
        assert len(req.request_id) == 12


class TestElicitationResponse:
    def test_to_message(self):
        resp = ElicitationResponse(
            request_id="r1",
            status=ElicitationStatus.APPROVED,
            data={"name": "Alice"},
        )
        msg = resp.to_message()
        assert msg["requestId"] == "r1"
        assert msg["status"] == "approved"
        assert msg["data"]["name"] == "Alice"


class TestElicitationBridge:
    def test_no_handler_denies(self):
        bridge = ElicitationBridge()
        req = ElicitationRequest(request_id="r1", message="hi")
        resp = asyncio.run(bridge.handle_request(req))
        assert resp.status == ElicitationStatus.DENIED

    def test_handler_approved(self):
        bridge = ElicitationBridge()

        async def handler(req: ElicitationRequest) -> dict | None:
            return {"name": "Bob"}

        bridge.register_handler(handler)
        req = ElicitationRequest(request_id="r2", message="hi")
        resp = asyncio.run(bridge.handle_request(req))
        assert resp.status == ElicitationStatus.APPROVED
        assert resp.data["name"] == "Bob"

    def test_handler_returns_none_denies(self):
        bridge = ElicitationBridge()

        async def handler(req: ElicitationRequest) -> dict | None:
            return None

        bridge.register_handler(handler)
        req = ElicitationRequest(request_id="r3", message="hi")
        resp = asyncio.run(bridge.handle_request(req))
        assert resp.status == ElicitationStatus.DENIED

    def test_timeout(self):
        bridge = ElicitationBridge(default_timeout=0.1)

        async def slow_handler(req: ElicitationRequest) -> dict | None:
            await asyncio.sleep(5)
            return {"too": "late"}

        bridge.register_handler(slow_handler)
        req = ElicitationRequest(request_id="r4", message="hi", timeout_seconds=0.1)
        resp = asyncio.run(bridge.handle_request(req))
        assert resp.status == ElicitationStatus.TIMEOUT

    def test_has_pending(self):
        bridge = ElicitationBridge()
        assert bridge.has_pending is False


# 5.4 Version Drift
from argus_mcp.bridge.version_checker import (
    DriftResult,
    DriftSeverity,
    VersionChecker,
    classify_drift,
    parse_semver,
)


class TestParseSemver:
    def test_valid(self):
        assert parse_semver("1.2.3") == (1, 2, 3)

    def test_with_v_prefix(self):
        assert parse_semver("v2.0.1") == (2, 0, 1)

    def test_with_prerelease(self):
        assert parse_semver("1.0.0-beta.1") == (1, 0, 0)

    def test_invalid(self):
        assert parse_semver("not-a-version") is None


class TestClassifyDrift:
    def test_current(self):
        assert classify_drift("1.2.3", "1.2.3") == DriftSeverity.CURRENT

    def test_patch(self):
        assert classify_drift("1.2.3", "1.2.5") == DriftSeverity.PATCH

    def test_minor(self):
        assert classify_drift("1.2.3", "1.4.0") == DriftSeverity.MINOR

    def test_major(self):
        assert classify_drift("1.2.3", "2.0.0") == DriftSeverity.MAJOR

    def test_ahead_is_current(self):
        assert classify_drift("2.0.0", "1.5.0") == DriftSeverity.CURRENT

    def test_unknown(self):
        assert classify_drift("abc", "1.0.0") == DriftSeverity.UNKNOWN


class TestDriftResult:
    def test_is_drifted(self):
        r = DriftResult("t", "1.0.0", "2.0.0", DriftSeverity.MAJOR)
        assert r.is_drifted is True

    def test_not_drifted(self):
        r = DriftResult("t", "1.0.0", "1.0.0", DriftSeverity.CURRENT)
        assert r.is_drifted is False

    def test_unknown_not_drifted(self):
        r = DriftResult("t", "?", "?", DriftSeverity.UNKNOWN)
        assert r.is_drifted is False


class TestVersionChecker:
    def test_no_registry(self):
        checker = VersionChecker(registry_client=None)
        results = asyncio.run(checker.check_all({"t": {"version": "1.0.0"}}))
        assert results == []

    def test_check_one_no_registry(self):
        checker = VersionChecker()
        result = asyncio.run(checker.check_one("t", "1.0.0"))
        assert result is None

    def test_check_all_with_mock_registry(self):
        class FakeRegistry:
            async def get_server(self, name):
                class S:
                    version = "2.0.0"

                return S()

        checker = VersionChecker(registry_client=FakeRegistry())
        results = asyncio.run(checker.check_all({"tool-a": {"version": "1.0.0"}}))
        assert len(results) == 1
        assert results[0].severity == DriftSeverity.MAJOR

    def test_get_drift_summary(self):
        checker = VersionChecker()
        results = [
            DriftResult("a", "1.0.0", "1.0.1", DriftSeverity.PATCH),
            DriftResult("b", "1.0.0", "2.0.0", DriftSeverity.MAJOR),
            DriftResult("c", "1.0.0", "1.0.0", DriftSeverity.CURRENT),
        ]
        summary = checker.get_drift_summary(results)
        assert summary["patch"] == 1
        assert summary["major"] == 1
        assert summary["current"] == 1


# 5.6 Skills — Manifest
from argus_mcp.skills.manifest import SkillManifest, SkillManifestError


class TestSkillManifest:
    def test_from_dict_minimal(self):
        m = SkillManifest.from_dict({"name": "test-skill"})
        assert m.name == "test-skill"
        assert m.version == "0.0.0"
        assert m.tools == []

    def test_from_dict_full(self):
        m = SkillManifest.from_dict(
            {
                "name": "full",
                "version": "1.2.3",
                "description": "desc",
                "tools": [{"name": "tool-a"}],
                "workflows": [{"name": "wf-a"}],
                "config": {"key": "val"},
                "dependencies": ["other"],
                "author": "Me",
                "license": "GPL-3.0-only",
            }
        )
        assert m.version == "1.2.3"
        assert len(m.tools) == 1
        assert m.dependencies == ["other"]

    def test_missing_name_raises(self):
        with pytest.raises(SkillManifestError, match="name"):
            SkillManifest.from_dict({})

    def test_to_dict_roundtrip(self):
        data = {
            "name": "rt",
            "version": "0.1.0",
            "description": "",
            "tools": [],
            "workflows": [],
            "config": {},
            "dependencies": [],
            "author": "",
            "license": "",
        }
        m = SkillManifest.from_dict(data)
        assert m.to_dict() == data

    def test_validate_ok(self):
        m = SkillManifest(name="ok", version="1.0.0", tools=[{"name": "t"}])
        assert m.validate() == []

    def test_validate_missing_name(self):
        m = SkillManifest(name="", version="1.0.0")
        errors = m.validate()
        assert any("name" in e.lower() for e in errors)

    def test_validate_bad_tool(self):
        m = SkillManifest(name="t", version="1.0.0", tools=[{"no_name": True}])
        errors = m.validate()
        assert any("name" in e.lower() for e in errors)

    def test_from_file(self):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            json.dump({"name": "file-skill", "version": "1.0.0"}, f)
            f.flush()
            path = f.name

        try:
            m = SkillManifest.from_file(path)
            assert m.name == "file-skill"
        finally:
            os.unlink(path)

    def test_from_file_bad_json(self):
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            f.write("not json")
            f.flush()
            path = f.name
        try:
            with pytest.raises(SkillManifestError, match="Failed to read"):
                SkillManifest.from_file(path)
        finally:
            os.unlink(path)


# 5.6 Skills — Manager
from argus_mcp.skills.manager import SkillManager, SkillStatus


class TestSkillStatus:
    def test_values(self):
        assert SkillStatus.ENABLED.value == "enabled"
        assert SkillStatus.DISABLED.value == "disabled"


class TestSkillManager:
    def _make_skill_dir(self, tmpdir: str, name: str, version: str = "1.0.0"):
        skill_dir = os.path.join(tmpdir, name)
        os.makedirs(skill_dir, exist_ok=True)
        manifest = {"name": name, "version": version, "tools": [{"name": f"{name}-tool"}]}
        with open(os.path.join(skill_dir, "manifest.json"), "w") as f:
            json.dump(manifest, f)
        return skill_dir

    def test_discover_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SkillManager(skills_dir=tmpdir)
            assert mgr.discover() == []

    def test_discover_skills(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_skill_dir(tmpdir, "skill-a")
            self._make_skill_dir(tmpdir, "skill-b")
            mgr = SkillManager(skills_dir=tmpdir)
            skills = mgr.discover()
            assert len(skills) == 2
            names = {s.name for s in skills}
            assert names == {"skill-a", "skill-b"}

    def test_install_and_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skills_dir = os.path.join(tmpdir, "installed")
            source_dir = os.path.join(tmpdir, "source", "my-skill")
            os.makedirs(source_dir)
            manifest = {"name": "my-skill", "version": "1.0.0", "tools": [{"name": "t"}]}
            with open(os.path.join(source_dir, "manifest.json"), "w") as f:
                json.dump(manifest, f)

            mgr = SkillManager(skills_dir=skills_dir)
            skill = mgr.install(source_dir)
            assert skill.name == "my-skill"
            assert skill.status == SkillStatus.ENABLED
            assert len(mgr.list_skills()) == 1

    def test_enable_disable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_skill_dir(tmpdir, "toggleable")
            mgr = SkillManager(skills_dir=tmpdir)
            mgr.discover()

            mgr.disable("toggleable")
            assert mgr.get("toggleable").status == SkillStatus.DISABLED
            assert mgr.list_enabled() == []

            mgr.enable("toggleable")
            assert mgr.get("toggleable").status == SkillStatus.ENABLED
            assert len(mgr.list_enabled()) == 1

    def test_uninstall(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_skill_dir(tmpdir, "removable")
            mgr = SkillManager(skills_dir=tmpdir)
            mgr.discover()
            mgr.uninstall("removable")
            assert mgr.list_skills() == []
            assert not os.path.isdir(os.path.join(tmpdir, "removable"))

    def test_uninstall_unknown(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = SkillManager(skills_dir=tmpdir)
            with pytest.raises(ValueError, match="not installed"):
                mgr.uninstall("nope")

    def test_get_skill_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "cfg-skill")
            os.makedirs(skill_dir)
            manifest = {"name": "cfg-skill", "config": {"key": "val"}}
            with open(os.path.join(skill_dir, "manifest.json"), "w") as f:
                json.dump(manifest, f)

            mgr = SkillManager(skills_dir=tmpdir)
            mgr.discover()
            cfg = mgr.get_skill_config("cfg-skill")
            assert cfg == {"key": "val"}

    def test_get_all_tools(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_skill_dir(tmpdir, "tool-skill")
            mgr = SkillManager(skills_dir=tmpdir)
            mgr.discover()
            tools = mgr.get_all_tools()
            assert len(tools) == 1
            assert tools[0]["name"] == "tool-skill-tool"
            assert tools[0]["_skill"] == "tool-skill"

    def test_state_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            self._make_skill_dir(tmpdir, "persist-skill")
            mgr = SkillManager(skills_dir=tmpdir)
            mgr.discover()
            mgr.disable("persist-skill")

            # New manager reads persisted state
            mgr2 = SkillManager(skills_dir=tmpdir)
            mgr2.discover()
            assert mgr2.get("persist-skill").status == SkillStatus.DISABLED

    def test_install_no_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            empty_dir = os.path.join(tmpdir, "empty")
            os.makedirs(empty_dir)
            mgr = SkillManager(skills_dir=tmpdir)
            with pytest.raises(SkillManifestError, match="No manifest"):
                mgr.install(empty_dir)

    def test_discover_nonexistent_dir(self):
        mgr = SkillManager(skills_dir="/tmp/nonexistent_argus_test_dir_xyz")
        assert mgr.discover() == []
