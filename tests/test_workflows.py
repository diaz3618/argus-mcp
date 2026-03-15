"""Tests for argus_mcp.workflows — steps, DSL, executor, composite tools.

Covers:
- Step / StepResult / StepStatus data classes
- WorkflowDefinition.topological_order (linear, parallel, cycle detection)
- parse_workflow validation (missing name/steps, duplicate IDs, bad deps)
- WorkflowExecutor (interpolation, conditions, retry, on_error strategies)
- CompositeTool (properties, invoke, to_tool_info, load_composite_tools)
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from argus_mcp.workflows.composite_tool import CompositeTool, load_composite_tools
from argus_mcp.workflows.dsl import (
    WorkflowDefinition,
    WorkflowValidationError,
    parse_workflow,
)
from argus_mcp.workflows.executor import WorkflowExecutor
from argus_mcp.workflows.steps import Step, StepResult, StepStatus

# Step / StepResult ───────────────────────────────────────────────────


class TestStep:
    def test_defaults(self):
        s = Step(id="s1", tool="echo")
        assert s.args == {}
        assert s.depends_on == []
        assert s.condition == ""
        assert s.retry == 0
        assert s.on_error == "fail"

    def test_from_dict_minimal(self):
        s = Step.from_dict({"id": "s1", "tool": "t"})
        assert s.id == "s1"
        assert s.tool == "t"

    def test_from_dict_full(self):
        data = {
            "id": "s1",
            "tool": "t",
            "args": {"k": "v"},
            "depends_on": ["s0"],
            "condition": "${s0.status} == 'completed'",
            "retry": 3,
            "on_error": "skip",
            "description": "Step one",
        }
        s = Step.from_dict(data)
        assert s.depends_on == ["s0"]
        assert s.retry == 3
        assert s.on_error == "skip"
        assert s.description == "Step one"


class TestStepResult:
    def test_defaults(self):
        r = StepResult(step_id="s1", status=StepStatus.COMPLETED)
        assert r.output is None
        assert r.error is None
        assert r.duration_ms == 0.0

    def test_failed_with_error(self):
        r = StepResult(step_id="s1", status=StepStatus.FAILED, error="boom")
        assert r.error == "boom"


class TestStepStatus:
    def test_all_values(self):
        assert {s.value for s in StepStatus} == {
            "pending",
            "running",
            "completed",
            "failed",
            "skipped",
        }


# WorkflowDefinition ─────────────────────────────────────────────────


class TestWorkflowDefinition:
    def test_empty_steps(self):
        wf = WorkflowDefinition(name="w")
        levels = wf.topological_order()
        assert levels == []

    def test_linear_chain(self):
        wf = WorkflowDefinition(
            name="w",
            steps=[
                Step(id="a", tool="t1"),
                Step(id="b", tool="t2", depends_on=["a"]),
                Step(id="c", tool="t3", depends_on=["b"]),
            ],
        )
        levels = wf.topological_order()
        assert len(levels) == 3
        assert [s.id for s in levels[0]] == ["a"]
        assert [s.id for s in levels[1]] == ["b"]
        assert [s.id for s in levels[2]] == ["c"]

    def test_parallel_then_join(self):
        wf = WorkflowDefinition(
            name="w",
            steps=[
                Step(id="a", tool="t"),
                Step(id="b", tool="t"),
                Step(id="c", tool="t", depends_on=["a", "b"]),
            ],
        )
        levels = wf.topological_order()
        assert len(levels) == 2
        first_ids = {s.id for s in levels[0]}
        assert first_ids == {"a", "b"}
        assert [s.id for s in levels[1]] == ["c"]

    def test_cycle_detection(self):
        wf = WorkflowDefinition(
            name="w",
            steps=[
                Step(id="a", tool="t", depends_on=["b"]),
                Step(id="b", tool="t", depends_on=["a"]),
            ],
        )
        with pytest.raises(WorkflowValidationError, match="[Cc]ycle"):
            wf.topological_order()


# parse_workflow ──────────────────────────────────────────────────────


class TestParseWorkflow:
    def test_valid_simple(self):
        wf = parse_workflow(
            {
                "name": "test-wf",
                "steps": [{"id": "s1", "tool": "echo"}],
            }
        )
        assert wf.name == "test-wf"
        assert len(wf.steps) == 1

    def test_missing_name(self):
        with pytest.raises(WorkflowValidationError, match="name"):
            parse_workflow({"steps": [{"id": "s1"}]})

    def test_empty_name(self):
        with pytest.raises(WorkflowValidationError, match="name"):
            parse_workflow({"name": "", "steps": [{"id": "s1"}]})

    def test_no_steps(self):
        with pytest.raises(WorkflowValidationError, match="no steps"):
            parse_workflow({"name": "w", "steps": []})

    def test_missing_step_id(self):
        with pytest.raises(WorkflowValidationError, match="id"):
            parse_workflow({"name": "w", "steps": [{"tool": "t"}]})

    def test_duplicate_step_id(self):
        with pytest.raises(WorkflowValidationError, match="[Dd]uplicate"):
            parse_workflow(
                {
                    "name": "w",
                    "steps": [
                        {"id": "s1", "tool": "t1"},
                        {"id": "s1", "tool": "t2"},
                    ],
                }
            )

    def test_unknown_dependency(self):
        with pytest.raises(WorkflowValidationError, match="unknown"):
            parse_workflow(
                {
                    "name": "w",
                    "steps": [{"id": "s1", "tool": "t", "depends_on": ["nope"]}],
                }
            )

    def test_cycle_in_parse(self):
        with pytest.raises(WorkflowValidationError, match="[Cc]ycle"):
            parse_workflow(
                {
                    "name": "w",
                    "steps": [
                        {"id": "a", "tool": "t", "depends_on": ["b"]},
                        {"id": "b", "tool": "t", "depends_on": ["a"]},
                    ],
                }
            )

    def test_inputs_and_output(self):
        wf = parse_workflow(
            {
                "name": "w",
                "steps": [{"id": "s1", "tool": "t"}],
                "inputs": {"q": {"type": "string"}},
                "output": "${s1.output}",
            }
        )
        assert "q" in wf.inputs
        assert wf.output == "${s1.output}"


# WorkflowExecutor ───────────────────────────────────────────────────


class TestWorkflowExecutor:
    def _make_workflow(self, **overrides):
        default = {
            "name": "w",
            "steps": [{"id": "s1", "tool": "echo", "args": {"msg": "hi"}}],
        }
        default.update(overrides)
        return parse_workflow(default)

    @pytest.mark.asyncio
    async def test_simple_success(self):
        invoke = AsyncMock(return_value="ok")
        executor = WorkflowExecutor(invoke)
        wf = self._make_workflow()
        results = await executor.execute(wf)
        assert results["s1"].status == StepStatus.COMPLETED
        assert results["s1"].output == "ok"
        invoke.assert_awaited_once_with("echo", {"msg": "hi"})

    @pytest.mark.asyncio
    async def test_interpolation_preserves_type(self):
        """Full-string interpolation ${x.output} preserves the raw type."""
        invoke = AsyncMock(side_effect=[{"list": [1, 2]}, "done"])
        wf = parse_workflow(
            {
                "name": "w",
                "steps": [
                    {"id": "fetch", "tool": "t1"},
                    {
                        "id": "use",
                        "tool": "t2",
                        "depends_on": ["fetch"],
                        "args": {"data": "${fetch.output}"},
                    },
                ],
            }
        )
        executor = WorkflowExecutor(invoke)
        _results = await executor.execute(wf)
        # The second call should receive the raw dict, not a string
        _, call_args = invoke.call_args_list[1]
        assert call_args == {}  # positional args
        positional = invoke.call_args_list[1].args
        assert positional[1]["data"] == {"list": [1, 2]}

    @pytest.mark.asyncio
    async def test_interpolation_partial_string(self):
        """Partial interpolation within a string does string substitution."""
        invoke = AsyncMock(side_effect=["world", "done"])
        wf = parse_workflow(
            {
                "name": "w",
                "steps": [
                    {"id": "greet", "tool": "t1"},
                    {
                        "id": "use",
                        "tool": "t2",
                        "depends_on": ["greet"],
                        "args": {"msg": "hello ${greet.output}!"},
                    },
                ],
            }
        )
        executor = WorkflowExecutor(invoke)
        await executor.execute(wf)
        positional = invoke.call_args_list[1].args
        assert positional[1]["msg"] == "hello world!"

    @pytest.mark.asyncio
    async def test_condition_skip(self):
        """Step with false condition is skipped."""
        invoke = AsyncMock(return_value="ok")
        wf = parse_workflow(
            {
                "name": "w",
                "steps": [
                    {"id": "a", "tool": "t1"},
                    {
                        "id": "b",
                        "tool": "t2",
                        "depends_on": ["a"],
                        "condition": "${a.status} == 'failed'",
                    },
                ],
            }
        )
        executor = WorkflowExecutor(invoke)
        results = await executor.execute(wf)
        assert results["b"].status == StepStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_condition_true(self):
        invoke = AsyncMock(return_value="ok")
        wf = parse_workflow(
            {
                "name": "w",
                "steps": [
                    {"id": "a", "tool": "t1"},
                    {
                        "id": "b",
                        "tool": "t2",
                        "depends_on": ["a"],
                        "condition": "${a.status} == 'completed'",
                    },
                ],
            }
        )
        executor = WorkflowExecutor(invoke)
        results = await executor.execute(wf)
        assert results["b"].status == StepStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_condition_inequality(self):
        invoke = AsyncMock(return_value="ok")
        wf = parse_workflow(
            {
                "name": "w",
                "steps": [
                    {"id": "a", "tool": "t1"},
                    {
                        "id": "b",
                        "tool": "t2",
                        "depends_on": ["a"],
                        "condition": "${a.status} != 'failed'",
                    },
                ],
            }
        )
        executor = WorkflowExecutor(invoke)
        results = await executor.execute(wf)
        assert results["b"].status == StepStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_retry_succeeds_on_second_attempt(self):
        invoke = AsyncMock(side_effect=[RuntimeError("fail"), "ok"])
        wf = parse_workflow(
            {
                "name": "w",
                "steps": [{"id": "s1", "tool": "t", "retry": 1}],
            }
        )
        executor = WorkflowExecutor(invoke)
        results = await executor.execute(wf)
        assert results["s1"].status == StepStatus.COMPLETED
        assert invoke.await_count == 2

    @pytest.mark.asyncio
    async def test_retry_exhausted(self):
        invoke = AsyncMock(side_effect=RuntimeError("fail"))
        wf = parse_workflow(
            {
                "name": "w",
                "steps": [{"id": "s1", "tool": "t", "retry": 2, "on_error": "skip"}],
            }
        )
        executor = WorkflowExecutor(invoke)
        results = await executor.execute(wf)
        assert results["s1"].status == StepStatus.FAILED
        assert invoke.await_count == 3  # 1 + 2 retries

    @pytest.mark.asyncio
    async def test_on_error_fail_returns_failed_result(self):
        """Step with on_error=fail returns FAILED result (exceptions caught internally)."""
        invoke = AsyncMock(side_effect=RuntimeError("boom"))
        wf = parse_workflow(
            {
                "name": "w",
                "steps": [{"id": "s1", "tool": "t", "on_error": "fail"}],
            }
        )
        executor = WorkflowExecutor(invoke)
        # _execute_step catches all exceptions, so no WorkflowExecutionError is raised
        # for a single step. The on_error=fail path in run() only fires when gather
        # catches a BaseException (e.g. SystemExit), which doesn't happen here.
        results = await executor.execute(wf)
        assert results["s1"].status == StepStatus.FAILED
        assert "boom" in results["s1"].error

    @pytest.mark.asyncio
    async def test_on_error_fail_dependency_propagates(self):
        """Downstream step with on_error=fail is FAILED when dependency fails."""
        invoke = AsyncMock(side_effect=RuntimeError("upstream boom"))
        wf = parse_workflow(
            {
                "name": "w",
                "steps": [
                    {"id": "a", "tool": "t"},
                    {"id": "b", "tool": "t", "depends_on": ["a"], "on_error": "fail"},
                ],
            }
        )
        executor = WorkflowExecutor(invoke)
        results = await executor.execute(wf)
        assert results["a"].status == StepStatus.FAILED
        assert results["b"].status == StepStatus.FAILED
        assert "Dependency" in results["b"].error

    @pytest.mark.asyncio
    async def test_on_error_skip_dependency(self):
        """Downstream step with on_error=skip is skipped when dep fails."""
        call_count = 0

        async def _invoke(tool, args):
            nonlocal call_count
            call_count += 1
            if tool == "fail_tool":
                raise RuntimeError("fail")
            return "ok"

        wf = parse_workflow(
            {
                "name": "w",
                "steps": [
                    {"id": "a", "tool": "fail_tool", "on_error": "skip"},
                    {
                        "id": "b",
                        "tool": "ok_tool",
                        "depends_on": ["a"],
                        "on_error": "skip",
                    },
                ],
            }
        )
        executor = WorkflowExecutor(_invoke)
        results = await executor.execute(wf)
        assert results["a"].status == StepStatus.FAILED
        assert results["b"].status == StepStatus.SKIPPED

    @pytest.mark.asyncio
    async def test_parallel_execution(self):
        """Independent steps run in the same level."""
        invoke = AsyncMock(return_value="ok")
        wf = parse_workflow(
            {
                "name": "w",
                "steps": [
                    {"id": "a", "tool": "t"},
                    {"id": "b", "tool": "t"},
                    {"id": "c", "tool": "t", "depends_on": ["a", "b"]},
                ],
            }
        )
        executor = WorkflowExecutor(invoke)
        results = await executor.execute(wf)
        assert all(r.status == StepStatus.COMPLETED for r in results.values())


# CompositeTool ───────────────────────────────────────────────────────


class TestCompositeTool:
    def _make(self, **overrides):
        data = {
            "name": "my-tool",
            "description": "A tool",
            "steps": [{"id": "s1", "tool": "echo"}],
            "inputs": {"query": {"type": "string", "description": "Q"}},
        }
        data.update(overrides)
        wf = parse_workflow(data)
        invoke = AsyncMock(return_value="result")
        return CompositeTool(wf, invoke), invoke

    def test_name(self):
        ct, _ = self._make()
        assert ct.name == "my-tool"

    def test_description_explicit(self):
        ct, _ = self._make()
        assert ct.description == "A tool"

    def test_description_fallback(self):
        ct, _ = self._make(description="")
        assert "Composite workflow" in ct.description

    def test_input_schema_with_inputs(self):
        ct, _ = self._make()
        schema = ct.input_schema
        assert schema["type"] == "object"
        assert "query" in schema["properties"]
        assert "query" in schema.get("required", [])

    def test_input_schema_no_inputs(self):
        ct, _ = self._make(inputs={})
        schema = ct.input_schema
        assert schema["properties"] == {}

    def test_input_schema_non_dict_param(self):
        """If a param def is not a dict, defaults to string type."""
        ct, _ = self._make(inputs={"x": "string"})
        schema = ct.input_schema
        assert schema["properties"]["x"]["type"] == "string"

    def test_input_schema_not_required(self):
        ct, _ = self._make(inputs={"opt": {"type": "string", "required": False}})
        schema = ct.input_schema
        assert "opt" not in schema.get("required", [])

    def test_to_tool_info(self):
        ct, _ = self._make()
        info = ct.to_tool_info()
        assert info["name"] == "my-tool"
        assert "inputSchema" in info
        assert "description" in info

    @pytest.mark.asyncio
    async def test_invoke_returns_output(self):
        ct, invoke = self._make()
        result = await ct.invoke({"query": "test"})
        assert result == "result"

    @pytest.mark.asyncio
    async def test_invoke_with_output_template(self):
        ct, invoke = self._make(output="${s1.output}")
        result = await ct.invoke({})
        assert result == "result"


# load_composite_tools ────────────────────────────────────────────────


class TestLoadCompositeTools:
    def test_valid(self):
        defs = [
            {"name": "t1", "steps": [{"id": "s", "tool": "echo"}]},
            {"name": "t2", "steps": [{"id": "s", "tool": "echo"}]},
        ]
        invoke = AsyncMock()
        tools = load_composite_tools(defs, invoke)
        assert len(tools) == 2
        assert {t.name for t in tools} == {"t1", "t2"}

    def test_invalid_skipped(self):
        """Invalid workflow definitions log a warning and are skipped."""
        defs = [
            {"name": "good", "steps": [{"id": "s", "tool": "t"}]},
            {"steps": []},  # missing name → error
        ]
        invoke = AsyncMock()
        tools = load_composite_tools(defs, invoke)
        assert len(tools) == 1
        assert tools[0].name == "good"

    def test_empty(self):
        tools = load_composite_tools([], AsyncMock())
        assert tools == []
