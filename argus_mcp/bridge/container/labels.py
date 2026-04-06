"""Argus resource labeling constants.

Mirrors the Go-side constants in ``packages/argusd/internal/labels/labels.go``
so that both the Python container-creation path and the Go daemon agree on
label keys and semantics.

All Argus-managed containers/pods are tagged with these labels.  The argusd
daemon uses them as selectors so that unmanaged resources are invisible.
"""

from __future__ import annotations

from typing import Dict, Optional

# Label keys — must stay in sync with packages/argusd/internal/labels/labels.go
MANAGED = "argus.managed"
PROJECT = "argus.project"
SERVER_ID = "argus.server_id"
SESSION_ID = "argus.session_id"

MANAGED_VALUE = "true"


def default_labels(
    server_id: str,
    *,
    project: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, str]:
    """Return the base labels applied to every Argus-managed resource.

    Parameters
    ----------
    server_id:
        The MCP backend server name (``svr_name``).
    project:
        Optional project identifier.
    session_id:
        Optional session identifier.
    """
    labels: Dict[str, str] = {
        MANAGED: MANAGED_VALUE,
        SERVER_ID: server_id,
    }
    if project:
        labels[PROJECT] = project
    if session_id:
        labels[SESSION_ID] = session_id
    return labels
