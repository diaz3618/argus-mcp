"""Dockerfile template generation for MCP server images.

Generates multi-stage Dockerfiles following industry best practices:
- Builder stage installs the MCP package and its dependencies.
- Runtime stage copies only the installed artefacts — no build tools,
  no package caches, minimal attack surface.
- Non-root ``appuser`` (UID 10001) for least-privilege execution.

Supported transports
--------------------
``uvx``
    Python packages installed via ``uv tool install``.
    Builder: ``python:3.13-slim``.  Runtime: same image, copies
    ``/opt/uv-tools``.

``npx``
    Node.js packages installed via ``npm install --save``.
    Builder: ``node:22-alpine``.  Runtime: same image, copies
    ``node_modules``.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Default base images ──────────────────────────────────────────────────

UVX_BUILDER_IMAGE = "python:3.13-slim"
NPX_BUILDER_IMAGE = "node:22-alpine"

# ── Image tag prefix ─────────────────────────────────────────────────────
IMAGE_PREFIX = "arguslocal"


# ── Package name parsing ─────────────────────────────────────────────────


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
            remaining = remaining[:idx] + remaining[idx + 3:]
        elif idx + 1 < len(remaining):
            package = remaining[idx + 1]
            remaining = remaining[:idx] + remaining[idx + 2:]

    # Skip known uvx flags
    uvx_flags = {"--force", "--reinstall", "--python", "--with", "--index-url"}
    while remaining and remaining[0].startswith("-"):
        flag = remaining[0]
        remaining.pop(0)
        # Flags that take a value
        if flag in ("--python", "--with", "--index-url") and remaining:
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


def parse_npx_args(args: List[str]) -> Tuple[str, List[str]]:
    """Parse ``npx`` arguments into (package, runtime_args).

    Examples::

        ["-y", "@upstash/context7-mcp", "--api-key", "xxx"]
        → ("@upstash/context7-mcp", ["--api-key", "xxx"])

        ["-y", "mcp-remote", "https://developers.openai.com/mcp"]
        → ("mcp-remote", ["https://developers.openai.com/mcp"])

        ["-y", "@modelcontextprotocol/server-sequential-thinking"]
        → ("@modelcontextprotocol/server-sequential-thinking", [])

        ["-y", "snyk@latest", "mcp", "-t", "stdio"]
        → ("snyk@latest", ["mcp", "-t", "stdio"])
    """
    remaining = list(args)

    # Strip npx flags
    npx_flags = {"-y", "--yes", "-q", "--quiet"}
    while remaining and remaining[0] in npx_flags:
        remaining.pop(0)

    # First positional arg is the package
    package = remaining.pop(0) if remaining else "unknown"

    return package, remaining


def _strip_version(name: str) -> str:
    """Strip version suffix from a package name.

    Handles scoped packages: ``@org/pkg@1.0.0`` → ``@org/pkg``.
    Handles plain packages: ``pkg@1.2.3`` → ``pkg``.
    Handles ``@latest``: ``pkg@latest`` → ``pkg``.
    """
    if not name:
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


# ── Dockerfile generation ────────────────────────────────────────────────


def generate_uvx_dockerfile(
    package: str,
    binary: str,
    *,
    builder_image: str = UVX_BUILDER_IMAGE,
    extra_build_args: Optional[List[str]] = None,
    build_env: Optional[Dict[str, str]] = None,
) -> str:
    """Generate a multi-stage Dockerfile for a ``uvx`` package.

    The builder stage installs ``uv`` and the package into
    ``/opt/uv-tools``.  The runtime stage copies only the installed
    tool directory and runs as a non-root user.
    """
    # Determine base image OS type for correct package manager
    is_alpine = "alpine" in builder_image.lower()

    install_cmd = f"uv tool install {package}"
    # Convert @version to ==version for uv
    if "@" in package and not package.startswith("@"):
        pkg_name, ver = package.rsplit("@", 1)
        if ver != "latest":
            install_cmd = f"uv tool install '{pkg_name}=={ver}'"
        else:
            install_cmd = f"uv tool install {pkg_name}"

    env_lines = ""
    if build_env:
        for k, v in build_env.items():
            env_lines += f'ARG {k}="{v}"\nENV {k}="${{{k}}}"\n'

    if is_alpine:
        sys_deps = "RUN apk add --no-cache python3 py3-pip"
    else:
        sys_deps = (
            "RUN apt-get update && "
            "apt-get install -y --no-install-recommends python3 python3-pip python3-venv && "
            "rm -rf /var/lib/apt/lists/*"
        )

    return f"""\
# Auto-generated — do not edit.
FROM {builder_image} AS builder

{sys_deps}
RUN pip install --no-cache-dir --break-system-packages uv 2>/dev/null || pip install --no-cache-dir uv
{env_lines}
ENV UV_TOOL_DIR=/opt/uv-tools
RUN {install_cmd}

FROM {builder_image}
COPY --from=builder /opt/uv-tools /opt/uv-tools
ENV PATH="/opt/uv-tools/bin:$PATH"
RUN (adduser --disabled-password --uid 10001 appuser 2>/dev/null || adduser -D -u 10001 appuser)
USER appuser
ENTRYPOINT ["{binary}"]
"""


def generate_npx_dockerfile(
    package: str,
    *,
    builder_image: str = NPX_BUILDER_IMAGE,
    build_env: Optional[Dict[str, str]] = None,
) -> str:
    """Generate a multi-stage Dockerfile for an ``npx`` package.

    The builder stage runs ``npm install --save`` to fetch the package
    and all its dependencies.  The runtime stage copies only the
    ``node_modules`` directory and uses ``npx`` to run the package.
    """
    clean_name = _strip_version(package)

    env_lines = ""
    if build_env:
        for k, v in build_env.items():
            env_lines += f'ARG {k}="{v}"\nENV {k}="${{{k}}}"\n'

    return f"""\
# Auto-generated — do not edit.
FROM {builder_image} AS builder
WORKDIR /app
{env_lines}
RUN npm install --save {package}

FROM {builder_image}
WORKDIR /app
COPY --from=builder /app/node_modules /app/node_modules
ENV NODE_PATH=/app/node_modules
RUN (adduser -D -u 10001 appuser 2>/dev/null || adduser --disabled-password --uid 10001 appuser)
USER appuser
ENTRYPOINT ["npx", "{clean_name}"]
"""


# ── Image tag computation ────────────────────────────────────────────────


def compute_image_tag(
    transport: str,
    package: str,
    dockerfile_content: str,
) -> str:
    """Compute a deterministic image tag from the Dockerfile content.

    The tag includes a content hash so that image rebuilds only occur
    when the Dockerfile actually changes (e.g. package version bump).
    """
    content_hash = hashlib.sha256(dockerfile_content.encode()).hexdigest()[:12]
    sanitized = _sanitize_image_name(_strip_version(package))
    return f"{IMAGE_PREFIX}/{transport}-{sanitized}:{content_hash}"
