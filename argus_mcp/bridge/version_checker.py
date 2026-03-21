"""Version drift detection — compare running tool versions with registry.

Provides:
- ``DriftResult`` — version comparison model
- ``VersionChecker`` — compares backend capabilities against registry
- ``DriftSeverity`` — patch / minor / major classification
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class DriftSeverity(Enum):
    """Severity of a version drift."""

    CURRENT = "current"  # Versions match
    PATCH = "patch"  # e.g., 1.2.3 → 1.2.4
    MINOR = "minor"  # e.g., 1.2.3 → 1.3.0
    MAJOR = "major"  # e.g., 1.2.3 → 2.0.0
    UNKNOWN = "unknown"  # Cannot parse version


@dataclass(frozen=True)
class DriftResult:
    """Result of a version comparison for a single tool/server."""

    name: str
    current_version: str
    latest_version: str
    severity: DriftSeverity
    backend: str = ""

    @property
    def is_drifted(self) -> bool:
        return self.severity not in (DriftSeverity.CURRENT, DriftSeverity.UNKNOWN)


_SEMVER_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


def parse_semver(version: str) -> Optional[Tuple[int, int, int]]:
    """Parse a semver string into (major, minor, patch), or None."""
    m = _SEMVER_RE.match(version.strip())
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def classify_drift(current: str, latest: str) -> DriftSeverity:
    """Classify the severity of a version drift.

    Parameters
    ----------
    current:
        The currently running version.
    latest:
        The latest available version.

    Returns
    -------
    DriftSeverity
    """
    cur = parse_semver(current)
    lat = parse_semver(latest)

    if cur is None or lat is None:
        return DriftSeverity.UNKNOWN

    if cur >= lat:
        return DriftSeverity.CURRENT

    if cur[0] < lat[0]:
        return DriftSeverity.MAJOR
    if cur[1] < lat[1]:
        return DriftSeverity.MINOR
    return DriftSeverity.PATCH


class VersionChecker:
    """Compare running tool versions against a registry.

    Parameters
    ----------
    registry_client:
        An instance of :class:`RegistryClient`.
        If ``None``, version checking is disabled.
    """

    def __init__(self, registry_client: Optional[Any] = None) -> None:
        self._registry = registry_client

    async def check_all(
        self,
        capabilities: Dict[str, Dict[str, Any]],
    ) -> List[DriftResult]:
        """Check all capabilities for version drift.

        Parameters
        ----------
        capabilities:
            Mapping of tool name → capability info (with optional ``version``).

        Returns
        -------
        list
            :class:`DriftResult` for each capability with version info.
        """
        results: List[DriftResult] = []

        for name, info in capabilities.items():
            current_version = info.get("version", "")
            if not current_version:
                continue

            latest_version = await self._get_latest_version(name)
            if not latest_version:
                continue

            severity = classify_drift(current_version, latest_version)
            results.append(
                DriftResult(
                    name=name,
                    current_version=current_version,
                    latest_version=latest_version,
                    severity=severity,
                    backend=info.get("backend", ""),
                )
            )

        return results

    async def check_one(
        self,
        name: str,
        current_version: str,
    ) -> Optional[DriftResult]:
        """Check a single tool for version drift."""
        latest = await self._get_latest_version(name)
        if not latest:
            return None

        severity = classify_drift(current_version, latest)
        return DriftResult(
            name=name,
            current_version=current_version,
            latest_version=latest,
            severity=severity,
        )

    async def _get_latest_version(self, name: str) -> Optional[str]:
        """Look up the latest version from the registry."""
        if not self._registry:
            return None

        try:
            server = await self._registry.get_server(name)
            if server and hasattr(server, "version"):
                return server.version or None
        except Exception as exc:  # noqa: BLE001
            logger.debug("Registry lookup failed for '%s': %s", name, exc, exc_info=True)

        return None

    def get_drift_summary(self, results: List[DriftResult]) -> Dict[str, int]:
        """Summarize drift results by severity."""
        summary: Dict[str, int] = {s.value: 0 for s in DriftSeverity}
        for r in results:
            summary[r.severity.value] += 1
        return summary
