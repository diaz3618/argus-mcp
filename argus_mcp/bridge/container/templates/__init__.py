"""Dockerfile template generation for MCP server images.

This package generates multi-stage Dockerfiles following industry best
practices, using Jinja2 templates with typed data models and input
validation.

Architecture
---------------------------------------------------
- **Typed models** (``models.py``) — ``TemplateData`` and
  ``RuntimeConfig`` provide a strict contract between config and
  templates.  No raw ``**kwargs`` or untyped dicts.
- **Input validation** (``validation.py``) — all user-supplied values
  (package names, system deps, build env) are validated before reaching
  the templates.  Prevents shell/command injection.
- **Jinja2 templates** (``.j2`` files) — Dockerfiles are rendered from
  template files with ``StrictUndefined`` — missing variables raise
  immediately rather than producing broken Dockerfiles.
- **Template engine** (``engine.py``) — thin Jinja2 wrapper with
  ``FileSystemLoader`` pointing at this package directory.

Supported transports
~~~~~~~~~~~~~~~~~~~~
``uvx``
    Python packages installed via ``uv tool install``.
    Default image: ``python:3.13-slim``.

``npx``
    Node.js packages installed via ``npm install --save``.
    Default image: ``node:22-alpine``.

``go``
    Go packages compiled from source via ``go install``.
    Default image: ``golang:1.24-alpine``.
"""

from argus_mcp.bridge.container.templates._generators import (
    IMAGE_PREFIX,
    compute_image_tag,
    generate_go_dockerfile,
    generate_npx_dockerfile,
    generate_source_dockerfile,
    generate_uvx_dockerfile,
    is_vcs_specifier,
    parse_go_args,
    parse_npx_args,
    parse_uvx_args,
)
from argus_mcp.bridge.container.templates.engine import render_template
from argus_mcp.bridge.container.templates.models import (
    CONTAINER_HOME,
    CONTAINER_UID,
    CONTAINER_USER,
    RUNTIME_DEFAULTS,
    RuntimeConfig,
    TemplateData,
)
from argus_mcp.bridge.container.templates.validation import (
    ValidationError,
    validate_build_env_key,
    validate_build_env_value,
    validate_package_name,
    validate_system_deps,
)

__all__ = [
    # Container user constants
    "CONTAINER_UID",
    "CONTAINER_USER",
    "CONTAINER_HOME",
    # Models
    "RuntimeConfig",
    "TemplateData",
    "RUNTIME_DEFAULTS",
    # Validation
    "ValidationError",
    "validate_package_name",
    "validate_system_deps",
    "validate_build_env_key",
    "validate_build_env_value",
    # Engine
    "render_template",
    # Generators (public API — backwards compatible)
    "parse_uvx_args",
    "parse_npx_args",
    "parse_go_args",
    "generate_uvx_dockerfile",
    "generate_npx_dockerfile",
    "generate_go_dockerfile",
    "generate_source_dockerfile",
    "compute_image_tag",
    "is_vcs_specifier",
    "IMAGE_PREFIX",
]
