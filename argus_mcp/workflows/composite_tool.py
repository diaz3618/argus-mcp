"""Composite tool — expose a workflow as a single MCP tool.

A composite tool appears in ``list_tools`` like any regular tool.
When invoked, it runs the underlying workflow DAG and returns
the final output.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from argus_mcp.workflows.dsl import WorkflowDefinition
from argus_mcp.workflows.executor import ToolInvoker, WorkflowExecutor

logger = logging.getLogger(__name__)


class CompositeTool:
    """Wraps a :class:`WorkflowDefinition` as an MCP tool descriptor.

    Attributes
    ----------
    name:
        Tool name exposed to clients.
    description:
        Tool description.
    input_schema:
        JSON Schema derived from workflow inputs.
    """

    def __init__(
        self,
        workflow: WorkflowDefinition,
        invoke_tool: ToolInvoker,
    ) -> None:
        self._workflow = workflow
        self._executor = WorkflowExecutor(invoke_tool)

    @property
    def name(self) -> str:
        return self._workflow.name

    @property
    def description(self) -> str:
        return self._workflow.description or f"Composite workflow: {self.name}"

    @property
    def input_schema(self) -> Dict[str, Any]:
        """Build a JSON Schema from workflow inputs."""
        if not self._workflow.inputs:
            return {"type": "object", "properties": {}}

        properties: Dict[str, Any] = {}
        required: List[str] = []

        for param_name, param_def in self._workflow.inputs.items():
            if isinstance(param_def, dict):
                properties[param_name] = {
                    "type": param_def.get("type", "string"),
                    "description": param_def.get("description", ""),
                }
                if param_def.get("required", True):
                    required.append(param_name)
            else:
                properties[param_name] = {"type": "string"}

        schema: Dict[str, Any] = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required
        return schema

    async def invoke(self, arguments: Optional[Dict[str, Any]] = None) -> Any:
        """Execute the workflow and return the final output.

        Returns the output template resolved against step results,
        or the last step's output if no template is set.
        """
        results = await self._executor.execute(self._workflow, inputs=arguments)

        # Resolve output template
        if self._workflow.output:
            context = {
                sid: {"output": r.output, "status": r.status.value} for sid, r in results.items()
            }
            context["inputs"] = arguments or {}
            return self._executor._interpolate_string(self._workflow.output, context)

        # Default: return last step's output
        if self._workflow.steps:
            last_id = self._workflow.steps[-1].id
            last_result = results.get(last_id)
            if last_result:
                return last_result.output

        return None

    def to_tool_info(self) -> Dict[str, Any]:
        """Return MCP tool info dict for ``list_tools``."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }


def load_composite_tools(
    workflow_defs: List[Dict[str, Any]],
    invoke_tool: ToolInvoker,
) -> List[CompositeTool]:
    """Parse workflow definitions and return composite tools."""
    from argus_mcp.workflows.dsl import WorkflowValidationError, parse_workflow

    tools: List[CompositeTool] = []
    for wf_data in workflow_defs:
        try:
            wf = parse_workflow(wf_data)
            tools.append(CompositeTool(wf, invoke_tool))
            logger.info("Composite tool '%s' loaded (%d steps)", wf.name, len(wf.steps))
        except (KeyError, ValueError, TypeError, WorkflowValidationError) as exc:
            logger.warning("Failed to load composite workflow: %s", exc)
    return tools
