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

# Belt-and-suspenders: verify templates were included in the wheel.
# If this fires, the wheel was built without package-data — see
# pyproject.toml [tool.setuptools.package-data] and MANIFEST.in.
_REQUIRED_TEMPLATES = (
    "uvx.dockerfile.j2",
    "npx.dockerfile.j2",
    "go.dockerfile.j2",
    "source.dockerfile.j2",
)

_missing = [t for t in _REQUIRED_TEMPLATES if not os.path.isfile(os.path.join(_TEMPLATE_DIR, t))]
if _missing:
    raise FileNotFoundError(
        f"Required Dockerfile templates missing from installed package: {_missing}. "
        f"Template directory: {_TEMPLATE_DIR}. "
        "This indicates the wheel was built without package-data. "
        "Reinstall from a correctly built wheel or from source."
    )

# Autoescape is intentionally disabled: these templates generate
# Dockerfiles (plain text), not HTML.  Enabling autoescape would
# corrupt shell commands and file paths with HTML entities.
# Using select_autoescape with default_for_string=False explicitly
# documents that no HTML escaping is needed (satisfies Bandit B701).
_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(_TEMPLATE_DIR),
    undefined=jinja2.StrictUndefined,
    autoescape=jinja2.select_autoescape(
        default_for_string=False,
        default=False,
    ),
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


def check_templates() -> Dict[str, Any]:
    """Verify all required Dockerfile templates are present.

    Returns a dict with keys:

    - ``ok`` (bool) — True if all templates found
    - ``template_dir`` (str) — absolute path to the template directory
    - ``found`` (list[str]) — template filenames that exist
    - ``missing`` (list[str]) — template filenames that are missing
    - ``expected_count`` (int) — total templates expected

    Intended for CI verification scripts and diagnostics.
    """
    found = [t for t in _REQUIRED_TEMPLATES if os.path.isfile(os.path.join(_TEMPLATE_DIR, t))]
    missing = [t for t in _REQUIRED_TEMPLATES if t not in found]
    return {
        "ok": len(missing) == 0,
        "template_dir": _TEMPLATE_DIR,
        "found": found,
        "missing": missing,
        "expected_count": len(_REQUIRED_TEMPLATES),
    }
