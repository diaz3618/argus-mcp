"""Jinja2 template engine for Dockerfile generation.

Loads ``.j2`` template files from this package directory and renders
them with strict undefined handling — any template variable that is
missing from the context will raise immediately rather than producing
a broken Dockerfile.
"""

from __future__ import annotations

import os
from typing import Any, Dict

import jinja2

from argus_mcp.bridge.container.templates.models import (
    CONTAINER_HOME,
    CONTAINER_UID,
    CONTAINER_USER,
)

_TEMPLATE_DIR = os.path.dirname(__file__)

# Autoescape is intentionally disabled: these templates generate
# Dockerfiles (plain text), not HTML.  Enabling autoescape would
# corrupt shell commands and file paths with HTML entities.
_env = jinja2.Environment(  # nosec B701
    loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
    undefined=jinja2.StrictUndefined,
    keep_trailing_newline=True,
    trim_blocks=True,
    lstrip_blocks=True,
)

# Default template variables for container identity — injected into every
# render so callers don't need to repeat them.  Explicit context values
# always win (dict merge gives caller priority).
_IDENTITY_DEFAULTS: Dict[str, Any] = {
    "container_uid": CONTAINER_UID,
    "container_user": CONTAINER_USER,
    "container_home": CONTAINER_HOME,
}


def render_template(template_name: str, context: Dict[str, Any]) -> str:
    """Render a Dockerfile Jinja2 template.

    Parameters
    ----------
    template_name:
        The template filename relative to this package directory
        (e.g. ``"uvx.dockerfile.j2"``).
    context:
        A dict of template variables.  Must contain all variables
        referenced in the template — ``StrictUndefined`` is enabled.

    Returns
    -------
    str
        The rendered Dockerfile content.
    """
    tmpl = _env.get_template(template_name)
    merged = {**_IDENTITY_DEFAULTS, **context}
    return tmpl.render(merged)
