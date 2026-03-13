"""Typed data models for Dockerfile template rendering.

Models
------
``RuntimeConfig``
    Per-transport builder image and additional system packages.
    Each transport type (uvx, npx) has sensible defaults that can
    be overridden via config.

``TemplateData``
    Complete typed contract between the configuration layer and the
    Jinja2 Dockerfile templates.  Every field used by the templates
    is explicitly declared here — no raw ``**kwargs`` or untyped dicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

#
# Industry-standard UID used by Google distroless and Chainguard images.
# Using a well-known UID (rather than an arbitrary one like 10001) makes
# Argus-built images compatible with Kubernetes ``runAsNonRoot`` policies
# and clearly signals "intentionally non-root" to security scanners.
#
# These constants are the **single source of truth** consumed by both
# the Jinja2 templates (via ``TemplateData`` defaults) and the container
# wrapper (``wrapper.py``) at runtime.

CONTAINER_UID: int = 65532
"""Non-root user ID — matches the ``nonroot`` user in distroless images."""

CONTAINER_USER: str = "nonroot"
"""Non-root username created in all Argus-built container images."""

CONTAINER_HOME: str = "/home/nonroot"
"""Home directory for the container user."""

RUNTIME_DEFAULTS: Dict[str, Dict[str, object]] = {
    "uvx": {
        "builder_image": "python:3.13-slim",
        "additional_packages": ["ca-certificates", "git"],
    },
    "npx": {
        "builder_image": "node:22-alpine",
        "additional_packages": ["ca-certificates", "git"],
    },
    "go": {
        "builder_image": "golang:1.24-alpine",
        "additional_packages": ["ca-certificates", "git"],
    },
}


@dataclass
class RuntimeConfig:
    """Per-transport runtime configuration.

    Controls the base Docker image and any additional system packages
    that must be installed in the image (beyond ``system_deps`` from
    the backend config).
    """

    builder_image: str = ""
    additional_packages: List[str] = field(default_factory=list)

    @classmethod
    def for_transport(
        cls,
        transport: str,
        *,
        overrides: Optional[Dict[str, object]] = None,
    ) -> RuntimeConfig:
        """Create a ``RuntimeConfig`` with defaults for the transport.

        Parameters
        ----------
        transport:
            Transport type key (``"uvx"`` or ``"npx"``).
        overrides:
            Optional dict with ``"builder_image"`` and/or
            ``"additional_packages"`` to override defaults.
        """
        defaults = RUNTIME_DEFAULTS.get(transport, {})
        raw_pkgs = defaults.get("additional_packages", [])
        config = cls(
            builder_image=str(defaults.get("builder_image", "")),
            additional_packages=list(raw_pkgs) if isinstance(raw_pkgs, list) else [],
        )
        if overrides:
            if overrides.get("builder_image"):
                config.builder_image = str(overrides["builder_image"])
            extra_pkgs = overrides.get("additional_packages")
            if extra_pkgs and isinstance(extra_pkgs, list):
                config.additional_packages = list(extra_pkgs)
        return config


@dataclass
class TemplateData:
    """Typed data model passed to Jinja2 Dockerfile templates.

    Every field consumed by the ``.j2`` templates is explicitly
    declared.  This is the single contract between the configuration
    layer (``schema_backends.py``) and the rendering engine.

    Fields
    ------
    package : str
        The full package specifier (e.g. ``"mcp-server-analyzer"``,
        ``"snyk@latest"``).
    package_clean : str
        Package name stripped of version (e.g. ``"snyk"``).
    binary : str
        The entrypoint binary name for ``ENTRYPOINT``.
    builder_image : str
        Base Docker image for the builder stage.
    is_alpine : bool
        Whether the builder image is Alpine-based (determines
        ``apk`` vs ``apt-get`` for system package installation).
    install_cmd : str
        The package install command (``uv tool install ...`` or
        ``npm install --save ...``).
    system_deps : list[str]
        System packages from per-backend ``container.system_deps``
        config (e.g. ``["ripgrep"]``).
    build_env : dict[str, str]
        Build-time environment variables.
    additional_packages : list[str]
        Extra system packages from ``RuntimeConfig``.
    bin_name : str
        NPX-specific: heuristic binary name for the discovery step.
    """

    package: str
    package_clean: str
    binary: str
    builder_image: str
    is_alpine: bool = False
    install_cmd: str = ""
    system_deps: List[str] = field(default_factory=list)
    build_env: Dict[str, str] = field(default_factory=dict)
    additional_packages: List[str] = field(default_factory=list)
    bin_name: str = ""
    go_package: str = ""
    go_package_clean: str = ""
    runtime_args: List[str] = field(default_factory=list)

    # Container user — defaults match the module-level constants.
    # These are injected into Jinja2 templates so that UID/user/home
    # are parameterised rather than hardcoded in template files.
    container_uid: int = CONTAINER_UID
    container_user: str = CONTAINER_USER
    container_home: str = CONTAINER_HOME

    def __post_init__(self) -> None:
        self.is_alpine = "alpine" in self.builder_image.lower()
