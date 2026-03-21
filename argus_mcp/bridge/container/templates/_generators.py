"""Dockerfile generators using the Jinja2 template engine.

Refactored from the original ``templates.py`` string-interpolation
approach.  The public API is preserved — ``generate_uvx_dockerfile()``,
``generate_npx_dockerfile()``, and ``generate_go_dockerfile()`` build
typed ``TemplateData`` and render Jinja2 templates.

This module also contains the argument-parsing functions
(``parse_uvx_args``, ``parse_npx_args``, ``parse_go_args``), helper
utilities, and ``compute_image_tag``.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import asdict
from typing import Dict, List, Optional, Tuple

from argus_mcp.bridge.container.templates.engine import render_template
from argus_mcp.bridge.container.templates.models import (
    RuntimeConfig,
    TemplateData,
)
from argus_mcp.bridge.container.templates.validation import (
    validate_build_env_key,
    validate_build_env_value,
    validate_package_name,
    validate_system_deps,
)
from argus_mcp.constants import SHORT_ID_LENGTH

logger = logging.getLogger(__name__)

IMAGE_PREFIX = "arguslocal"


def parse_uvx_args(args: List[str]) -> Tuple[str, str, List[str]]:
    """Parse ``uvx`` arguments into (package, binary, runtime_args).

    Examples::

        ["mcp-server-analyzer"]
        → ("mcp-server-analyzer", "mcp-server-analyzer", [])

        ["--from", "mcpdoc", "mcpdoc", "--urls", "..."]
        → ("mcpdoc", "mcpdoc", ["--urls", "..."])

        ["mcp-server-foo@1.2.0"]
        → ("mcp-server-foo@1.2.0", "mcp-server-foo", [])

        ["python-lsp-mcp@latest"]
        → ("python-lsp-mcp@latest", "python-lsp-mcp", [])
    """
    remaining = list(args)
    package: Optional[str] = None
    binary: Optional[str] = None

    # Handle `--from PACKAGE BINARY` pattern
    if "--from" in remaining:
        idx = remaining.index("--from")
        if idx + 2 < len(remaining):
            package = remaining[idx + 1]
            binary = remaining[idx + 2]
            remaining = remaining[:idx] + remaining[idx + 3 :]
        elif idx + 1 < len(remaining):
            package = remaining[idx + 1]
            remaining = remaining[:idx] + remaining[idx + 2 :]

    # Skip known uvx flags — only strip flags that belong to the ``uvx``
    # tool runner itself.  Any unknown flag (e.g. ``--urls``, ``--yaml``,
    # ``--transport``) is a **tool argument** meant for the package binary
    # and must be preserved in ``remaining`` → ``runtime_args``.
    uvx_flags_standalone = {"--force", "--reinstall"}
    uvx_flags_with_value = {"--python", "--with", "--index-url"}
    uvx_flags = uvx_flags_standalone | uvx_flags_with_value
    while remaining and remaining[0] in uvx_flags:
        flag = remaining.pop(0)
        # Flags that take a value
        if flag in uvx_flags_with_value and remaining:
            remaining.pop(0)

    # First positional arg is the package (or binary if --from was used)
    if not package and remaining:
        package = remaining.pop(0)

    if not binary and package:
        binary = _strip_version(package)

    if not package:
        package = "unknown"
    if not binary:
        binary = _strip_version(package)

    return package, binary, remaining


def parse_npx_args(args: List[str]) -> Tuple[str, List[str], bool]:
    """Parse ``npx`` arguments into (package, runtime_args, is_vcs).

    Examples::

        ["-y", "@upstash/context7-mcp", "--api-key", "xxx"]
        → ("@upstash/context7-mcp", ["--api-key", "xxx"], False)

        ["-y", "mcp-remote", "https://developers.openai.com/mcp"]
        → ("mcp-remote", ["https://developers.openai.com/mcp"], False)

        ["-y", "@modelcontextprotocol/server-sequential-thinking"]
        → ("@modelcontextprotocol/server-sequential-thinking", [], False)

        ["-y", "snyk@latest", "mcp", "-t", "stdio"]
        → ("snyk@latest", ["mcp", "-t", "stdio"], False)

        ["-y", "github:owner/repo"]
        → ("github:owner/repo", [], True)

    The third element ``is_vcs`` is ``True`` when the package specifier
    is a VCS reference (``github:``, ``git+https://``, etc.) which needs
    ``git`` to be available at ``npm install`` time.
    """
    remaining = list(args)

    # Strip npx flags
    npx_flags = {"-y", "--yes", "-q", "--quiet"}
    while remaining and remaining[0] in npx_flags:
        remaining.pop(0)

    # First positional arg is the package
    package = remaining.pop(0) if remaining else "unknown"

    return package, remaining, is_vcs_specifier(package)


def parse_go_args(
    args: List[str],
    *,
    go_package: Optional[str] = None,
) -> Tuple[str, List[str]]:
    """Parse arguments for a Go MCP server.

    Go MCP servers are pre-compiled binaries.  For container isolation,
    we build from source using ``go install`` with the Go module path.

    Parameters
    ----------
    args:
        Original command args (passed through as runtime args).
    go_package:
        Explicit Go module import path (e.g.
        ``"github.com/strowk/mcp-k8s-go"``).  **Required** for Go
        transport container builds.

    Returns
    -------
    (go_module_path, runtime_args)
        The Go module path for ``go install``, and any runtime arguments.

    Raises
    ------
    ValueError
        If ``go_package`` is not provided.
    """
    if not go_package or not go_package.strip():
        raise ValueError(
            "Go transport requires 'go_package' in the container config "
            "(the Go module import path for building from source)."
        )
    return go_package.strip(), list(args)


def is_vcs_specifier(name: str) -> bool:
    """Detect whether a package specifier is a VCS (git) reference.

    Recognised forms::

        github:owner/repo
        github:owner/repo#branch
        bitbucket:owner/repo
        gitlab:owner/repo
        git+https://github.com/owner/repo.git
        git+ssh://git@github.com/owner/repo.git

    Returns ``True`` if the specifier requires ``git`` at install time.
    """
    if not name:
        return False
    lower = name.lower()
    return (
        lower.startswith("github:")
        or lower.startswith("bitbucket:")
        or lower.startswith("gitlab:")
        or lower.startswith("git+https://")
        or lower.startswith("git+ssh://")
        or lower.startswith("git://")
    )


def _vcs_repo_name(specifier: str) -> str:
    """Extract the repository name from a VCS specifier.

    Examples::

        "github:owner/repo"              → "repo"
        "github:owner/repo#branch"       → "repo"
        "bitbucket:owner/repo"           → "repo"
        "git+https://github.com/o/r.git" → "r"
        "git+ssh://git@github.com/o/r"   → "r"
    """
    # Strip fragment (branch/tag/commit after #)
    name = specifier.split("#", 1)[0]

    # For shorthand forms: github:owner/repo, bitbucket:owner/repo, gitlab:owner/repo
    for prefix in ("github:", "bitbucket:", "gitlab:"):
        if name.lower().startswith(prefix):
            path = name[len(prefix) :]
            repo = path.rsplit("/", 1)[-1] if "/" in path else path
            return repo.removesuffix(".git")

    # For URL forms: git+https://..., git+ssh://..., git://...
    # Strip the scheme
    if "://" in name:
        path = name.split("://", 1)[1]
        # Remove user@host prefix for ssh
        if "@" in path.split("/")[0]:
            path = path.split("@", 1)[1]
        repo = path.rstrip("/").rsplit("/", 1)[-1]
        return repo.removesuffix(".git")

    return name


def _strip_version(name: str) -> str:
    """Strip version suffix from a package name.

    Handles scoped packages: ``@org/pkg@1.0.0`` → ``@org/pkg``.
    Handles plain packages: ``pkg@1.2.3`` → ``pkg``.
    Handles ``@latest``: ``pkg@latest`` → ``pkg``.
    VCS specifiers are returned as-is (no ``@version`` to strip).
    """
    if not name:
        return name

    # VCS specifiers don't have @version semantics
    if is_vcs_specifier(name):
        return name

    parts = name.split("@")
    if len(parts) <= 1:
        return name

    # Scoped package: @org/pkg or @org/pkg@version
    if name.startswith("@"):
        if len(parts) == 2:
            # @org/pkg (no version)
            return name
        # @org/pkg@version → @org/pkg
        return "@" + parts[1]

    # Unscoped: pkg@version → pkg
    return parts[0]


def _sanitize_image_name(name: str) -> str:
    """Sanitize a package name for use as a Docker image tag component.

    Converts scoped packages like ``@upstash/context7-mcp`` to
    ``upstash-context7-mcp``.
    """
    sanitized = name.lstrip("@")
    sanitized = re.sub(r"[^a-zA-Z0-9._-]", "-", sanitized)
    return sanitized.lower().strip("-")


def _npm_bin_name(clean_name: str) -> str:
    """Derive the expected binary name from an npm package name.

    Scoped packages ``@org/name`` → ``name``.
    Plain packages ``name`` → ``name``.
    VCS specifiers ``github:owner/repo`` → ``repo``.

    Examples::

        "@upstash/context7-mcp"   → "context7-mcp"
        "@diazstg/memory-bank-mcp" → "memory-bank-mcp"
        "mcp-ripgrep"              → "mcp-ripgrep"
        "snyk"                     → "snyk"
        "github:owner/repo"       → "repo"
    """
    if is_vcs_specifier(clean_name):
        return _vcs_repo_name(clean_name)
    if clean_name.startswith("@") and "/" in clean_name:
        return clean_name.split("/", 1)[1]
    return clean_name


def _compute_uvx_install_cmd(package: str) -> str:
    """Compute the ``uv tool install`` command for a uvx package.

    Handles version specifiers: ``@version`` becomes ``==version``
    for ``uv``, while ``@latest`` is stripped.
    """
    if "@" in package and not package.startswith("@"):
        pkg_name, ver = package.rsplit("@", 1)
        if ver != "latest":
            return f"uv tool install '{pkg_name}=={ver}'"
        return f"uv tool install {pkg_name}"
    return f"uv tool install {package}"


def _strip_go_version(module_path: str) -> str:
    """Strip version suffix from a Go module path.

    Handles: ``github.com/foo/bar@v1.2.3`` → ``github.com/foo/bar``.
    Handles: ``github.com/foo/bar@latest`` → ``github.com/foo/bar``.
    No-op if no ``@`` version: ``github.com/foo/bar`` → ``github.com/foo/bar``.
    """
    if "@" in module_path:
        return module_path.rsplit("@", 1)[0]
    return module_path


def _validate_build_inputs(
    package: str,
    build_env: Optional[Dict[str, str]],
    system_deps: Optional[List[str]],
) -> Tuple[str, Dict[str, str], List[str]]:
    """Validate and normalise common Dockerfile generation inputs."""
    package = validate_package_name(package)
    validated_deps = validate_system_deps(system_deps or [])
    validated_env: Dict[str, str] = {}
    if build_env:
        for k, v in build_env.items():
            validate_build_env_key(k)
            validate_build_env_value(v)
            validated_env[k] = v
    return package, validated_env, validated_deps


def generate_uvx_dockerfile(
    package: str,
    binary: str,
    *,
    builder_image: Optional[str] = None,
    build_env: Optional[Dict[str, str]] = None,
    system_deps: Optional[List[str]] = None,
    build_system_deps: Optional[List[str]] = None,
    runtime_config: Optional[RuntimeConfig] = None,
) -> str:
    """Generate a multi-stage Dockerfile for a ``uvx`` package.

    The builder stage installs ``uv`` and the package into
    ``/opt/uv-tools``.  The runtime stage copies only the installed
    tool directory and runs as a non-root user.

    Parameters
    ----------
    package:
        The package specifier (e.g. ``"mcp-server-analyzer"``).
    binary:
        The entrypoint binary name.
    builder_image:
        Override for the base Docker image.  When ``None``, uses
        the default from ``RuntimeConfig``.
    build_env:
        Build-time environment variables.
    system_deps:
        System packages to install in the runtime stage.
    build_system_deps:
        System packages to install only in the builder stage.
    runtime_config:
        Per-transport runtime configuration.  When ``None``, uses
        defaults for the ``"uvx"`` transport.
    """
    # Resolve runtime config
    rc = runtime_config or RuntimeConfig.for_transport("uvx")
    image = builder_image or rc.builder_image

    package, validated_env, validated_deps = _validate_build_inputs(package, build_env, system_deps)
    validated_build_deps = validate_system_deps(build_system_deps or [])

    # Build typed template data
    data = TemplateData(
        package=package,
        package_clean=_strip_version(package),
        binary=binary,
        builder_image=image,
        install_cmd=_compute_uvx_install_cmd(package),
        system_deps=validated_deps,
        build_system_deps=validated_build_deps,
        build_env=validated_env,
        additional_packages=rc.additional_packages,
    )

    return render_template("uvx.dockerfile.j2", asdict(data))


def generate_npx_dockerfile(
    package: str,
    *,
    builder_image: Optional[str] = None,
    build_env: Optional[Dict[str, str]] = None,
    system_deps: Optional[List[str]] = None,
    build_system_deps: Optional[List[str]] = None,
    runtime_config: Optional[RuntimeConfig] = None,
) -> str:
    """Generate a multi-stage Dockerfile for an ``npx`` package.

    The builder stage runs ``npm install --save`` to fetch the package
    and all its dependencies.  A discovery step reads the package's
    ``package.json`` ``bin`` field to determine the correct binary name.

    Parameters
    ----------
    package:
        The package specifier (e.g. ``"@upstash/context7-mcp"``).
    builder_image:
        Override for the base Docker image.
    build_env:
        Build-time environment variables.
    system_deps:
        System packages to install in the runtime stage.
    build_system_deps:
        System packages to install only in the builder stage
        (e.g. ``["git"]`` for VCS npm specifiers).
    runtime_config:
        Per-transport runtime configuration.
    """
    # Resolve runtime config
    rc = runtime_config or RuntimeConfig.for_transport("npx")
    image = builder_image or rc.builder_image

    package, validated_env, validated_deps = _validate_build_inputs(package, build_env, system_deps)
    validated_build_deps = validate_system_deps(build_system_deps or [])

    clean_name = _strip_version(package)
    bin_name = _npm_bin_name(clean_name)

    # Build typed template data
    data = TemplateData(
        package=package,
        package_clean=clean_name,
        binary="__argus_entry",  # determined at build time
        builder_image=image,
        install_cmd=f"npm install --save {package}",
        system_deps=validated_deps,
        build_system_deps=validated_build_deps,
        build_env=validated_env,
        additional_packages=rc.additional_packages,
        bin_name=bin_name,
    )

    return render_template("npx.dockerfile.j2", asdict(data))


def generate_go_dockerfile(
    go_package: str,
    *,
    builder_image: Optional[str] = None,
    build_env: Optional[Dict[str, str]] = None,
    system_deps: Optional[List[str]] = None,
    build_system_deps: Optional[List[str]] = None,
    runtime_config: Optional[RuntimeConfig] = None,
    runtime_args: Optional[List[str]] = None,
) -> str:
    """Generate a multi-stage Dockerfile for a Go MCP package.

    The builder stage compiles from source using ``go install``.
    The runtime stage is a minimal Alpine image with just the binary
    and a non-root user.

    Parameters
    ----------
    go_package:
        The Go module import path (e.g.
        ``"github.com/strowk/mcp-k8s-go"``).
    builder_image:
        Override the base Go builder image.  When ``None``, uses
        the default from ``RuntimeConfig``.
    build_env:
        Build-time environment variables.
    system_deps:
        System packages to install in the runtime stage.
    build_system_deps:
        System packages to install only in the builder stage.
    runtime_config:
        Per-transport runtime configuration.
    runtime_args:
        Arguments to bake into the ENTRYPOINT.
    """
    # Resolve runtime config
    rc = runtime_config or RuntimeConfig.for_transport("go")
    image = builder_image or rc.builder_image

    go_package, validated_env, validated_deps = _validate_build_inputs(
        go_package, build_env, system_deps
    )
    validated_build_deps = validate_system_deps(build_system_deps or [])

    # Strip version from Go package for clean name
    clean_name = _strip_go_version(go_package)

    # Build typed template data
    data = TemplateData(
        package=go_package,
        package_clean=clean_name,
        binary="/app/mcp-server",
        builder_image=image,
        install_cmd=f"go install {go_package}",
        system_deps=validated_deps,
        build_system_deps=validated_build_deps,
        build_env=validated_env,
        additional_packages=rc.additional_packages,
        go_package=go_package,
        go_package_clean=clean_name,
        runtime_args=runtime_args or [],
    )

    return render_template("go.dockerfile.j2", asdict(data))


def generate_source_dockerfile(
    source_url: str,
    build_steps: List[str],
    entrypoint: List[str],
    *,
    source_ref: Optional[str] = None,
    builder_image: Optional[str] = None,
    build_env: Optional[Dict[str, str]] = None,
    system_deps: Optional[List[str]] = None,
    build_system_deps: Optional[List[str]] = None,
    runtime_config: Optional[RuntimeConfig] = None,
) -> str:
    """Generate a multi-stage Dockerfile that clones a git repository.

    The builder stage clones *source_url*, runs *build_steps*, and
    then copies the result into a minimal runtime stage.  *entrypoint*
    becomes the container ``ENTRYPOINT``.

    Parameters
    ----------
    source_url:
        HTTPS or git+ssh URL of the repository.
    build_steps:
        Shell commands to run inside the cloned repo (e.g. build).
    entrypoint:
        The container entrypoint command as a list.
    source_ref:
        Optional git ref (branch, tag, commit) to checkout.
    builder_image:
        Override the base Docker image.
    build_env:
        Build-time environment variables.
    system_deps:
        Runtime system packages.
    build_system_deps:
        Build-time system packages.
    runtime_config:
        Per-transport runtime overrides.
    """
    rc = runtime_config or RuntimeConfig.for_transport("uvx")
    image = builder_image or rc.builder_image

    validated_deps = validate_system_deps(system_deps or [])
    validated_build_deps = validate_system_deps(build_system_deps or [])
    validated_env: Dict[str, str] = {}
    if build_env:
        for k, v in build_env.items():
            validate_build_env_key(k)
            validate_build_env_value(v)
            validated_env[k] = v

    # Auto-inject git for the clone step (D6).
    if "git" not in validated_build_deps:
        validated_build_deps = ["git"] + validated_build_deps

    # Extract hostname for .netrc auth support.
    host = ""
    if source_url.startswith("https://"):
        try:
            from urllib.parse import urlparse

            host = urlparse(source_url).hostname or ""
        except ValueError:  # noqa: BLE001
            logger.debug("Failed to parse source URL hostname: %s", source_url)

    # Derive a package name for tagging from the URL.
    repo_name = source_url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")

    data = TemplateData(
        package=repo_name,
        package_clean=repo_name,
        binary=entrypoint[0] if entrypoint else "",
        builder_image=image,
        install_cmd="",
        system_deps=validated_deps,
        build_system_deps=validated_build_deps,
        build_env=validated_env,
        additional_packages=rc.additional_packages,
        source_url=source_url,
        source_ref=source_ref or "",
        build_steps=build_steps,
        entrypoint=entrypoint,
        source_url_host=host,
    )

    return render_template("source.dockerfile.j2", asdict(data))


def compute_image_tag(
    transport: str,
    package: str,
    dockerfile_content: str,
) -> str:
    """Compute a deterministic image tag from the Dockerfile content.

    The tag includes a content hash so that image rebuilds only occur
    when the Dockerfile actually changes (e.g. package version bump).
    """
    content_hash = hashlib.sha256(dockerfile_content.encode()).hexdigest()[:SHORT_ID_LENGTH]
    sanitized = _sanitize_image_name(_strip_version(package))
    return f"{IMAGE_PREFIX}/{transport}-{sanitized}:{content_hash}"
