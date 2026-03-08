"""Authorization policy definitions and loading.

Policies are specified as a list of rules, each with:
* ``effect``: ``"allow"`` or ``"deny"``
* ``roles``: list of role names this rule applies to (``["*"]`` = any role)
* ``resources``: list of resource patterns (tool names, server names)
  * ``"*"`` matches everything
  * ``"server:<name>"`` matches a specific backend server
  * ``"tool:<name>"`` matches a specific tool
  * ``"group:<name>"`` matches a server group

Example policy::

    {
        "effect": "allow",
        "roles": ["admin"],
        "resources": ["*"]
    }

    {
        "effect": "deny",
        "roles": ["viewer"],
        "resources": ["tool:dangerous_tool"]
    }
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class PolicyDecision(Enum):
    """Result of a policy evaluation."""

    ALLOW = "allow"
    DENY = "deny"
    NO_MATCH = "no_match"


@dataclass(frozen=True)
class AuthzPolicy:
    """A single authorization policy rule.

    Attributes
    ----------
    effect:
        ``"allow"`` or ``"deny"``.
    roles:
        Roles this rule applies to.  ``["*"]`` matches any role.
    resources:
        Resource patterns (tool names, server patterns).
    description:
        Human-readable description.
    """

    effect: str
    roles: List[str] = field(default_factory=lambda: ["*"])
    resources: List[str] = field(default_factory=lambda: ["*"])
    description: str = ""

    def matches(self, user_roles: List[str], resource: str) -> bool:
        """Return ``True`` if this policy matches the request."""
        role_match = "*" in self.roles or any(r in self.roles for r in user_roles)
        if not role_match:
            return False

        resource_match = "*" in self.resources or any(
            _resource_matches(pat, resource) for pat in self.resources
        )
        return resource_match

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AuthzPolicy:
        """Parse from a config dict."""
        return cls(
            effect=data.get("effect", "deny"),
            roles=data.get("roles", ["*"]),
            resources=data.get("resources", ["*"]),
            description=data.get("description", ""),
        )


def _resource_matches(pattern: str, resource: str) -> bool:
    """Check if *pattern* matches *resource*.

    Supports:
    * Exact match
    * Glob patterns (``tool:read_*``)
    * Wildcard (``*``)
    """
    if pattern == "*":
        return True
    return fnmatch.fnmatch(resource, pattern)


def load_policies(policy_list: List[Dict[str, Any]]) -> List[AuthzPolicy]:
    """Parse a list of policy dicts into :class:`AuthzPolicy` objects."""
    policies = []
    for item in policy_list:
        try:
            policies.append(AuthzPolicy.from_dict(item))
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("Skipping invalid policy %s: %s", item, exc)
    return policies
