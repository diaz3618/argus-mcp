"""Workflow DSL — YAML → DAG parser and validator.

Parses workflow definitions from YAML or dict format, validates
the DAG structure (acyclicity, valid references), and produces a
:class:`WorkflowDefinition` ready for execution.

Example workflow YAML::

    name: my-pipeline
    description: Fetch and transform data
    inputs:
      query:
        type: string
        description: SQL query to run
    steps:
      - id: fetch
        tool: db.query
        args:
          sql: "${inputs.query}"
      - id: transform
        tool: transform.json
        depends_on: [fetch]
        args:
          data: "${fetch.output}"
    output: "${transform.output}"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Set

from argus_mcp.workflows.steps import Step

logger = logging.getLogger(__name__)


class WorkflowValidationError(Exception):
    """Raised when a workflow definition is invalid."""


@dataclass
class WorkflowDefinition:
    """Parsed and validated workflow DAG.

    Attributes
    ----------
    name:
        Workflow name (used as composite tool name).
    description:
        Human-readable description.
    steps:
        Ordered list of workflow steps.
    inputs:
        Input parameter schema (JSON-Schema-like dict).
    output:
        Output template referencing step outputs.
    """

    name: str
    description: str = ""
    steps: List[Step] = field(default_factory=list)
    inputs: Dict[str, Any] = field(default_factory=dict)
    output: str = ""

    def topological_order(self) -> List[List[Step]]:
        """Return steps grouped by execution level (parallel within level).

        Steps with no unresolved dependencies go in the first level,
        steps whose dependencies are all in earlier levels go next, etc.

        Raises :class:`WorkflowValidationError` if cycles are detected.
        """
        step_map = {s.id: s for s in self.steps}
        remaining = set(step_map.keys())
        completed: Set[str] = set()
        levels: List[List[Step]] = []

        while remaining:
            # Find steps whose dependencies are all completed
            ready = [
                sid
                for sid in remaining
                if all(dep in completed for dep in step_map[sid].depends_on)
            ]
            if not ready:
                raise WorkflowValidationError(
                    f"Cycle detected in workflow '{self.name}'. Unresolvable steps: {remaining}"
                )
            levels.append([step_map[sid] for sid in ready])
            completed.update(ready)
            remaining -= set(ready)

        return levels


def parse_workflow(data: Dict[str, Any]) -> WorkflowDefinition:
    """Parse a workflow definition from a dict (loaded from YAML/JSON).

    Validates:
    - Required fields (name, steps)
    - Step IDs are unique
    - ``depends_on`` references exist
    - DAG is acyclic

    Raises :class:`WorkflowValidationError` on invalid input.
    """
    name = data.get("name")
    if not name:
        raise WorkflowValidationError("Workflow must have a 'name' field")

    raw_steps = data.get("steps", [])
    if not raw_steps:
        raise WorkflowValidationError(f"Workflow '{name}' has no steps")

    steps: List[Step] = []
    seen_ids: Set[str] = set()

    for raw in raw_steps:
        if "id" not in raw:
            raise WorkflowValidationError(f"Step missing 'id' in workflow '{name}': {raw}")
        step = Step.from_dict(raw)
        if step.id in seen_ids:
            raise WorkflowValidationError(f"Duplicate step ID '{step.id}' in workflow '{name}'")
        seen_ids.add(step.id)
        steps.append(step)

    for step in steps:
        for dep in step.depends_on:
            if dep not in seen_ids:
                raise WorkflowValidationError(
                    f"Step '{step.id}' depends on unknown step '{dep}' in workflow '{name}'"
                )

    wf = WorkflowDefinition(
        name=name,
        description=data.get("description", ""),
        steps=steps,
        inputs=data.get("inputs", {}),
        output=data.get("output", ""),
    )

    wf.topological_order()

    return wf


def load_workflow_yaml(path: str) -> WorkflowDefinition:
    """Load a workflow from a YAML file.

    Requires ``pyyaml``.
    """
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("pyyaml is required for YAML workflows: pip install pyyaml") from exc

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise WorkflowValidationError(f"Workflow file must be a YAML mapping: {path}")

    return parse_workflow(data)
