"""Workflow DAG executor.

Executes workflow steps in topological order, running independent
steps in parallel via ``asyncio.gather()``.

Supports:
- Sequential execution (steps with dependencies)
- Parallel fan-out/fan-in (independent steps)
- Parameter interpolation (``${step_id.output}``)
- Conditional execution (``condition`` field)
- Retry on failure
- Error strategies: fail-fast, skip, continue
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Callable, Coroutine, Dict, Optional

from argus_mcp.workflows.dsl import WorkflowDefinition
from argus_mcp.workflows.steps import Step, StepResult, StepStatus

logger = logging.getLogger(__name__)

# Pattern for interpolation: ${step_id.output} or ${inputs.param}
_INTERPOLATION_RE = re.compile(r"\$\{([a-zA-Z0-9_]+)\.([a-zA-Z0-9_.]+)\}")

# Type for tool invocation callback
ToolInvoker = Callable[[str, Dict[str, Any]], Coroutine[Any, Any, Any]]


class WorkflowExecutionError(Exception):
    """Raised on fatal workflow execution failure."""


class WorkflowExecutor:
    """Execute a :class:`WorkflowDefinition` DAG.

    Parameters
    ----------
    invoke_tool:
        Async callback ``(tool_name, args) -> result`` to call tools.
        In production, this delegates to the bridge routing middleware.
    """

    def __init__(self, invoke_tool: ToolInvoker) -> None:
        self._invoke = invoke_tool

    async def execute(
        self,
        workflow: WorkflowDefinition,
        inputs: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, StepResult]:
        """Run all steps in topological order.

        Parameters
        ----------
        workflow:
            The parsed workflow definition.
        inputs:
            Workflow input parameters.

        Returns
        -------
        dict
            Mapping of step ID → :class:`StepResult`.
        """
        results: Dict[str, StepResult] = {}
        context: Dict[str, Any] = {"inputs": inputs or {}}

        levels = workflow.topological_order()

        for level in levels:
            # Run independent steps in parallel
            tasks = [self._execute_step(step, context, results) for step in level]
            level_results = await asyncio.gather(*tasks, return_exceptions=True)

            for step, result in zip(level, level_results):
                if isinstance(result, BaseException):
                    sr = StepResult(
                        step_id=step.id,
                        status=StepStatus.FAILED,
                        error=str(result),
                    )
                    results[step.id] = sr
                    context[step.id] = {"output": None, "status": "failed", "error": str(result)}

                    if step.on_error == "fail":
                        raise WorkflowExecutionError(f"Step '{step.id}' failed: {result}")
                else:
                    results[step.id] = result
                    context[step.id] = {
                        "output": result.output,
                        "status": result.status.value,
                    }

        return results

    async def _execute_step(
        self,
        step: Step,
        context: Dict[str, Any],
        results: Dict[str, StepResult],
    ) -> StepResult:
        """Execute a single step with retry and condition support."""
        # Check condition
        if step.condition:
            if not self._evaluate_condition(step.condition, context):
                logger.debug("Step '%s' skipped (condition false)", step.id)
                return StepResult(step_id=step.id, status=StepStatus.SKIPPED)

        # Check if dependencies all succeeded
        for dep_id in step.depends_on:
            dep_result = results.get(dep_id)
            if dep_result and dep_result.status == StepStatus.FAILED:
                if step.on_error == "skip":
                    return StepResult(step_id=step.id, status=StepStatus.SKIPPED)
                if step.on_error == "fail":
                    return StepResult(
                        step_id=step.id,
                        status=StepStatus.FAILED,
                        error=f"Dependency '{dep_id}' failed",
                    )

        # Interpolate arguments
        resolved_args = self._interpolate(step.args, context)

        # Execute with retry
        last_error: Optional[str] = None
        attempts = 1 + step.retry

        for attempt in range(attempts):
            start = time.monotonic()
            try:
                output = await self._invoke(step.tool, resolved_args)
                duration = (time.monotonic() - start) * 1000
                logger.debug(
                    "Step '%s' completed (attempt %d/%d, %.1fms)",
                    step.id,
                    attempt + 1,
                    attempts,
                    duration,
                )
                return StepResult(
                    step_id=step.id,
                    status=StepStatus.COMPLETED,
                    output=output,
                    duration_ms=duration,
                )
            except Exception as exc:
                last_error = str(exc)
                duration = (time.monotonic() - start) * 1000
                logger.warning(
                    "Step '%s' attempt %d/%d failed (%.1fms): %s",
                    step.id,
                    attempt + 1,
                    attempts,
                    duration,
                    exc,
                )

        return StepResult(
            step_id=step.id,
            status=StepStatus.FAILED,
            error=last_error,
        )

    def _interpolate(self, args: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """Replace ``${ref.path}`` tokens in argument values."""
        resolved: Dict[str, Any] = {}
        for key, value in args.items():
            if isinstance(value, str):
                resolved[key] = self._interpolate_string(value, context)
            elif isinstance(value, dict):
                resolved[key] = self._interpolate(value, context)
            elif isinstance(value, list):
                resolved[key] = [
                    self._interpolate_string(v, context) if isinstance(v, str) else v for v in value
                ]
            else:
                resolved[key] = value
        return resolved

    def _interpolate_string(self, value: str, context: Dict[str, Any]) -> Any:
        """Replace interpolation tokens in a string value.

        If the entire string is a single ``${ref.path}`` and the resolved
        value is non-string, return the raw value (preserves types).
        """
        # Check for full-string interpolation (return raw value to preserve type)
        match = _INTERPOLATION_RE.fullmatch(value)
        if match:
            resolved = self._resolve_ref(match.group(1), match.group(2), context)
            if resolved is not None:
                return resolved

        # Partial interpolation within a larger string
        def _replacer(m: re.Match) -> str:
            resolved = self._resolve_ref(m.group(1), m.group(2), context)
            return str(resolved) if resolved is not None else m.group(0)

        return _INTERPOLATION_RE.sub(_replacer, value)

    def _resolve_ref(self, scope: str, path: str, context: Dict[str, Any]) -> Any:
        """Resolve a dotted reference like ``step_id.output``."""
        obj = context.get(scope)
        if obj is None:
            return None
        for part in path.split("."):
            if isinstance(obj, dict):
                obj = obj.get(part)
            else:
                return None
        return obj

    def _evaluate_condition(self, condition: str, context: Dict[str, Any]) -> bool:
        """Evaluate a simple condition expression.

        Supports: ``${ref.path} == 'value'``, ``${ref.path} != 'value'``,
        and bare ``${ref.path}`` (truthy check).
        """
        # Simple equality: ${step.status} == 'completed'
        eq_match = re.match(
            r"\$\{([a-zA-Z0-9_]+)\.([a-zA-Z0-9_.]+)\}\s*==\s*'([^']*)'",
            condition,
        )
        if eq_match:
            val = self._resolve_ref(eq_match.group(1), eq_match.group(2), context)
            return str(val) == eq_match.group(3)

        # Inequality
        neq_match = re.match(
            r"\$\{([a-zA-Z0-9_]+)\.([a-zA-Z0-9_.]+)\}\s*!=\s*'([^']*)'",
            condition,
        )
        if neq_match:
            val = self._resolve_ref(neq_match.group(1), neq_match.group(2), context)
            return str(val) != neq_match.group(3)

        # Bare reference: truthy check
        bare = _INTERPOLATION_RE.match(condition)
        if bare:
            val = self._resolve_ref(bare.group(1), bare.group(2), context)
            return bool(val)

        # Default: treat non-empty string as truthy
        return bool(condition.strip())
