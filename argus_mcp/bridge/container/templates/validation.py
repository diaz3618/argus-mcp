"""Input validation for template parameters — security-sensitive.

This module validates all user-supplied values before they reach the
Dockerfile templates.  It prevents shell injection, command injection,
and other attacks that could occur if unsanitized values are
interpolated into Dockerfiles.
"""

from __future__ import annotations

import re
from typing import List

# Shell-unsafe characters that must never appear in package names
# or system dependency names.
_SHELL_UNSAFE = re.compile(r"[;&|`$(){}\[\]<>!#~\n\r\\]")

# Valid build env key: uppercase letters, digits, underscore.
# Must start with a letter (not digit).
_ENV_KEY_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")

# Valid system dependency name: alphanumeric, dot, dash, plus, underscore.
# Must start with alphanumeric.
_SYSDEP_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._+\-]*$")

# Reserved environment variable keys that must not be overridden by
# users — they are set by the Dockerfile template itself.
_RESERVED_ENV_KEYS = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "SHELL",
        "HOSTNAME",
        "UV_TOOL_DIR",
        "UV_TOOL_BIN_DIR",
        "NODE_PATH",
    }
)


class ValidationError(ValueError):
    """Validation failed for a template input value.

    Raised when user-supplied values contain unsafe characters or
    violate naming conventions.  This is intentionally a subclass
    of ``ValueError`` so callers can catch either.
    """


def validate_package_name(name: str) -> str:
    """Validate a package name for safe use in Dockerfile commands.

    Parameters
    ----------
    name:
        The raw package specifier (e.g. ``"mcp-server-analyzer"``,
        ``"snyk@latest"``, ``"@upstash/context7-mcp"``).

    Returns
    -------
    str
        The validated (stripped) package name.

    Raises
    ------
    ValidationError
        If the name is empty, too long, or contains unsafe characters.
    """
    if not name or not name.strip():
        raise ValidationError("Package name must not be empty")
    name = name.strip()
    if _SHELL_UNSAFE.search(name):
        raise ValidationError(f"Package name contains unsafe characters: {name!r}")
    if len(name) > 256:
        raise ValidationError(f"Package name too long ({len(name)} > 256 chars)")
    return name


def validate_system_deps(deps: List[str]) -> List[str]:
    """Validate system dependency names for safe use in apt/apk commands.

    Parameters
    ----------
    deps:
        List of system package names (e.g. ``["ripgrep", "git"]``).

    Returns
    -------
    list[str]
        Validated dependency names (empty strings stripped).

    Raises
    ------
    ValidationError
        If any dependency name contains unsafe characters or does not
        match the expected naming pattern.
    """
    validated = []
    for dep in deps:
        dep = dep.strip()
        if not dep:
            continue
        if _SHELL_UNSAFE.search(dep):
            raise ValidationError(f"System dependency contains unsafe characters: {dep!r}")
        if not _SYSDEP_PATTERN.match(dep):
            raise ValidationError(f"System dependency name is not a valid package name: {dep!r}")
        if len(dep) > 128:
            raise ValidationError(
                f"System dependency name too long ({len(dep)} > 128 chars): {dep!r}"
            )
        validated.append(dep)
    return validated


def validate_build_env_key(key: str) -> str:
    """Validate a build environment variable key.

    Keys must be uppercase letters, digits, and underscores only,
    and must not collide with reserved variables set by the
    Dockerfile template.

    Parameters
    ----------
    key:
        The raw environment variable key.

    Returns
    -------
    str
        The validated key.

    Raises
    ------
    ValidationError
        If the key does not match the naming pattern or is reserved.
    """
    if not _ENV_KEY_PATTERN.match(key):
        raise ValidationError(
            f"Build env key must be uppercase letters, digits, and "
            f"underscore (starting with a letter): {key!r}"
        )
    if key in _RESERVED_ENV_KEYS:
        raise ValidationError(f"Build env key is reserved: {key!r}")
    return key


def validate_build_env_value(value: str) -> str:
    """Validate a build environment variable value.

    Values must not contain shell-dangerous characters that could
    enable command injection when interpolated into Dockerfile
    ``ARG`` / ``ENV`` directives.

    Parameters
    ----------
    value:
        The raw environment variable value.

    Returns
    -------
    str
        The validated value.

    Raises
    ------
    ValidationError
        If the value contains dangerous shell metacharacters.
    """
    dangerous = set(";&|`$(){}")
    found = dangerous.intersection(value)
    if found:
        raise ValidationError(f"Build env value contains dangerous characters {found}: {value!r}")
    return value
